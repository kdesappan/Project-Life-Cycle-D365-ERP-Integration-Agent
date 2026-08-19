"""Extraction agent — runs the Excel extractor and hydrates each ProcessStep."""
from __future__ import annotations

from datetime import datetime

from backend.models.schemas import ProcessStep, SessionStatus, StepStatus
from backend.services.excel_extractor import extract_all


def run_extraction(file_path: str, steps: list[ProcessStep]) -> tuple[SessionStatus, str | None]:
    """Extract all payloads and populate each step's extracted_payload field.

    Returns (new_session_status, error_message_or_None).
    """
    try:
        payloads = extract_all(file_path)
    except Exception as exc:  # noqa: BLE001
        return SessionStatus.FAILED, f"Excel extraction failed: {exc}"

    for step in steps:
        step.status = StepStatus.AWAITING_APPROVAL
        step.started_at = datetime.utcnow()
        payload = payloads.get(step.id, {})
        if "_extraction_error" in payload:
            step.status = StepStatus.FAILED
            step.error_message = payload["_extraction_error"]
        else:
            step.extracted_payload = payload

    return SessionStatus.AWAITING_APPROVAL, None
