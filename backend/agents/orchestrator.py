"""Session orchestrator — manages the in-memory session store and coordinates agents."""
from __future__ import annotations

import uuid
from datetime import datetime
import re
from typing import Any, Dict, Optional

from backend.agents.d365_agent import execute_step
from backend.agents.extraction_agent import run_extraction
from backend.models.schemas import (
    D365CallResult,
    PROCESS_STEPS,
    ProcessStep,
    Session,
    SessionStatus,
    StepStatus,
)
from backend.services.d365_client import D365Client, build_client_from_env

# In-memory session store — keyed by session_id
_sessions: Dict[str, Session] = {}


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def create_session(filename: str, file_path: str) -> Session:
    session_id = str(uuid.uuid4())
    steps = [
        ProcessStep(
            id=s["id"],
            order=s["order"],
            name=s["name"],
            description=s["description"],
            payload_file=s["payload_file"],
            d365_entities=s["d365_entities"],
            icon=s["icon"],
        )
        for s in PROCESS_STEPS
    ]
    session = Session(
        session_id=session_id,
        filename=filename,
        file_path=file_path,
        steps=steps,
    )
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> Optional[Session]:
    return _sessions.get(session_id)


def list_sessions() -> list[Session]:
    return sorted(_sessions.values(), key=lambda s: s.created_at, reverse=True)


def delete_session(session_id: str) -> bool:
    if session_id in _sessions:
        del _sessions[session_id]
        return True
    return False


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def trigger_extraction(session_id: str) -> Session:
    session = _sessions[session_id]
    session.status = SessionStatus.EXTRACTING
    session.updated_at = datetime.utcnow()

    new_status, error = run_extraction(session.file_path, session.steps)
    session.status = new_status
    session.extraction_error = error
    session.updated_at = datetime.utcnow()
    return session


# ---------------------------------------------------------------------------
# Human approval / rejection
# ---------------------------------------------------------------------------

def approve_step(session_id: str, step_id: str, note: Optional[str], client: Optional[D365Client] = None) -> Session:
    session = _sessions[session_id]
    step = session.get_step(step_id)
    if step is None:
        raise ValueError(f"Step {step_id!r} not found in session {session_id!r}")
    if step.status not in (StepStatus.AWAITING_APPROVAL, StepStatus.FAILED):
        raise ValueError(f"Step {step_id!r} is not awaiting approval (current status: {step.status})")

    step.approval_note = note
    step.status = StepStatus.APPROVED

    # Execute D365 writes
    effective_client = client or build_client_from_env()
    if step.id != "project_contract":
        effective_contract_id = _get_session_effective_contract_id(session)
        if effective_contract_id and step.extracted_payload:
            _replace_contract_ids_in_payload(step.extracted_payload, {"", "PC-001"}, effective_contract_id)
    if step.id == "project_master":
        _apply_contract_title_to_project_names(session)
        _ensure_subprojects_for_ifrs15_obligations(session)
    execute_step(step, effective_client)

    # Keep downstream steps aligned to the effective contract selected/created in Step 2.
    if step.id == "project_contract":
        old_contract_id = _get_extracted_contract_id(step)
        effective_contract_id = _get_effective_contract_id_from_calls(step)
        if effective_contract_id:
            _propagate_contract_id_to_downstream_steps(session, old_contract_id, effective_contract_id)

    # Keep milestone billing aligned to the resolved project created in Step 3.
    if step.id == "project_master":
        effective_project_id = _get_effective_root_project_id_from_calls(step)
        if effective_project_id:
            _propagate_project_id_to_step(session, "project_contract", effective_project_id)
            _propagate_subproject_ids_to_ifrs15_obligations(session)
            _propagate_subproject_ids_to_milestone_billing(session)

        # In legacy mode, Step 2 defers ProjectFundingRules until projects exist.
        # Complete that deferred work now using the resolved project ID.
        if effective_project_id:
            deferred_calls = _post_deferred_funding_rules_after_project_creation(
                session, effective_client, effective_project_id
            )
            if deferred_calls:
                contract_step = session.get_step("project_contract")
                if contract_step is not None:
                    contract_step.d365_calls.extend(deferred_calls)

    session.updated_at = datetime.utcnow()
    _refresh_session_status(session)
    return session


def reject_step(session_id: str, step_id: str, reason: str) -> Session:
    session = _sessions[session_id]
    step = session.get_step(step_id)
    if step is None:
        raise ValueError(f"Step {step_id!r} not found")
    step.status = StepStatus.REJECTED
    step.rejection_reason = reason
    step.completed_at = datetime.utcnow()
    session.updated_at = datetime.utcnow()
    _refresh_session_status(session)
    return session


def retry_step(session_id: str, step_id: str, client: Optional[D365Client] = None) -> Session:
    session = _sessions[session_id]
    step = session.get_step(step_id)
    if step is None:
        raise ValueError(f"Step {step_id!r} not found")
    step.status = StepStatus.AWAITING_APPROVAL
    step.d365_calls = []
    step.error_message = None
    step.rejection_reason = None
    step.completed_at = None
    session.updated_at = datetime.utcnow()
    return session


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _refresh_session_status(session: Session) -> None:
    statuses = {s.status for s in session.steps}
    if StepStatus.FAILED in statuses:
        session.status = SessionStatus.FAILED
    elif all(s.status in (StepStatus.POSTED, StepStatus.SKIPPED, StepStatus.REJECTED) for s in session.steps):
        session.status = SessionStatus.COMPLETED
    elif StepStatus.POSTING in statuses or StepStatus.APPROVED in statuses:
        session.status = SessionStatus.PROCESSING
    else:
        session.status = SessionStatus.AWAITING_APPROVAL


def _get_extracted_contract_id(step: ProcessStep) -> str:
    payload = step.extracted_payload or {}
    headers = payload.get("ProjectContractHeaders") if isinstance(payload, dict) else None
    if isinstance(headers, list) and headers:
        return str(headers[0].get("ProjectContractId") or "")
    return ""


def _get_effective_contract_id_from_calls(step: ProcessStep) -> str:
    for call in reversed(step.d365_calls or []):
        body = call.response_body if isinstance(call.response_body, dict) else {}
        for key in ("_assigned_contract_id", "_matched_contract_id", "ProjectContractId", "ProjectContractID"):
            value = body.get(key)
            if value:
                return str(value)
    return ""


def _get_session_effective_contract_id(session: Session) -> str:
    contract_step = session.get_step("project_contract")
    if not contract_step:
        return ""
    effective_contract_id = _get_effective_contract_id_from_calls(contract_step)
    if effective_contract_id:
        return effective_contract_id
    return _get_extracted_contract_id(contract_step)


def _propagate_contract_id_to_downstream_steps(session: Session, old_id: str, new_id: str) -> None:
    if not new_id:
        return

    placeholder_ids = {"", "PC-001"}
    if old_id:
        placeholder_ids.add(old_id)

    for s in session.steps:
        if s.id == "project_contract" or not s.extracted_payload:
            continue
        _replace_contract_ids_in_payload(s.extracted_payload, placeholder_ids, new_id)


def _replace_contract_ids_in_payload(node: Any, candidate_ids: set[str], new_id: str) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            key_l = str(k).lower()
            if key_l in {"projectcontractid", "projectcontractid", "contractid", "contract id"}:
                current = "" if v is None else str(v).strip()
                if current in candidate_ids or not current.upper().startswith("PC-"):
                    node[k] = new_id
                    continue
            _replace_contract_ids_in_payload(v, candidate_ids, new_id)
        return

    if isinstance(node, list):
        for item in node:
            _replace_contract_ids_in_payload(item, candidate_ids, new_id)


def _get_effective_root_project_id_from_calls(step: ProcessStep) -> str:
    # Step 3 writes parent first, then children; prefer first assigned root-like ID.
    assigned_ids: list[str] = []
    for call in step.d365_calls or []:
        body = call.response_body if isinstance(call.response_body, dict) else {}
        val = body.get("_assigned_project_id")
        if val:
            assigned_ids.append(str(val))

    if assigned_ids:
        # Root typically does not end with a child suffix like -01, -02.
        for pid in assigned_ids:
            if not re.search(r"-\d{2}$", pid):
                return pid
        return assigned_ids[0]

    for call in step.d365_calls or []:
        body = call.response_body if isinstance(call.response_body, dict) else {}
        val = body.get("ProjectID") or body.get("ProjectId")
        if val:
            return str(val)
    return ""


def _propagate_project_id_to_step(session: Session, step_id: str, project_id: str) -> None:
    target = session.get_step(step_id)
    if not target or not target.extracted_payload:
        return

    _replace_project_ids_in_payload(target.extracted_payload, project_id)


def _replace_project_ids_in_payload(node: Any, project_id: str) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            key_l = str(k).lower()
            if key_l in {"projectid", "project id", "project_id", "project"}:
                current = "" if v is None else str(v).strip()
                # Keep explicit contract IDs untouched; only rewrite likely placeholders/derived values.
                if current == "" or current.upper().startswith("PROJ-"):
                    node[k] = project_id
                    continue
            _replace_project_ids_in_payload(v, project_id)
        return

    if isinstance(node, list):
        for item in node:
            _replace_project_ids_in_payload(item, project_id)


def _get_contract_title(session: Session) -> str:
    contract_step = session.get_step("project_contract")
    payload = contract_step.extracted_payload if contract_step and contract_step.extracted_payload else {}
    headers = payload.get("ProjectContractHeaders", []) if isinstance(payload, dict) else []
    if isinstance(headers, list) and headers:
        title = str(headers[0].get("Name") or "").strip()
        if title:
            return title
    return ""


def _apply_contract_title_to_project_names(session: Session) -> None:
    title = _get_contract_title(session)
    if not title:
        return
    project_step = session.get_step("project_master")
    if not project_step or not project_step.extracted_payload:
        return
    projects = project_step.extracted_payload.get("ProjectsV2", [])
    if not isinstance(projects, list):
        return
    for project in projects:
        if isinstance(project, dict):
            project["ProjectName"] = title


def _ensure_subprojects_for_ifrs15_obligations(session: Session) -> None:
    project_step = session.get_step("project_master")
    ifrs_step = session.get_step("ifrs15_obligations")
    if not project_step or not ifrs_step or not project_step.extracted_payload or not ifrs_step.extracted_payload:
        return

    projects = project_step.extracted_payload.get("ProjectsV2", [])
    lines = ifrs_step.extracted_payload.get("ProjectContractLines", [])
    if not isinstance(projects, list) or not isinstance(lines, list) or not projects or not lines:
        return

    parent = next(
        (p for p in projects if isinstance(p, dict) and not (p.get("ParentProjectId") or p.get("_parent_seq_key"))),
        None,
    )
    if not isinstance(parent, dict):
        return

    parent_seq_key = str(parent.get("_seq_key") or "0")
    subprojects = [
        p for p in projects
        if isinstance(p, dict) and (p.get("ParentProjectId") or p.get("_parent_seq_key"))
    ]

    for idx, line in enumerate(lines):
        if not isinstance(line, dict):
            continue

        if idx < len(subprojects):
            target = subprojects[idx]
        else:
            target = {
                "dataAreaId": parent.get("dataAreaId") or line.get("dataAreaId") or "2020",
                "ProjectID": "",
                "ProjectName": "",
                "ProjectContractId": parent.get("ProjectContractId") or line.get("ProjectContractId") or "",
                "ProjectGroupId": parent.get("ProjectGroupId") or "FP-WIP",
                "ProjectType": parent.get("ProjectType") or "FixedPrice",
                "ProjectStage": parent.get("ProjectStage") or "InProcess",
                "CustomerAccount": parent.get("CustomerAccount") or "",
                "_customer_name": parent.get("_customer_name") or "",
                "CurrencyCode": line.get("CurrencyCode") or parent.get("CurrencyCode") or "AED",
                "ProjectStartDate": line.get("StartDate") or parent.get("ProjectStartDate") or "2023-01-01",
                "ProjectSchedulingEndDate": line.get("EndDate") or parent.get("ProjectSchedulingEndDate") or "2026-12-31",
                "ParentProjectId": None,
                "LineProperty": parent.get("LineProperty") or "Chargeable",
                "_parent_seq_key": parent_seq_key,
                "_seq_key": str(len(projects)),
            }
            projects.append(target)
            subprojects.append(target)

        contract_title = _get_contract_title(session)
        target["ProjectName"] = contract_title or target.get("ProjectName") or f"POB-{idx + 1} Sub-project"
        target["ContractValueExcludingTax"] = line.get("LineAmountExcludingTax") or line.get("LineAmount") or 0.0
        target["CurrencyCode"] = line.get("CurrencyCode") or target.get("CurrencyCode") or "AED"


def _propagate_subproject_ids_to_ifrs15_obligations(session: Session) -> None:
    project_step = session.get_step("project_master")
    ifrs_step = session.get_step("ifrs15_obligations")
    if not project_step or not ifrs_step or not project_step.extracted_payload or not ifrs_step.extracted_payload:
        return

    projects = project_step.extracted_payload.get("ProjectsV2", [])
    if not isinstance(projects, list):
        return

    subprojects = [
        p for p in projects
        if isinstance(p, dict) and (p.get("ParentProjectId") or p.get("_parent_seq_key"))
    ]
    if not subprojects:
        return

    lines = ifrs_step.extracted_payload.get("ProjectContractLines", [])
    if isinstance(lines, list):
        for idx, line in enumerate(lines):
            if not isinstance(line, dict) or idx >= len(subprojects):
                continue
            subproject = subprojects[idx]
            project_id = subproject.get("ProjectID") or subproject.get("ProjectId")
            if project_id:
                line["ProjectId"] = project_id
                line["LineProjectId"] = project_id
                subproject["ContractValueExcludingTax"] = line.get("LineAmountExcludingTax") or line.get("LineAmount") or 0.0
                subproject["AllocationPercentOfTransactionPrice"] = line.get("AllocationPercentOfTransactionPrice") or line.get("allocationPercent") or subproject.get("AllocationPercentOfTransactionPrice")

    pob_rows = ifrs_step.extracted_payload.get("ifrs15PerformanceObligations", [])
    if isinstance(pob_rows, list):
        for idx, pob in enumerate(pob_rows):
            if not isinstance(pob, dict) or idx >= len(subprojects):
                continue
            project_id = subprojects[idx].get("ProjectID") or subprojects[idx].get("ProjectId")
            if project_id:
                pob["projectId"] = project_id


def _propagate_subproject_ids_to_milestone_billing(session: Session) -> None:
    project_step = session.get_step("project_master")
    milestone_step = session.get_step("milestone_billing")
    ifrs_step = session.get_step("ifrs15_obligations")
    if not project_step or not milestone_step or not project_step.extracted_payload or not milestone_step.extracted_payload:
        return

    projects = project_step.extracted_payload.get("ProjectsV2", [])
    rows = milestone_step.extracted_payload.get("ProjOnaccounttrans", [])
    if not isinstance(projects, list) or not isinstance(rows, list):
        return

    subprojects = [
        p for p in projects
        if isinstance(p, dict) and (p.get("ParentProjectId") or p.get("_parent_seq_key"))
    ]
    if not subprojects:
        return

    pob_to_project_id = {
        f"POB-{idx}": str(project.get("ProjectID") or project.get("ProjectId") or "")
        for idx, project in enumerate(subprojects, start=1)
    }
    pob_to_amount = _get_pob_allocated_amounts(ifrs_step)

    expanded_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        linked_pobs = row.get("_linked_pobs")
        if not isinstance(linked_pobs, list) or not linked_pobs:
            linked_pobs = ["POB-1"] if len(subprojects) == 1 else list(pob_to_project_id.keys())
        for pob in linked_pobs:
            pob_key = str(pob).upper().replace(" ", "-")
            project_id = pob_to_project_id.get(pob_key)
            if not project_id:
                continue
            split_amount = _split_milestone_amount_for_pob(row, pob_key, linked_pobs, pob_to_amount)
            new_row = {**row, "ProjectId": project_id, "_linked_pob": pob_key}
            if split_amount is not None:
                tax_amount = round(split_amount * 0.05, 2)
                new_row["Amount"] = split_amount
                new_row["TaxAmount"] = tax_amount
                new_row["AmountIncludingTax"] = round(split_amount + tax_amount, 2)
            expanded_rows.append(new_row)

    if expanded_rows:
        milestone_step.extracted_payload["ProjOnaccounttrans"] = expanded_rows


def _get_pob_allocated_amounts(ifrs_step: Optional[ProcessStep]) -> dict[str, float]:
    if not ifrs_step or not ifrs_step.extracted_payload:
        return {}

    amounts: dict[str, float] = {}
    lines = ifrs_step.extracted_payload.get("ProjectContractLines", [])
    if isinstance(lines, list):
        for idx, line in enumerate(lines, start=1):
            if not isinstance(line, dict):
                continue
            amount = line.get("LineAmountExcludingTax") or line.get("LineAmount")
            try:
                amounts[f"POB-{idx}"] = float(amount or 0.0)
            except (TypeError, ValueError):
                amounts[f"POB-{idx}"] = 0.0

    pob_rows = ifrs_step.extracted_payload.get("ifrs15PerformanceObligations", [])
    if isinstance(pob_rows, list):
        for pob in pob_rows:
            if not isinstance(pob, dict):
                continue
            pob_id = str(pob.get("pobId") or "").upper().replace(" ", "-")
            if not pob_id:
                continue
            amount = pob.get("allocatedTransactionPrice")
            try:
                amounts[pob_id] = float(amount or amounts.get(pob_id, 0.0))
            except (TypeError, ValueError):
                pass
    return amounts


def _split_milestone_amount_for_pob(
    row: dict[str, Any],
    pob_key: str,
    linked_pobs: list[Any],
    pob_to_amount: dict[str, float],
) -> Optional[float]:
    explicit = row.get("amountByPerformanceObligation") or row.get("_amount_by_performance_obligation")
    if isinstance(explicit, dict):
        for key, value in explicit.items():
            normalized = str(key).upper().replace(" ", "-")
            if normalized == pob_key:
                try:
                    return round(float(value or 0.0), 2)
                except (TypeError, ValueError):
                    return None

    try:
        amount = float(row.get("Amount") or 0.0)
    except (TypeError, ValueError):
        return None

    if row.get("_amount_is_pob_percent"):
        pob_amount = pob_to_amount.get(pob_key)
        if pob_amount is not None:
            return round(pob_amount * amount / 100.0, 2)

    linked_count = max(len(linked_pobs), 1)
    return round(amount / linked_count, 2)


def _post_deferred_funding_rules_after_project_creation(
    session: Session,
    client: D365Client,
    project_id: str,
) -> list[D365CallResult]:
    project_contract_step = session.get_step("project_contract")
    if not project_contract_step or not project_contract_step.extracted_payload:
        return []

    # Only run when Step 2 actually deferred funding rules.
    has_defer = any(
        c.entity == "ProjectFundingRules" and c.method == "DEFER"
        for c in (project_contract_step.d365_calls or [])
    )
    if not has_defer:
        return []

    payload = project_contract_step.extracted_payload
    headers = payload.get("ProjectContractHeaders", [])
    funding_sources = payload.get("ProjectContractFundingSources", [])
    funding_rules = payload.get("ProjectContractFundingRules", [])
    if not funding_rules:
        return []

    calls: list[D365CallResult] = [
        D365CallResult(
            entity="ProjectFundingRules",
            method="INFO",
            path="/ProjectFundingRules",
            status_code=200,
            success=True,
            response_body={
                "_action": "post_deferred_after_project_creation",
                "project_id": project_id,
                "deferred_count": len(funding_rules),
            },
            error=None,
            executed_at=datetime.utcnow(),
        )
    ]

    for fr in funding_rules:
        da = str(fr.get("dataAreaId") or (headers[0].get("dataAreaId") if headers else "2020"))
        contract_id = str(fr.get("ProjectContractId") or (headers[0].get("ProjectContractId") if headers else ""))
        post_body = {
            "dataAreaId": da,
            "ProjectContractId": contract_id,
            "ProjectId": project_id,
            "FundingSourceId": fr.get("FundingSourceId") or (funding_sources[0].get("FundingSourceId") if funding_sources else "FS-001"),
            "Priority": 1,
            "AllocationPercentage": float(fr.get("ContributionPercent") or 100.0),
            "AllocateRounding": "No",
        }
        post_body = {k: v for k, v in post_body.items() if v not in (None, "")}
        status, body = client.post("/ProjectFundingRules", post_body)
        calls.append(
            D365CallResult(
                entity="ProjectFundingRules",
                method="POST",
                path="/ProjectFundingRules",
                status_code=status,
                success=status in (200, 201, 409),
                response_body=body,
                error=None,
                executed_at=datetime.utcnow(),
            )
        )

    return calls
