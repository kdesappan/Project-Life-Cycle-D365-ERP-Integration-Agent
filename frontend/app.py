"""Streamlit UI — D365 Project Lifecycle Integration Agent."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import requests
import streamlit as st

BACKEND = os.getenv("D365_AGENT_BACKEND_URL", "http://localhost:8000").rstrip("/")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="D365 Project Lifecycle Agent",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ---- Global — force light background on every Streamlit container ---- */
html, body {
    background: #f5f7fa !important;
    color: #1a202c !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
.stApp, [data-testid="stApp"],
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
[data-testid="block-container"],
section.main, section.main > div,
.main .block-container {
    background: #f5f7fa !important;
    color: #1a202c !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebarContent"] {
    background: #ffffff !important;
    border-right: 1px solid #e2e8f0 !important;
    box-shadow: 2px 0 8px rgba(0,0,0,.06);
}
[data-testid="stSidebar"] * { color: #2d3748 !important; }
/* header toolbar */
[data-testid="stHeader"], header[data-testid="stHeader"] {
    background: #ffffff !important;
    border-bottom: 1px solid #e5e7eb !important;
}

/* ---- Typography ---- */
h1, h2, h3, h4 { font-family: 'Inter', sans-serif !important; color: #1a202c !important; font-weight: 700 !important; }
p, li, label, span, div { font-family: 'Inter', sans-serif !important; }
code, pre, .stCode { font-family: 'JetBrains Mono', 'Fira Code', monospace !important; font-size: 12.5px !important; }

/* ---- Streamlit default widget text ---- */
[data-testid="stMarkdownContainer"] p { color: #374151 !important; font-size: 14px; line-height: 1.65; }
[data-testid="stMarkdownContainer"] li { color: #374151 !important; }
[data-testid="stMarkdownContainer"] strong { color: #111827 !important; }

/* ---- Sidebar labels ---- */
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stTextInput label { color: #374151 !important; }

/* ---- Cards ---- */
.step-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 18px 22px;
    margin-bottom: 14px;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
    transition: border-color .2s, box-shadow .2s;
}
.step-card:hover { border-color: #3b82f6; box-shadow: 0 4px 12px rgba(59,130,246,.12); }

/* ---- Status badges ---- */
.badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .3px;
    font-family: 'Inter', sans-serif;
}
.badge-pending        { background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; }
.badge-extracting     { background: #dbeafe; color: #1d4ed8; border: 1px solid #93c5fd; }
.badge-awaiting       { background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; }
.badge-approved       { background: #d1fae5; color: #065f46; border: 1px solid #6ee7b7; }
.badge-posting        { background: #e0e7ff; color: #3730a3; border: 1px solid #a5b4fc; }
.badge-posted         { background: #059669; color: #ffffff; border: 1px solid #059669; }
.badge-rejected       { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
.badge-failed         { background: #dc2626; color: #ffffff; border: 1px solid #dc2626; }
.badge-skipped        { background: #f8fafc; color: #94a3b8; border: 1px solid #e2e8f0; }

/* ---- Buttons ---- */
.stButton > button {
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    font-size: 13.5px !important;
    transition: all .18s ease !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #2563eb, #1d4ed8) !important;
    border: none !important;
    color: #fff !important;
    box-shadow: 0 2px 8px rgba(37,99,235,.35) !important;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #1d4ed8, #1e40af) !important;
    box-shadow: 0 4px 14px rgba(37,99,235,.45) !important;
    transform: translateY(-1px) !important;
}
.stButton > button:not([kind="primary"]) {
    background: #ffffff !important;
    border: 1.5px solid #d1d5db !important;
    color: #374151 !important;
}
.stButton > button:not([kind="primary"]):hover {
    border-color: #3b82f6 !important;
    color: #2563eb !important;
    box-shadow: 0 2px 8px rgba(59,130,246,.15) !important;
}

/* ---- Inputs ---- */
.stTextInput input, .stSelectbox select {
    font-family: 'Inter', sans-serif !important;
    font-size: 13.5px !important;
    border-radius: 8px !important;
    border: 1.5px solid #d1d5db !important;
    color: #1a202c !important;
    background: #ffffff !important;
}
.stTextInput input:focus { border-color: #3b82f6 !important; box-shadow: 0 0 0 3px rgba(59,130,246,.15) !important; }

/* ---- Tabs ---- */
[data-testid="stTabs"] [data-baseweb="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #6b7280 !important;
}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
    color: #2563eb !important;
    border-bottom-color: #2563eb !important;
}

/* ---- Expanders ---- */
[data-testid="stExpander"] summary {
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    color: #1a202c !important;
    background: #ffffff !important;
    border-radius: 10px !important;
    border: 1px solid #e5e7eb !important;
    padding: 12px 16px !important;
}
[data-testid="stExpander"] summary:hover { border-color: #3b82f6 !important; }
[data-testid="stExpander"] > div { background: #fafbfc !important; border-radius: 0 0 10px 10px !important; border: 1px solid #e5e7eb !important; border-top: none !important; }

/* ---- Dataframe ---- */
[data-testid="stDataFrame"] { border-radius: 8px !important; overflow: hidden !important; border: 1px solid #e2e8f0 !important; }

/* ---- Alert boxes ---- */
[data-testid="stAlert"] { border-radius: 8px !important; font-family: 'Inter', sans-serif !important; font-size: 13.5px !important; }

/* ---- Toggle ---- */
[data-testid="stToggle"] label { font-family: 'Inter', sans-serif !important; color: #374151 !important; }

/* ---- Section headers ---- */
.section-title {
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 700;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    margin-bottom: 8px;
}

/* ---- Pipeline bar ---- */
.pipeline-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 20px;
    padding: 14px 18px;
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,.05);
}
.pipeline-node {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    font-family: 'Inter', sans-serif;
    font-weight: 500;
    padding: 4px 10px;
    border-radius: 20px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
}
.pipeline-arrow { color: #d1d5db; font-size: 16px; }

/* ---- Scrollbar ---- */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #f1f5f9; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATUS_BADGE = {
    "pending":          ('<span class="badge badge-pending">⏳ Pending</span>',          "#64748b"),
    "extracting":       ('<span class="badge badge-extracting">🔄 Extracting</span>',     "#1d4ed8"),
    "awaiting_approval":('<span class="badge badge-awaiting">👁 Awaiting Approval</span>', "#92400e"),
    "approved":         ('<span class="badge badge-approved">✅ Approved</span>',          "#065f46"),
    "posting":          ('<span class="badge badge-posting">📡 Posting to D365</span>',   "#3730a3"),
    "posted":           ('<span class="badge badge-posted">🟢 Posted</span>',              "#059669"),
    "rejected":         ('<span class="badge badge-rejected">🚫 Rejected</span>',         "#991b1b"),
    "failed":           ('<span class="badge badge-failed">❌ Failed</span>',              "#dc2626"),
    "skipped":          ('<span class="badge badge-skipped">⏭ Skipped</span>',            "#94a3b8"),
}

def _badge(status: str) -> str:
    return STATUS_BADGE.get(status, (f'<span class="badge">{status}</span>', "#fff"))[0]

def _api(method: str, path: str, **kwargs) -> tuple[int, Any]:
    # Approve/extract can trigger several sequential D365 round-trips server-side
    # (each allowed up to 60s), so give this client call plenty of headroom.
    timeout = kwargs.pop("timeout", 180)
    try:
        resp = getattr(requests, method)(f"{BACKEND}{path}", timeout=timeout, **kwargs)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, resp.text
    except requests.exceptions.ReadTimeout:
        return 0, {"error": f"Backend did not respond within {timeout}s — D365 may be slow/hibernated. Refresh and check the step status before retrying."}
    except requests.exceptions.ConnectionError:
        return 0, {"error": "Cannot reach backend. Is the FastAPI server running?"}

def _backend_alive() -> bool:
    code, _ = _api("get", "/health")
    return code == 200

def _describe_call_outcome(call: dict) -> str:
    """Human-readable one-liner for a successful/deferred D365 call, mirroring the
    failure-hint logic so success summaries are just as informative as failures."""
    method = call.get("method", "")
    entity = call.get("entity", "")
    rb = call.get("response_body") or {}
    code = call.get("status_code", "—")

    if method == "DEFER":
        return rb.get("reason") or "Deferred — not applicable/available in this tenant."
    if method == "INFO":
        return rb.get("_note") or f"Assigned new ID: {rb.get('_assigned_contract_id') or rb.get('_assigned_project_id') or '—'}"
    if method == "GET":
        if rb.get("_action") == "skip_create":
            matched = rb.get("_matched_contract_id") or rb.get("_resolved_account") or ""
            return f"Already exists in D365{f' ({matched})' if matched else ''} — skipped create (idempotent)."
        if rb.get("_resolved_account"):
            return f"Resolved customer account: {rb.get('_resolved_account')}"
        return "Verified in D365."
    if method == "POST":
        if code == 409:
            return f"{entity} already exists (safe no-op)."
        if entity in ("Projects", "ProjectsV2"):
            id_fields = ("ProjectID", "ProjectId")
        else:
            id_fields = ("ProjectContractID", "ProjectContractId")
        id_fields += ("ContractLineId", "CustomerAccount")
        new_id = next((rb.get(f) for f in id_fields if rb.get(f)), "")
        return f"Created successfully{f' — {new_id}' if new_id else ''}."
    if method == "PATCH":
        return "Updated successfully."
    return f"Completed (HTTP {code})."

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

if "session_id" not in st.session_state:
    st.session_state["session_id"] = None
if "polling" not in st.session_state:
    st.session_state["polling"] = False
# Load effective settings from backend once per session (avoids re-entering credentials)
if "d365_cfg" not in st.session_state:
    _, _cfg = _api("get", "/api/d365/settings")
    st.session_state["d365_cfg"] = _cfg if isinstance(_cfg, dict) else {}

# ---------------------------------------------------------------------------
# Sidebar — D365 settings
# ---------------------------------------------------------------------------

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Microsoft_logo.svg/240px-Microsoft_logo.svg.png", width=120)
    st.markdown("<h2 style='font-size:17px;font-weight:700;color:#1a202c;margin:8px 0 4px;'>D365 F&O Integration Agent</h2>", unsafe_allow_html=True)
    st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:10px 0 14px;'>", unsafe_allow_html=True)

    st.markdown('<div class="section-title">🔗 D365 Connection</div>', unsafe_allow_html=True)

    _cfg = st.session_state["d365_cfg"]
    _secret_already_set = _cfg.get("secret_set", False)

    # Read-only status — credentials auto-loaded from .env
    if _cfg:
        _secret_badge = "🔑 Secret: configured" if _secret_already_set else "⚠️ Secret: not set"
        _color = "#059669" if _secret_already_set else "#d97706"
        st.markdown(
            f"<div style='background:#f0fdf4;border:1px solid #86efac;border-radius:8px;"
            f"padding:8px 12px;font-size:12px;font-family:Inter,sans-serif;margin-bottom:10px;'>"
            f"<span style='color:#059669;font-weight:700;'>⬤</span> Live — credentials loaded from .env<br>"
            f"<span style='color:#6b7280;'>{_secret_badge} &nbsp;·&nbsp; Company: {_cfg.get('data_area_id','—')}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with st.expander("⚙️ Override credentials", expanded=not _secret_already_set):
        d365_url = st.text_input("D365 Base URL", value=_cfg.get("base_url", ""))
        d365_tenant = st.text_input("Tenant ID", value=_cfg.get("tenant_id", ""))
        d365_client_id = st.text_input("Client ID", value=_cfg.get("client_id", ""))
        d365_secret = st.text_input(
            "Client Secret" + (" (leave blank to keep existing)" if _secret_already_set else ""),
            type="password",
        )
        d365_da = st.text_input("Company / Data Area ID", value=_cfg.get("data_area_id", "2020"))

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Save", use_container_width=True):
                _, resp = _api("post", "/api/d365/settings", json={
                    "base_url": d365_url,
                    "tenant_id": d365_tenant,
                    "client_id": d365_client_id,
                    "client_secret": d365_secret if d365_secret else "",
                    "data_area_id": d365_da,
                })
                if isinstance(resp, dict) and resp.get("saved"):
                    _, _new_cfg = _api("get", "/api/d365/settings")
                    st.session_state["d365_cfg"] = _new_cfg if isinstance(_new_cfg, dict) else {}
                    st.success("Saved")
                    st.rerun()
                else:
                    st.error("Failed to save")
        with col2:
            if st.button("🔌 Test Connection", use_container_width=True):
                _, resp = _api("get", "/api/d365/test")
                if isinstance(resp, dict) and resp.get("success"):
                    st.success(resp.get("message", "OK"))
                else:
                    msg = resp.get("message", str(resp)) if isinstance(resp, dict) else str(resp)
                    st.warning(msg)

    st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:10px 0 14px;'>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">📂 Sessions</div>', unsafe_allow_html=True)

    _, sessions_data = _api("get", "/api/sessions")
    sessions_list = sessions_data if isinstance(sessions_data, list) else []

    if sessions_list:
        session_options = {
            f"{s['filename']} ({s['session_id'][:8]}…)": s["session_id"]
            for s in sessions_list
        }
        chosen_label = st.selectbox("Load previous session", ["— New session —"] + list(session_options.keys()))
        if chosen_label != "— New session —" and st.button("Load", use_container_width=True):
            st.session_state["session_id"] = session_options[chosen_label]
            st.rerun()
    else:
        st.caption("No sessions yet.")

    st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:10px 0 14px;'>", unsafe_allow_html=True)
    st.markdown(
        """
<div style='font-size:11.5px;color:#6b7280;font-family:Inter,sans-serif;line-height:1.8;'>
<span style='font-weight:700;color:#374151;'>Process order</span><br>
① Ref. Data &nbsp;→&nbsp; ② Contract &nbsp;→&nbsp; ③ Projects<br>
→ ④ IFRS 15 &nbsp;→&nbsp; ⑤ Milestones &nbsp;→&nbsp; ⑥ Invoices<br>
→ ⑦ Revenue Recognition
</div>
""",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Backend health banner
# ---------------------------------------------------------------------------

if not _backend_alive():
    st.error(
        "⚠️ **Backend offline.** This frontend cannot reach the FastAPI backend. "
        "For Streamlit Community Cloud, add the public backend URL as the `D365_AGENT_BACKEND_URL` secret. "
        "For local use, start FastAPI with `uvicorn backend.main:app --reload --port 8000`.",
        icon="🚨",
    )
    st.stop()

# ---------------------------------------------------------------------------
# Main header
# ---------------------------------------------------------------------------

st.markdown(
    """
<div style='display:flex;align-items:center;gap:14px;margin-bottom:6px;padding:20px 24px;background:#ffffff;border-radius:14px;border:1px solid #e5e7eb;box-shadow:0 2px 8px rgba(0,0,0,.06);'>
  <div style='width:52px;height:52px;background:linear-gradient(135deg,#2563eb,#7c3aed);border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:1.6rem;flex-shrink:0;'>🏗️</div>
  <div>
    <h1 style='margin:0 0 2px;font-size:1.55rem;font-weight:700;color:#111827;font-family:Inter,sans-serif;'>D365 Project Lifecycle Integration Agent</h1>
    <p style='margin:0;color:#6b7280;font-size:13.5px;font-family:Inter,sans-serif;'>Upload a contract workbook &rarr; extract &rarr; review &rarr; <strong style="color:#2563eb;">approve</strong> &rarr; post to Microsoft Dynamics 365 F&amp;O</p>
  </div>
</div>
<div style='height:18px;'></div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Upload section
# ---------------------------------------------------------------------------

current_session = None
if st.session_state["session_id"]:
    _, current_session_data = _api("get", f"/api/sessions/{st.session_state['session_id']}")
    if isinstance(current_session_data, dict) and "session_id" in current_session_data:
        current_session = current_session_data

upload_col, info_col = st.columns([2, 1])

with upload_col:
    st.markdown("### 📤 Upload Contract Workbook")
    uploaded_file = st.file_uploader(
        "Drag & drop your signed/unsigned contract Excel file (.xlsx)",
        type=["xlsx", "xls"],
        help="The workbook should contain sheets for: Reference Data, Contract, Projects, IFRS 15, Milestones, Invoices, Revenue Recognition",
    )

    col_upload, col_extract = st.columns(2)
    with col_upload:
        if st.button("📁 Upload File", disabled=uploaded_file is None, use_container_width=True, type="primary"):
            with st.spinner("Uploading…"):
                code, resp = _api("post", "/api/upload", files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
            if code == 200 and isinstance(resp, dict):
                st.session_state["session_id"] = resp["session_id"]
                st.success(f"✅ Uploaded: **{resp['filename']}** — Session `{resp['session_id'][:8]}…`")
                st.rerun()
            else:
                st.error(f"Upload failed: {resp}")

    with col_extract:
        extract_disabled = current_session is None or current_session.get("status") not in ("created", "failed")
        if st.button("⚙️ Extract & Process", disabled=extract_disabled, use_container_width=True):
            with st.spinner("Running extraction agents…"):
                code, resp = _api("post", f"/api/sessions/{st.session_state['session_id']}/extract")
            if code == 200:
                st.info("Extraction started — page will auto-refresh")
                time.sleep(3)
                st.rerun()
            else:
                st.error(f"Extraction failed: {resp}")

with info_col:
    st.markdown("### 📋 Expected Workbook Sheets")
    st.markdown(
        """
| # | Sheet | D365 Entities |
|---|-------|---------------|
| 1 | Reference / Master Data | LegalEntities, CustomersV3 |
| 2 | Project Contract | ProjectContractHeaders |
| 3 | Project Master | ProjectsV2 |
| 4 | IFRS 15 / POBs | Projects sub-project allocation |
| 5 | Milestone Schedule | ProjectBillingSchedules |
| 6 | Invoice Schedule | ProjectInvoiceProposals |
| 7 | Revenue Recognition | D365 Revenue Recognition Automation Batch |
"""
    )

# ---------------------------------------------------------------------------
# Active session display
# ---------------------------------------------------------------------------

if not current_session:
    st.markdown("---")
    st.info("Upload a contract file and click **Extract & Process** to begin.", icon="💡")
    st.stop()

# Auto-refresh while extraction/posting is in progress
auto_refresh_statuses = ("extracting", "processing")
if current_session.get("status") in auto_refresh_statuses:
    time.sleep(2)
    st.rerun()

st.markdown("---")

# Session overview banner
sess_status = current_session.get("status", "unknown")
badge_html, badge_color = STATUS_BADGE.get(sess_status, (f'<span class="badge">{sess_status}</span>', "#fff"))

st.markdown(
    f"""
<div style='background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 20px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.06);'>
  <div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;'>
    <div style='display:flex;align-items:center;gap:10px;'>
      <span style='font-size:22px;'>📂</span>
      <div>
        <span style='font-size:15px;font-weight:700;color:#111827;font-family:Inter,sans-serif;'>{current_session.get("filename","")}</span><br>
        <span style='font-size:11.5px;color:#9ca3af;font-family:Inter,sans-serif;'>Session ID: <code style="font-family:JetBrains Mono,monospace;color:#6b7280;">{current_session.get("session_id","")[:16]}…</code></span>
      </div>
    </div>
    <div>{badge_html}</div>
  </div>
  {"<div style='color:#b91c1c;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:8px 12px;margin-top:10px;font-size:13px;font-family:Inter,sans-serif;'>⚠️ " + current_session.get("extraction_error","") + "</div>" if current_session.get("extraction_error") else ""}
</div>
""",
    unsafe_allow_html=True,
)

# Pipeline visual
steps = current_session.get("steps", [])
pipeline_html = '<div class="pipeline-bar">'
for i, step in enumerate(steps):
    s = step.get("status", "pending")
    color = STATUS_BADGE.get(s, ("", "#8b949e"))[1]
    pipeline_html += f'<div class="pipeline-node"><span style="color:{color};">{step.get("icon","")}</span> <span style="color:{color};font-size:11px;">{step.get("name","")[:18]}</span></div>'
    if i < len(steps) - 1:
        pipeline_html += '<span class="pipeline-arrow">→</span>'
pipeline_html += "</div>"
st.markdown(pipeline_html, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Per-step cards
# ---------------------------------------------------------------------------

st.markdown("<h3 style='font-size:16px;font-weight:700;color:#1a202c;margin:4px 0 12px;font-family:Inter,sans-serif;'>🔄 Integration Steps</h3>", unsafe_allow_html=True)

for step in steps:
    step_id = step["id"]
    step_status = step.get("status", "pending")
    step_badge, _ = STATUS_BADGE.get(step_status, (f'<span class="badge">{step_status}</span>', "#fff"))

    with st.expander(
        f"{step.get('icon','')} **{step.get('name','')}** — {step_badge}",
        expanded=(step_status in ("awaiting_approval", "failed", "rejected")),
    ):
        # ── Failure summary — shown first so the user immediately sees what broke ──
        if step_status == "failed":
            d365_calls_all = step.get("d365_calls", [])
            failed_calls = [c for c in d365_calls_all if not c.get("success", False)]

            if not d365_calls_all:
                # Extraction-level failure — no calls were ever attempted
                st.markdown(
                    f"<div style='background:#fef2f2;border:1.5px solid #fca5a5;border-radius:10px;"
                    f"padding:14px 18px;margin-bottom:14px;'>"
                    f"<div style='font-size:14px;font-weight:700;color:#991b1b;margin-bottom:6px;'>❌ Step failed — no D365 calls were attempted</div>"
                    f"<div style='font-size:13px;color:#b91c1c;font-family:Inter,sans-serif;'>"
                    f"{step.get('error_message','Unknown error')}</div>"
                    f"<div style='font-size:12px;color:#6b7280;margin-top:8px;'>Re-run <strong>Extract &amp; Process</strong> to regenerate the payload, then Retry.</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            elif failed_calls:
                project_ops_blocked = any(
                    "Project Operations Integration" in (str(c.get("error") or ""))
                    or c.get("entity") == "ProjectParameters"
                    for c in failed_calls
                )

                if project_ops_blocked:
                    st.markdown(
                        "<div style='background:#fff7ed;border:1.5px solid #fdba74;border-radius:10px;"
                        "padding:14px 18px;margin-bottom:14px;'>"
                        "<div style='font-size:14px;font-weight:700;color:#9a3412;margin-bottom:6px;'>"
                        "⚙️ Prerequisite Missing — Project Operations Integration is disabled</div>"
                        "<div style='font-size:13px;color:#9a3412;font-family:Inter,sans-serif;'>"
                        "Enable <strong>Project Operations Integration</strong> for this legal entity in "
                        "<em>Project management and accounting → Setup → Project parameters</em>. "
                        "After enabling, retry <strong>Project Contract</strong>."
                        "</div>"
                        "</div>",
                        unsafe_allow_html=True,
                    )

                # Build failure breakdown table
                rows_html = ""
                for c in failed_calls:
                    entity = c.get("entity", "")
                    method = c.get("method", "")
                    code   = c.get("status_code", "—")
                    err    = c.get("error", "") or ""
                    path   = c.get("path", "")

                    # Human-readable remediation hints per situation
                    if method == "TOKEN" and entity == "Azure AD":
                        hint = (
                            "Azure AD token acquisition failed. Verify <strong>Tenant ID</strong>, "
                            "<strong>Client ID</strong> and <strong>Client Secret</strong> in "
                            "<em>⚙️ Override credentials</em>, then Retry."
                        )
                    elif code in (0, "0"):
                        hint = (
                            f"Network or timeout error reaching D365 — <em>{err or 'no detail'}</em>. "
                            "Check VPN/firewall connectivity to the D365 UAT environment. "
                            "The sandbox may be hibernated; wait 2–3 minutes and Retry."
                        )
                    elif method == "GET" and code in (404, "404") and entity == "LegalEntities":
                        hint = f"Company <strong>{step.get('extracted_payload',{}).get('legalEntity',{}).get('DataAreaId','?')}</strong> does not exist in D365. Create the legal entity first."
                    elif method == "GET" and code in (404, "404") and entity == "ProjectGroups":
                        _pg_id = step.get("extracted_payload", {}).get("projectGroup", {}).get("ProjectGroupId", "?")
                        hint = f"Project group <strong>{_pg_id}</strong> does not exist in company <strong>{step.get('extracted_payload',{}).get('legalEntity',{}).get('DataAreaId','?')}</strong>. Create it under <em>Project management &amp; accounting → Setup → Posting → Project groups</em>."
                    elif method == "GET" and entity == "ProjectContractHeaders" and "Complete Step 2 successfully before Step 3" in err:
                        hint = (
                            "Project contract is missing in D365 for this Project ID. "
                            "Complete <strong>Step 2: Project Contract</strong> successfully first, then retry Step 3."
                        )
                    elif code in (401, "401"):
                        hint = "Authentication failed — check Tenant ID, Client ID and Client Secret in <em>⚙️ Override credentials</em>."
                    elif code in (403, "403"):
                        hint = "Insufficient permissions — ensure the service account has <em>Project accountant</em> duty in D365."
                    elif code in (400, "400"):
                        if "Project Operations Integration" in err:
                            hint = (
                                "Enable <strong>Project Operations Integration</strong> for this legal entity in "
                                "<em>Project parameters</em>, then Retry."
                            )
                        else:
                            hint = f"Bad request on <strong>{entity}</strong> — the OData payload may contain an invalid field. Check Raw JSON tab."
                    elif code in (409, "409"):
                        hint = f"<strong>{entity}</strong> already exists (conflict). Safe to retry — 409 will be treated as success on next attempt."
                    elif err:
                        hint = err
                    else:
                        hint = f"HTTP {code} returned by D365. Check the Raw JSON tab for the full response."

                    rows_html += (
                        f"<tr>"
                        f"<td style='padding:7px 10px;border-bottom:1px solid #fee2e2;font-weight:600;color:#991b1b;white-space:nowrap;'>{entity}</td>"
                        f"<td style='padding:7px 10px;border-bottom:1px solid #fee2e2;font-family:JetBrains Mono,monospace;color:#6b7280;font-size:12px;'>{method} {path[:60]}{'…' if len(path)>60 else ''}</td>"
                        f"<td style='padding:7px 10px;border-bottom:1px solid #fee2e2;font-weight:700;color:#dc2626;white-space:nowrap;'>HTTP {code}</td>"
                        f"<td style='padding:7px 12px;border-bottom:1px solid #fee2e2;font-size:12.5px;color:#374151;'>{hint}</td>"
                        f"</tr>"
                    )

                st.markdown(
                    f"<div style='background:#fef2f2;border:1.5px solid #fca5a5;border-radius:10px;"
                    f"padding:14px 18px;margin-bottom:14px;'>"
                    f"<div style='font-size:14px;font-weight:700;color:#991b1b;margin-bottom:10px;'>"
                    f"❌ {len(failed_calls)} call(s) failed — fix the issue(s) below then Retry</div>"
                    f"<table style='width:100%;border-collapse:collapse;font-family:Inter,sans-serif;font-size:13px;'>"
                    f"<thead><tr style='background:#fee2e2;'>"
                    f"<th style='padding:6px 10px;text-align:left;color:#7f1d1d;font-size:11px;text-transform:uppercase;letter-spacing:.5px;'>Entity</th>"
                    f"<th style='padding:6px 10px;text-align:left;color:#7f1d1d;font-size:11px;text-transform:uppercase;letter-spacing:.5px;'>Call</th>"
                    f"<th style='padding:6px 10px;text-align:left;color:#7f1d1d;font-size:11px;text-transform:uppercase;letter-spacing:.5px;'>Code</th>"
                    f"<th style='padding:6px 10px;text-align:left;color:#7f1d1d;font-size:11px;text-transform:uppercase;letter-spacing:.5px;'>What to fix</th>"
                    f"</tr></thead><tbody>{rows_html}</tbody></table>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # ── Success summary — same level of detail as the failure table above ──
        elif step_status == "posted":
            all_calls = step.get("d365_calls", [])
            deferred = [c for c in all_calls if c.get("method") == "DEFER"]
            posted_count = len(all_calls) - len(deferred)

            rows_html = ""
            for c in all_calls:
                entity = c.get("entity", "")
                method = c.get("method", "")
                code = c.get("status_code", "—")
                path = c.get("path", "")
                outcome = _describe_call_outcome(c)
                is_deferred = method == "DEFER"
                row_color = "#92400e" if is_deferred else "#065f46"
                border_color = "#fde68a" if is_deferred else "#bbf7d0"
                code_color = "#b45309" if is_deferred else "#059669"
                rows_html += (
                    f"<tr>"
                    f"<td style='padding:7px 10px;border-bottom:1px solid {border_color};font-weight:600;color:{row_color};white-space:nowrap;'>{entity}</td>"
                    f"<td style='padding:7px 10px;border-bottom:1px solid {border_color};font-family:JetBrains Mono,monospace;color:#6b7280;font-size:12px;'>{method} {path[:60]}{'…' if len(path)>60 else ''}</td>"
                    f"<td style='padding:7px 10px;border-bottom:1px solid {border_color};font-weight:700;color:{code_color};white-space:nowrap;'>{'DEFERRED' if is_deferred else f'HTTP {code}'}</td>"
                    f"<td style='padding:7px 12px;border-bottom:1px solid {border_color};font-size:12.5px;color:#374151;'>{outcome}</td>"
                    f"</tr>"
                )

            summary_line = f"✅ {posted_count} call(s) completed successfully"
            if deferred:
                summary_line += f" · ⏸ {len(deferred)} deferred (see reasons below)"

            st.markdown(
                f"<div style='background:#ecfdf5;border:1.5px solid #86efac;border-radius:10px;"
                f"padding:14px 18px;margin-bottom:14px;'>"
                f"<div style='font-size:14px;font-weight:700;color:#065f46;margin-bottom:10px;'>{summary_line}</div>"
                f"<table style='width:100%;border-collapse:collapse;font-family:Inter,sans-serif;font-size:13px;'>"
                f"<thead><tr style='background:#d1fae5;'>"
                f"<th style='padding:6px 10px;text-align:left;color:#065f46;font-size:11px;text-transform:uppercase;letter-spacing:.5px;'>Entity</th>"
                f"<th style='padding:6px 10px;text-align:left;color:#065f46;font-size:11px;text-transform:uppercase;letter-spacing:.5px;'>Call</th>"
                f"<th style='padding:6px 10px;text-align:left;color:#065f46;font-size:11px;text-transform:uppercase;letter-spacing:.5px;'>Result</th>"
                f"<th style='padding:6px 10px;text-align:left;color:#065f46;font-size:11px;text-transform:uppercase;letter-spacing:.5px;'>Outcome</th>"
                f"</tr></thead><tbody>{rows_html}</tbody></table>"
                f"</div>",
                unsafe_allow_html=True,
            )


        desc_col, ent_col = st.columns([2, 1])
        with desc_col:
            st.markdown(f"*{step.get('description','')}*")
        with ent_col:
            entities = step.get("d365_entities", [])
            if entities:
                st.markdown("**D365 Entities:** " + ", ".join(f"`{e}`" for e in entities))

        if step.get("rejection_reason"):
            st.warning(f"**Rejected:** {step['rejection_reason']}")
        if step.get("approval_note"):
            st.success(f"**Approval note:** {step['approval_note']}")

        # Extracted payload viewer
        payload = step.get("extracted_payload")
        if payload:
            st.markdown("#### 📋 Extracted D365 REST/OData Payload")
            tabs = st.tabs(["📄 JSON Preview", "🔍 Raw JSON"])

            with tabs[0]:
                # Show key sections as formatted tables
                import pandas as pd
                _rendered = False
                for key, val in payload.items():
                    if key.startswith("_"):
                        continue
                    if isinstance(val, list) and val:
                        st.markdown(f"**{key}** ({len(val)} records)")
                        try:
                            df = pd.DataFrame(val)
                            st.dataframe(df, use_container_width=True, height=min(300, 40 + 35 * len(df)))
                            _rendered = True
                        except Exception:
                            st.json(val)
                    elif isinstance(val, dict):
                        st.markdown(f"**{key}**")
                        rows = [
                            {"Field": k, "Value": "" if v is None else str(v)}
                            for k, v in val.items()
                        ]
                        if rows:
                            df = pd.DataFrame(rows)
                            st.dataframe(
                                df, use_container_width=True, hide_index=True,
                                height=min(300, 40 + 35 * len(df)),
                            )
                        _rendered = True

            with tabs[1]:
                st.json(payload)

        # D365 call results
        d365_calls = step.get("d365_calls", [])
        if d365_calls:
            if step_id == "project_contract":
                contract_id_existing = ""
                contract_id_created = ""
                mode = ""
                for c in d365_calls:
                    if c.get("entity") == "ProjectParameters" and c.get("method") == "GET":
                        rb = c.get("response_body") or {}
                        mode = (rb.get("_mode") or "")
                    if c.get("method") == "GET" and c.get("entity") in ("ProjectContracts", "ProjectContractHeaders"):
                        rb = c.get("response_body") or {}
                        if rb.get("_action") == "skip_create":
                            contract_id_existing = rb.get("_matched_contract_id") or contract_id_existing
                    if c.get("method") == "POST" and c.get("entity") in ("ProjectContracts", "ProjectContractHeaders") and c.get("success"):
                        rb = c.get("response_body") or {}
                        contract_id_created = rb.get("ProjectContractID") or rb.get("ProjectContractId") or contract_id_created

                if contract_id_created:
                    st.markdown(
                        f"<div style='background:#ecfdf5;border:1.5px solid #86efac;border-radius:10px;padding:10px 14px;margin:8px 0 12px;'>"
                        f"<div style='font-size:13px;font-weight:700;color:#065f46;'>✅ Project Contract Created: <span style='font-family:JetBrains Mono,monospace;'>{contract_id_created}</span></div>"
                        f"<div style='font-size:12px;color:#065f46;margin-top:4px;'>Mode: {mode or 'unknown'}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                elif contract_id_existing:
                    st.markdown(
                        f"<div style='background:#eff6ff;border:1.5px solid #93c5fd;border-radius:10px;padding:10px 14px;margin:8px 0 12px;'>"
                        f"<div style='font-size:13px;font-weight:700;color:#1d4ed8;'>ℹ️ Existing Project Contract Reused: <span style='font-family:JetBrains Mono,monospace;'>{contract_id_existing}</span></div>"
                        f"<div style='font-size:12px;color:#1e3a8a;margin-top:4px;'>No duplicate created. Mode: {mode or 'unknown'}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            st.markdown("#### 📡 D365 OData Call Log")
            for call in d365_calls:
                ok = call.get("success", False)
                method = call.get("method", "")
                entity = call.get("entity", "")
                path = call.get("path", "")
                code = call.get("status_code", "—")
                error_msg = call.get("error")

                # colour-coded row per call type
                if ok and method == "GET":
                    icon = "🔍"
                    color = "#059669"
                elif ok and method in ("POST", "PATCH"):
                    icon = "✅"
                    color = "#2563eb"
                elif not ok and method == "GET":
                    icon = "⚠️"
                    color = "#d97706"
                else:
                    icon = "❌"
                    color = "#dc2626"

                st.markdown(
                    f"<div style='font-size:13px;font-family:JetBrains Mono,monospace;margin:3px 0;'>"
                    f"{icon} <span style='color:{color};font-weight:600;'>{method}</span> "
                    f"<span style='color:#374151;font-weight:600;'>{entity}</span> "
                    f"<span style='color:#6b7280;'>{path}</span> "
                    f"→ HTTP <span style='color:{color};font-weight:700;'>{code}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if error_msg:
                    st.markdown(
                        f"<div style='margin:2px 0 6px 22px;font-size:12px;color:#b91c1c;"
                        f"background:#fef2f2;border-left:3px solid #dc2626;padding:4px 10px;"
                        f"border-radius:4px;'>↳ {error_msg}</div>",
                        unsafe_allow_html=True,
                    )

        # Human approval actions
        if step_status == "awaiting_approval":
            st.markdown("---")
            st.markdown("#### 👤 Human Review Required")
            st.info("Review the extracted payload above, then **Approve** to post to D365 or **Reject** to skip this step.", icon="🔐")

            note_col, _ = st.columns([2, 1])
            with note_col:
                approval_note = st.text_input(
                    "Approval note (optional)",
                    key=f"note_{step_id}",
                    placeholder="e.g. Verified against signed contract v2.1",
                )

            btn_approve, btn_reject, btn_space = st.columns([1, 1, 2])
            with btn_approve:
                if st.button("✅ Approve & Post to D365", key=f"approve_{step_id}", type="primary", use_container_width=True):
                    with st.spinner(f"Posting {step['name']} to D365…"):
                        code2, resp2 = _api(
                            "post",
                            f"/api/sessions/{st.session_state['session_id']}/steps/{step_id}/approve",
                            json={"note": approval_note or None},
                        )
                    if code2 == 200:
                        st.success("Posted successfully!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Failed: {resp2}")

            with btn_reject:
                rejection_reason = st.text_input(
                    "Rejection reason",
                    key=f"reject_reason_{step_id}",
                    placeholder="Required to reject",
                )
                if st.button("🚫 Reject", key=f"reject_{step_id}", use_container_width=True):
                    if not rejection_reason:
                        st.warning("Please provide a rejection reason.")
                    else:
                        code2, resp2 = _api(
                            "post",
                            f"/api/sessions/{st.session_state['session_id']}/steps/{step_id}/reject",
                            json={"reason": rejection_reason},
                        )
                        if code2 == 200:
                            st.warning(f"Step rejected: {rejection_reason}")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"Failed: {resp2}")

        elif step_status in ("failed", "rejected"):
            st.markdown("---")
            if st.button(f"🔁 Retry Step", key=f"retry_{step_id}", use_container_width=False):
                code2, resp2 = _api("post", f"/api/sessions/{st.session_state['session_id']}/steps/{step_id}/retry")
                if code2 == 200:
                    st.rerun()

# ---------------------------------------------------------------------------
# Session-level actions
# ---------------------------------------------------------------------------

st.markdown("---")
action_col1, action_col2, action_col3 = st.columns([1, 1, 3])

with action_col1:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

with action_col2:
    if st.button("🗑️ Delete Session", use_container_width=True):
        if st.session_state["session_id"]:
            _api("delete", f"/api/sessions/{st.session_state['session_id']}")
            st.session_state["session_id"] = None
            st.rerun()

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown(
    """
<div style='text-align:center;color:#9ca3af;font-size:11.5px;margin-top:48px;padding:18px 0;border-top:2px solid #f1f5f9;font-family:Inter,sans-serif;'>
  <span style='color:#6b7280;font-weight:600;'>D365 Project Lifecycle Integration Agent</span>
  &nbsp;·&nbsp; IFRS 15 compliant
  &nbsp;·&nbsp; Human-in-the-loop approval for every ERP write
    &nbsp;·&nbsp; <a href="{BACKEND}/docs" target="_blank" style="color:#2563eb;font-weight:500;text-decoration:none;">API Docs ↗</a>
</div>
""",
    unsafe_allow_html=True,
)
