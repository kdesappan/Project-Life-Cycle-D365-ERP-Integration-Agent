import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
BASE = os.getenv("BACKEND_BASE_URL", "http://localhost:8001")
PORT = BASE.rsplit(":", 1)[-1]
XLSX = ROOT / "Sample contract excel file which user upload" / "Project agent 1a - Engagement Letter - Presight and Daypop_IFRS15_Analysis.xlsx"


def ensure_backend() -> bool:
    try:
        r = requests.get(f"{BASE}/health", timeout=2)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    cmd = [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", PORT, "--host", "0.0.0.0"]
    subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try:
            r = requests.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def wait_step(session_id: str, step_id: str, target: str, timeout_s: int = 120) -> dict:
    for _ in range(timeout_s):
        r = requests.get(f"{BASE}/api/sessions/{session_id}", timeout=10)
        if r.status_code == 200:
            sess = r.json()
            step = next((x for x in sess.get("steps", []) if x.get("id") == step_id), {})
            status = (step.get("status") or "").lower()
            if status == target.lower():
                return step
            if status == "failed" and target.lower() != "failed":
                raise RuntimeError(f"{step_id} failed early: {step.get('error_message')}")
        time.sleep(1)
    raise TimeoutError(f"Timeout waiting for {step_id} -> {target}")


def approve(session_id: str, step_id: str, note: str) -> dict:
    r = requests.post(
        f"{BASE}/api/sessions/{session_id}/steps/{step_id}/approve",
        json={"note": note},
        timeout=180,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Approve {step_id} failed: HTTP {r.status_code} {r.text[:400]}")
    session = r.json()
    return next((x for x in session.get("steps", []) if x.get("id") == step_id), {})


def print_calls(step: dict, label: str) -> None:
    calls = step.get("d365_calls", [])
    print(f"\n{label}: {step.get('status')} calls={len(calls)}")
    for c in calls:
        entity = c.get("entity")
        method = c.get("method")
        status_code = c.get("status_code")
        success = c.get("success")
        err = c.get("error")
        print(f"  - {entity} {method} -> HTTP {status_code} success={success}")
        if err:
            print(f"    error: {err}")


if not XLSX.exists():
    raise SystemExit(f"Missing workbook: {XLSX}")

if not ensure_backend():
    raise SystemExit(f"Backend not reachable on {BASE}")

with XLSX.open("rb") as f:
    up = requests.post(f"{BASE}/api/upload", files={"file": (XLSX.name, f)}, timeout=20)
if up.status_code != 200:
    raise SystemExit(f"Upload failed: {up.status_code} {up.text[:300]}")
session_id = up.json().get("session_id")
print("Session", session_id)

ext = requests.post(f"{BASE}/api/sessions/{session_id}/extract", timeout=30)
if ext.status_code != 200:
    raise SystemExit(f"Extract failed: {ext.status_code} {ext.text[:300]}")
wait_step(session_id, "project_master", "awaiting_approval")
print("Extraction ready")

step1 = approve(session_id, "reference_data", "prepare customer and reference masters")
print_calls(step1, "reference_data")
if (step1.get("status") or "").lower() == "failed":
    raise SystemExit("reference_data failed, stopping")

step3 = approve(session_id, "project_master", "create project hierarchy")
print_calls(step3, "project_master")

if (step3.get("status") or "").lower() == "failed":
    raise SystemExit(f"project_master failed: {step3.get('error_message')}")

print("\nproject_master succeeded")
