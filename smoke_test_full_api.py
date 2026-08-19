from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8000"


def _print(msg: str) -> None:
    print(msg, flush=True)


def _find_sample_file() -> Path:
    files = sorted(Path("uploads").rglob("*.xlsx"))
    if not files:
        raise FileNotFoundError("No .xlsx file found under uploads/")
    return files[0]


def _get_session(session_id: str) -> dict:
    r = requests.get(f"{BASE_URL}/api/sessions/{session_id}", timeout=30)
    r.raise_for_status()
    return r.json()


def _wait_for_extraction(session_id: str, timeout_sec: int = 180) -> dict:
    start = time.time()
    while True:
        session = _get_session(session_id)
        status = session.get("status")
        step_statuses = {s.get("id"): s.get("status") for s in session.get("steps", [])}
        _print(f"Extraction poll: session_status={status}, steps={step_statuses}")

        if status in ("awaiting_approval", "failed"):
            return session

        if time.time() - start > timeout_sec:
            raise TimeoutError("Extraction did not reach awaiting_approval/failed within timeout")

        time.sleep(2)


def _approve_step(session_id: str, step_id: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/sessions/{session_id}/steps/{step_id}/approve",
        json={"note": "Automated smoke test"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def _step_summary(step: dict) -> str:
    calls = step.get("d365_calls", []) or []
    ok = sum(1 for c in calls if c.get("success"))
    bad = sum(1 for c in calls if not c.get("success"))
    return f"{step.get('id')}: status={step.get('status')}, calls={len(calls)}, success_calls={ok}, failed_calls={bad}"


def _print_milestone_details(session: dict) -> None:
    milestone = next((s for s in session.get("steps", []) if s.get("id") == "milestone_billing"), None)
    if not milestone:
        _print("Milestone step not found")
        return

    _print("\nMilestone Billing Call Details:")
    for c in milestone.get("d365_calls", []) or []:
        _print(
            "  - "
            + json.dumps(
                {
                    "entity": c.get("entity"),
                    "method": c.get("method"),
                    "path": c.get("path"),
                    "status_code": c.get("status_code"),
                    "success": c.get("success"),
                    "error": c.get("error"),
                },
                ensure_ascii=True,
            )
        )


def main() -> int:
    sample = _find_sample_file()
    _print(f"Using sample file: {sample}")

    with sample.open("rb") as fh:
        upload = requests.post(
            f"{BASE_URL}/api/upload",
            files={"file": (sample.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            timeout=60,
        )
    upload.raise_for_status()
    up = upload.json()
    session_id = up["session_id"]
    _print(f"Created session: {session_id}")

    ex = requests.post(f"{BASE_URL}/api/sessions/{session_id}/extract", timeout=30)
    ex.raise_for_status()
    _print("Extraction triggered")

    session = _wait_for_extraction(session_id)
    _print(f"Extraction completed with session status: {session.get('status')}")

    steps = sorted(session.get("steps", []), key=lambda s: s.get("order", 999))
    for step in steps:
        sid = step.get("id")
        st = step.get("status")
        if st not in ("awaiting_approval", "failed"):
            _print(f"Skipping {sid}: current status={st}")
            continue

        _print(f"Approving step: {sid}")
        session = _approve_step(session_id, sid)
        updated = next((s for s in session.get("steps", []) if s.get("id") == sid), {})
        _print("  " + _step_summary(updated))

    final_session = _get_session(session_id)
    _print("\nFinal Step Summary:")
    for step in sorted(final_session.get("steps", []), key=lambda s: s.get("order", 999)):
        _print("  " + _step_summary(step))

    _print_milestone_details(final_session)

    _print(f"\nFinal Session Status: {final_session.get('status')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _print(f"SMOKE TEST FAILED: {exc}")
        raise
