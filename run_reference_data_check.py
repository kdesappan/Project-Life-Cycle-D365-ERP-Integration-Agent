import json
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


def ensure_backend():
    try:
        r = requests.get(f"{BASE}/health", timeout=2)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    cmd = [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", PORT, "--host", "0.0.0.0"]
    subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(25):
        try:
            r = requests.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def fail(msg: str):
    print(msg)
    raise SystemExit(1)


if not XLSX.exists():
    fail(f"Missing test workbook: {XLSX}")

if not ensure_backend():
    fail(f"Backend not reachable on {BASE}/health")

print("Health OK")

with XLSX.open("rb") as f:
    up = requests.post(f"{BASE}/api/upload", files={"file": (XLSX.name, f)}, timeout=20)
if up.status_code != 200:
    fail(f"Upload failed: HTTP {up.status_code} {up.text[:300]}")
session_id = up.json().get("session_id")
if not session_id:
    fail(f"Upload missing session_id: {up.text[:300]}")
print("Session", session_id)

ext = requests.post(f"{BASE}/api/sessions/{session_id}/extract", timeout=40)
if ext.status_code != 200:
    fail(f"Extract failed: HTTP {ext.status_code} {ext.text[:300]}")
print("Extract OK")

# Extraction may complete asynchronously; wait until reference_data is awaiting_approval.
ready = False
for _ in range(60):
    s = requests.get(f"{BASE}/api/sessions/{session_id}", timeout=10)
    if s.status_code == 200:
        sess = s.json()
        step = next((x for x in sess.get("steps", []) if x.get("id") == "reference_data"), {})
        st = (step.get("status") or "").lower()
        if st == "awaiting_approval":
            ready = True
            break
        if st == "failed":
            fail(f"Extraction step failed before approval: {step.get('error_message')}")
    time.sleep(1)

if not ready:
    fail("Timed out waiting for reference_data to become awaiting_approval")

app = requests.post(
    f"{BASE}/api/sessions/{session_id}/steps/reference_data/approve",
    json={"note": "validate customer address creation"},
    timeout=120,
)
if app.status_code != 200:
    fail(f"Approve failed: HTTP {app.status_code} {app.text[:400]}")

session_after = app.json()
step = next((x for x in session_after.get("steps", []) if x.get("id") == "reference_data"), {})
calls = step.get("d365_calls", [])
print("Calls", len(calls))

address_related = []
for c in calls:
    entity = (c.get("entity") or "")
    path = (c.get("path") or "")
    key = f"{entity} {path}".lower()
    if "postal" in key or "address" in key:
        address_related.append(c)

print("AddressCalls", len(address_related))
for idx, c in enumerate(address_related, start=1):
    print(
        json.dumps(
            {
                "i": idx,
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

# Print customer call response snippets for assigned/matched account tracking
for c in calls:
    if c.get("entity") == "CustomersV3" and c.get("method") in ("GET", "POST"):
        body = c.get("response_body") or {}
        snippet = {
            "entity": c.get("entity"),
            "method": c.get("method"),
            "status_code": c.get("status_code"),
            "success": c.get("success"),
            "_matched_account": body.get("_matched_account"),
            "_assigned_account": body.get("_assigned_account"),
            "_address_to_create": body.get("_address_to_create"),
        }
        print(json.dumps(snippet, ensure_ascii=True))

failed = [c for c in calls if not c.get("success")]
print("FailedCalls", len(failed))
if failed:
    print("StepStatus", step.get("status"), "Error", step.get("error_message"))
