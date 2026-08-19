"""FastAPI application — REST endpoints for the D365 Project Lifecycle Integration Agent."""
from __future__ import annotations

import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from backend.agents.orchestrator import (
    approve_step,
    create_session,
    delete_session,
    get_session,
    list_sessions,
    reject_step,
    retry_step,
    trigger_extraction,
)
from backend.models.schemas import (
    ApprovalRequest,
    D365Settings,
    RejectionRequest,
    Session,
    UploadResponse,
)
from backend.services.d365_client import D365Client

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="D365 Project Lifecycle Integration Agent",
    description="Multi-agent system for end-to-end D365 F&O project lifecycle integration with human approval",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-request D365 settings override (stored in memory; seeded from .env on startup)
_d365_overrides: dict[str, D365Settings] = {}
# Per-session D365 settings snapshot to keep one principal for all approvals in the session.
_session_d365_settings: dict[str, D365Settings] = {}


def _seed_settings_from_env() -> None:
    """Populate the global override from .env so the frontend never needs to re-enter credentials."""
    base_url = os.getenv("D365_BASE_URL") or f"https://{os.getenv('D365_ENVIRONMENT','demo-env')}.operations.dynamics.com"
    _d365_overrides["global"] = D365Settings(
        base_url=base_url,
        tenant_id=os.getenv("D365_TENANT_ID", ""),
        client_id=os.getenv("D365_CLIENT_ID", ""),
        client_secret=os.getenv("D365_CLIENT_SECRET", ""),
        data_area_id=os.getenv("D365_DATA_AREA_ID", os.getenv("D365_COMPANY", "2020")),
    )


_seed_settings_from_env()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# D365 connection
# ---------------------------------------------------------------------------

@app.get("/api/d365/settings", tags=["d365"])
def get_d365_settings() -> dict:
    """Return current effective settings (secret is masked)."""
    s = _d365_overrides.get("global")
    if not s:
        return {}
    return {
        "base_url": s.base_url,
        "tenant_id": s.tenant_id,
        "client_id": s.client_id,
        "secret_set": bool(s.client_secret),
        "data_area_id": s.data_area_id,
    }

@app.post("/api/d365/settings", tags=["d365"])
def save_d365_settings(settings: D365Settings) -> dict:
    """Save D365 credentials for this server process (not persisted to disk)."""
    _d365_overrides["global"] = settings
    return {"saved": True}


@app.get("/api/d365/test", tags=["d365"])
def test_d365_connection() -> dict:
    settings = _d365_overrides.get("global")
    client = _build_client(settings)
    ok, msg = client.test_connection()
    return {"success": ok, "message": msg}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@app.get("/api/sessions", tags=["sessions"])
def get_sessions() -> list[Session]:
    return list_sessions()


@app.get("/api/sessions/{session_id}", tags=["sessions"])
def get_session_endpoint(session_id: str) -> Session:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.delete("/api/sessions/{session_id}", tags=["sessions"])
def remove_session(session_id: str) -> dict:
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    _session_d365_settings.pop(session_id, None)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Upload & extraction
# ---------------------------------------------------------------------------

@app.post("/api/upload", tags=["upload"], response_model=UploadResponse)
async def upload_contract(file: UploadFile = File(...)) -> UploadResponse:
    """Upload a signed/unsigned contract Excel workbook and create a new session."""
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx / .xls files are accepted")

    dest = UPLOAD_DIR / f"{file.filename}"
    # Use a unique subfolder to avoid collisions
    import uuid as _uuid
    unique_dir = UPLOAD_DIR / str(_uuid.uuid4())
    unique_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_dir / file.filename

    content = await file.read()
    dest.write_bytes(content)

    session = create_session(filename=file.filename, file_path=str(dest))
    # Pin credentials at upload time so all subsequent steps use the same principal.
    global_settings = _d365_overrides.get("global")
    if global_settings:
        _session_d365_settings[session.session_id] = deepcopy(global_settings)
    return UploadResponse(session_id=session.session_id, filename=file.filename, message="File uploaded. Click 'Extract & Process' to continue.")


@app.post("/api/sessions/{session_id}/extract", tags=["extraction"])
def extract_session(session_id: str, background_tasks: BackgroundTasks) -> dict:
    """Trigger Excel extraction for the session (runs synchronously — may take a few seconds)."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    background_tasks.add_task(_run_extraction_bg, session_id)
    return {"message": "Extraction started", "session_id": session_id}


def _run_extraction_bg(session_id: str) -> None:
    trigger_extraction(session_id)


# ---------------------------------------------------------------------------
# Step approval / rejection / retry
# ---------------------------------------------------------------------------

@app.post("/api/sessions/{session_id}/steps/{step_id}/approve", tags=["approval"])
def approve(session_id: str, step_id: str, body: ApprovalRequest) -> Session:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    settings = _session_d365_settings.get(session_id) or _d365_overrides.get("global")
    client = _build_client(settings)
    try:
        return approve_step(session_id, step_id, note=body.note, client=client)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/steps/{step_id}/reject", tags=["approval"])
def reject(session_id: str, step_id: str, body: RejectionRequest) -> Session:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return reject_step(session_id, step_id, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/steps/{step_id}/retry", tags=["approval"])
def retry(session_id: str, step_id: str) -> Session:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return retry_step(session_id, step_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_client(settings: Optional[D365Settings]) -> D365Client:
    if settings:
        return D365Client(
            base_url=settings.base_url,
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            data_area_id=settings.data_area_id,
        )
    from backend.services.d365_client import build_client_from_env
    return build_client_from_env()
