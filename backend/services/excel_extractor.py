"""Excel → D365 OData JSON extraction service.

Reads each sheet from the uploaded contract Excel workbook and maps it to
the seven REST/OData payload structures expected by D365 F&O.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(val: Any) -> Any:
    """Convert numpy / NaN values to plain Python types."""
    if val is None:
        return None
    if isinstance(val, float) and np.isnan(val):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, pd.Timestamp):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    return val


def _row_to_dict(row: pd.Series) -> dict:
    return {k: _clean(v) for k, v in row.items() if _clean(v) is not None}


def _find_sheet(xl: pd.ExcelFile, *keywords: str) -> str | None:
    """Return the first sheet name whose lower-case name contains any keyword."""
    for sheet in xl.sheet_names:
        lower = sheet.lower()
        for kw in keywords:
            if kw.lower() in lower:
                return sheet
    return None


def _read_sheet(xl: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    df = xl.parse(sheet)
    df.columns = [str(c).strip() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# Per-step extractors
# ---------------------------------------------------------------------------

def _extract_reference_data(xl: pd.ExcelFile) -> dict:
    # Contract Summary is the primary source; other sheet names are fallbacks
    sheet = _find_sheet(xl, "contract summary", "summary", "reference", "master", "prerequisite", "legal", "customer")

    meta = {
        "_meta": {
            "extractedOn": datetime.utcnow().strftime("%Y-%m-%d"),
            "accountingFramework": "IFRS 15",
            "payloadVersion": "1.0.0",
            "purpose": "Prerequisite master data that must exist in D365 F&O before the project contract is posted.",
        }
    }

    if sheet is None:
        sheet = xl.sheet_names[0]

    df = _read_sheet(xl, sheet)

    result = {**meta}

    # Named key column detection with fallback to first/second column
    key_col = next((c for c in df.columns if c.lower() in ("field", "key", "label", "parameter", "name")), None)
    val_col = next((c for c in df.columns if c.lower() in ("value", "data", "answer", "detail")), None)
    if key_col is None and len(df.columns) >= 2:
        key_col = df.columns[0]
    if val_col is None and len(df.columns) >= 2:
        val_col = df.columns[1]
    if key_col is None and len(df.columns) >= 2:
        key_col = df.columns[0]
    if val_col is None and len(df.columns) >= 2:
        val_col = df.columns[1]

    kv: dict = {}
    if key_col and val_col:
        for _, row in df.dropna(subset=[key_col]).iterrows():
            k = str(row[key_col]).strip()
            v = _clean(row[val_col])
            if k and v is not None and k.lower() != "nan":
                kv[k] = v

    def _get(*candidates: str) -> Any:
        for c in candidates:
            for k, v in kv.items():
                if c.lower() in k.lower():
                    return v
        return None

    summary_kv: dict[str, Any] = {}
    summary_sheet = _find_sheet(xl, "contract summary", "summary")
    if summary_sheet:
        sdf = _read_sheet(xl, summary_sheet)
        sk = next((c for c in sdf.columns if c.lower() in ("field", "key", "label", "parameter", "name")), None)
        sv = next((c for c in sdf.columns if c.lower() in ("value", "data", "answer", "detail")), None)
        if sk is None and len(sdf.columns) >= 2:
            sk = sdf.columns[0]
        if sv is None and len(sdf.columns) >= 2:
            sv = sdf.columns[1]
        if sk and sv:
            for _, row in sdf.dropna(subset=[sk]).iterrows():
                k = str(row[sk]).strip()
                v = _clean(row[sv])
                if k and v is not None and k.lower() != "nan":
                    summary_kv[k] = v

    def _summary_get(*candidates: str) -> Any:
        for c in candidates:
            for k, v in summary_kv.items():
                if c.lower() in k.lower():
                    return v
        return None

    # Contract Summary holds stable customer details in the current workbook format.
    summary_kv: dict[str, Any] = {}
    summary_sheet = _find_sheet(xl, "contract summary", "summary")
    if summary_sheet:
        sdf = _read_sheet(xl, summary_sheet)
        sk = next((c for c in sdf.columns if c.lower() in ("field", "key", "label", "parameter", "name")), None)
        sv = next((c for c in sdf.columns if c.lower() in ("value", "data", "answer", "detail")), None)
        if sk is None and len(sdf.columns) >= 2:
            sk = sdf.columns[0]
        if sv is None and len(sdf.columns) >= 2:
            sv = sdf.columns[1]
        if sk and sv:
            for _, row in sdf.dropna(subset=[sk]).iterrows():
                k = str(row[sk]).strip()
                v = _clean(row[sv])
                if k and v is not None and k.lower() != "nan":
                    summary_kv[k] = v

    def _summary_get(*candidates: str) -> Any:
        for c in candidates:
            for k, v in summary_kv.items():
                if c.lower() in k.lower():
                    return v
        return None

    data_area = _get("data area", "company", "legal entity id", "entity id") or "2020"
    org_name = _get("supplier", "g42 entity", "company name", "legal entity name", "entity name") or "Daypop Technology Projects LLC"
    # "Customer" row comes before "Customer address" — search exact label first, then fallback
    customer_name = _get("customer name", "client name", "customer") or "Customer Name"
    customer_address = _get("customer address", "address") or ""
    # Strip parenthetical aliases like "(also referred to as 'Presight')"
    if "(" in str(customer_name):
        customer_name = customer_name[:customer_name.index("(")].strip()

    # Read payment terms days from the dedicated Payment Terms sheet
    pt_days = 0
    pt_sheet = _find_sheet(xl, "payment terms")
    if pt_sheet:
        pt_df = _read_sheet(xl, pt_sheet)
        pt_key = pt_df.columns[0] if len(pt_df.columns) >= 1 else None
        pt_val = pt_df.columns[1] if len(pt_df.columns) >= 2 else None
        if pt_key and pt_val:
            for _, row in pt_df.dropna(subset=[pt_key]).iterrows():
                k = str(row[pt_key]).strip().lower()
                v = _clean(row[pt_val])
                if "credit period" in k or "payment days" in k or "days" in k:
                    try:
                        pt_days = int(float(str(v)))
                        break
                    except (ValueError, TypeError):
                        pass

    # Derive payment terms code from days (e.g. 60 → N060); fallback to N060
    payment_terms = f"N{pt_days:03d}" if pt_days > 0 else (_get("payment terms code", "terms code") or "N060")
    pt_description = f"Net {pt_days} days from invoice receipt" if pt_days > 0 else f"Payment terms {payment_terms}"

    # Currency read from Contract Summary sheet; falls back to AED
    currency = _get("currency", "contract currency", "ccy", "sales currency") or "AED"
    # SalesTaxGroup always defaults to AbuDhabi regardless of sheet content
    tax_group = "AbuDhabi"

    result["legalEntity"] = {
        "entity": "LegalEntities",
        "DataAreaId": data_area,
        "Name": org_name,
        "_verify": "Confirm the actual DataAreaId for the legal entity in this environment.",
    }
    result["customer"] = {
        "entity": "CustomersV3",
        "dataAreaId": data_area,
        # CustomerAccount omitted — D365 number sequence assigns it automatically
        "OrganizationName": customer_name,
        "CustomerGroupId": "L_NGVN",
        "SalesCurrencyCode": currency,
        "SalesTaxGroup": tax_group,
        # Address stored as metadata; must be created separately via a Step 2b
        "_address": customer_address,
        # Confirmed mandatory by live D365 probe: dataAreaId, CustomerGroupId,
        # OrganizationName, SalesCurrencyCode, SalesTaxGroup
    }
    result["paymentTerms"] = {
        "entity": "PaymentTerms",
        "dataAreaId": data_area,
        "Name": payment_terms,
        "Description": pt_description,
        "NumberOfDays": pt_days,
        "PaymentMethodType": "Net",
    }
    result["salesTax"] = {
        "entity": "TaxGroups",
        "dataAreaId": data_area,
        "TaxGroup": tax_group,
        "Description": "Standard VAT rate",
        "TaxRatePercent": 5.0,
    }
    result["projectGroup"] = {
        "entity": "ProjectGroups",
        "dataAreaId": data_area,
        "ProjectGroupId": "FP-WIP",
        "ProjectType": "FixedPrice",
        "RevenueRecognitionAccountingMethod": "CompletedPercentage",
        "MatchingPrincipleForRevenue": "SalesValue",
        "PostCostsToAccounts": "Balance",
    }
    # Attach any raw kv pairs as additional context
    if kv:
        result["_sourceFields"] = kv

    return result


def _extract_project_contract(xl: pd.ExcelFile) -> dict:
    sheet = _find_sheet(xl, "contract", "engagement letter", "agreement", "header")
    meta = {
        "_meta": {
            "extractedOn": datetime.utcnow().strftime("%Y-%m-%d"),
            "accountingFramework": "IFRS 15",
            "payloadVersion": "1.0.0",
            "purpose": "Project contract header, funding source and funding rule.",
        }
    }

    if sheet is None:
        sheet = xl.sheet_names[min(1, len(xl.sheet_names) - 1)]

    df = _read_sheet(xl, sheet)

    key_col = next((c for c in df.columns if c.lower() in ("field", "key", "label", "parameter", "name")), None)
    val_col = next((c for c in df.columns if c.lower() in ("value", "data", "answer", "detail")), None)

    kv: dict = {}
    if key_col and val_col:
        for _, row in df.dropna(subset=[key_col]).iterrows():
            k = str(row[key_col]).strip()
            v = _clean(row[val_col])
            if k and v is not None:
                kv[k] = v

    def _get(*candidates: str) -> Any:
        for c in candidates:
            for k, v in kv.items():
                if c.lower() in k.lower():
                    return v
        return None

    # Contract Summary usually carries the authoritative customer row.
    summary_kv: dict[str, Any] = {}
    summary_sheet = _find_sheet(xl, "contract summary", "summary")
    if summary_sheet:
        sdf = _read_sheet(xl, summary_sheet)
        sk = next((c for c in sdf.columns if c.lower() in ("field", "key", "label", "parameter", "name")), None)
        sv = next((c for c in sdf.columns if c.lower() in ("value", "data", "answer", "detail")), None)
        if sk is None and len(sdf.columns) >= 2:
            sk = sdf.columns[0]
        if sv is None and len(sdf.columns) >= 2:
            sv = sdf.columns[1]
        if sk and sv:
            for _, row in sdf.dropna(subset=[sk]).iterrows():
                k = str(row[sk]).strip()
                v = _clean(row[sv])
                if k and v is not None and k.lower() != "nan":
                    summary_kv[k] = v

    def _summary_get(*candidates: str) -> Any:
        for c in candidates:
            for k, v in summary_kv.items():
                if c.lower() in k.lower():
                    return v
        return None

    data_area = _get("data area", "company", "legal entity") or _summary_get("data area", "company", "legal entity") or "2020"
    # Leave blank when the source has no explicit contract ID so D365's number sequence assigns one on create.
    contract_id = _get("contract id", "contract number", "reference number") or ""
    customer_name = _get("customer name", "client name", "customer") or _summary_get("customer name", "client name", "customer") or ""
    customer = _get("customer account", "client account", "customer id") or ""
    if "(" in str(customer_name):
        customer_name = str(customer_name).split("(", 1)[0].strip()
    contract_title = (
        _get("contract title", "contract name", "project title", "engagement title")
        or _summary_get("contract title", "contract name", "project title", "engagement title")
        or ""
    )
    contract_name = contract_title or customer_name or "Project Contract"
    currency = _get("currency", "ccy") or "AED"
    start_date = _get("start date", "commencement", "from date") or "2023-01-01"
    end_date = _get("end date", "completion", "to date") or "2026-12-31"
    value_ex_tax_raw = _get("contract value excl", "value excluding", "amount excl", "contract value ex", "total value")
    value_ex_tax = float(value_ex_tax_raw) if value_ex_tax_raw is not None else 0.0
    tax_rate = 0.05
    tax_amount = round(value_ex_tax * tax_rate, 2)
    value_inc_tax = round(value_ex_tax + tax_amount, 2)

    payment_terms = _get("payment terms") or "N060"
    tax_group = _get("tax group", "vat group") or "AbuDhabi"

    fs_seed = customer or customer_name or "CUST"
    funding_source_id = f"FS-{re.sub(r'[^A-Z0-9]', '', str(fs_seed).upper())[:8]}"

    result = {
        **meta,
        "ProjectContractHeaders": [
            {
                "dataAreaId": data_area,
                "ProjectContractId": contract_id,
                "Name": contract_name,
                "CustomerAccount": customer,
                "_customer_name": customer_name,
                "FundingType": "Customer",
                "CurrencyCode": currency,
                "ContractStartDate": str(start_date),
                "ContractEndDate": str(end_date),
                "ContractValueExcludingTax": value_ex_tax,
                "ContractValueIncludingTax": value_inc_tax,
                "TaxAmount": tax_amount,
                "PaymentTerms": payment_terms,
                "SalesTaxGroup": tax_group,
                "Status": "Active",
            }
        ],
        "ProjectContractFundingSources": [
            {
                "dataAreaId": data_area,
                "ProjectContractId": contract_id,
                "FundingSourceId": funding_source_id,
                "FundingSourceType": "Customer",
                "CustomerAccount": customer,
                "_customer_name": customer_name,
                "CurrencyCode": currency,
                "FundingLimitAmount": value_ex_tax,
                "PaymentTerms": payment_terms,
                "SalesTaxGroup": tax_group,
            }
        ],
        "ProjectContractFundingRules": [
            {
                "dataAreaId": data_area,
                "ProjectContractId": contract_id,
                "FundingRuleId": "FR-001",
                "FundingSourceId": funding_source_id,
                "ProjectId": contract_id.replace("PC-", "PROJ-"),
                "IncludeSubProjects": True,
                "ContributionPercent": 100.0,
            }
        ],
    }
    if kv:
        result["_sourceFields"] = kv
    return result


def _extract_project_master(xl: pd.ExcelFile) -> dict:
    sheet = _find_sheet(xl, "project master", "project hierarchy", "projects")
    meta = {
        "_meta": {
            "extractedOn": datetime.utcnow().strftime("%Y-%m-%d"),
            "accountingFramework": "IFRS 15",
            "payloadVersion": "1.0.0",
            "purpose": "Project master hierarchy with parent project and sub-projects.",
        }
    }

    if sheet is None:
        sheet = xl.sheet_names[min(2, len(xl.sheet_names) - 1)]

    df = _read_sheet(xl, sheet)

    # Contract Summary contains stable customer identity for account resolution downstream.
    summary_kv: dict[str, Any] = {}
    summary_sheet = _find_sheet(xl, "contract summary", "summary")
    if summary_sheet:
        sdf = _read_sheet(xl, summary_sheet)
        sk = next((c for c in sdf.columns if c.lower() in ("field", "key", "label", "parameter", "name")), None)
        sv = next((c for c in sdf.columns if c.lower() in ("value", "data", "answer", "detail")), None)
        if sk is None and len(sdf.columns) >= 2:
            sk = sdf.columns[0]
        if sv is None and len(sdf.columns) >= 2:
            sv = sdf.columns[1]
        if sk and sv:
            for _, row in sdf.dropna(subset=[sk]).iterrows():
                k = str(row[sk]).strip()
                v = _clean(row[sv])
                if k and v is not None and k.lower() != "nan":
                    summary_kv[k] = v

    def _summary_get(*candidates: str) -> Any:
        for c in candidates:
            for k, v in summary_kv.items():
                if c.lower() in k.lower():
                    return v
        return None

    customer_name = _summary_get("customer name", "client name", "customer") or ""
    if "(" in str(customer_name):
        customer_name = str(customer_name).split("(", 1)[0].strip()
    contract_title = _summary_get("contract title", "contract name", "project title", "engagement title") or ""
    project_name = str(contract_title or "Parent Project").strip()

    # Try to find rows with project data
    projects_rows = []
    id_col = next((c for c in df.columns if "id" in c.lower() or "project" in c.lower()), None)

    if id_col:
        for _, row in df.dropna(subset=[id_col]).iterrows():
            d = _row_to_dict(row)
            if d:
                projects_rows.append(d)

    # Build minimal structure if no rows found. IDs are left blank — Step 3 assigns
    # them from D365's project number sequence, correlated via `_seq_key`.
    if not projects_rows:
        projects_rows = [
            {"ProjectID": "", "ProjectName": project_name, "ParentProjectId": None, "_seq_key": "0"},
            {"ProjectID": "", "ProjectName": project_name, "ParentProjectId": None, "_parent_seq_key": "0", "_seq_key": "1"},
        ]

    # Normalise rows into ProjectsV2 shape
    projects_v2 = []
    for idx, row in enumerate(projects_rows):
        seq_key = str(row.get("_seq_key", idx))
        explicit_id = row.get("ProjectID") or row.get("ProjectId") or row.get("project id", "")
        explicit_parent = row.get("ParentProjectId") or row.get("parent", None)
        proj = {
            "dataAreaId": row.get("dataAreaId") or row.get("DataAreaId") or "2020",
            # Left blank when not explicit in source; Step 3 assigns via number sequence.
            "ProjectID": explicit_id,
            "ProjectName": project_name or row.get("ProjectName") or row.get("project name", ""),
            "ProjectContractId": row.get("ProjectContractId") or row.get("contract id", ""),
            "ProjectGroupId": row.get("ProjectGroupId") or "FP-WIP",
            "ProjectType": row.get("ProjectType") or "FixedPrice",
            "ProjectStage": row.get("ProjectStage") or "InProcess",
            "CustomerAccount": row.get("CustomerAccount") or row.get("customer", ""),
            "_customer_name": customer_name,
            "CurrencyCode": row.get("CurrencyCode") or row.get("currency", "AED"),
            "ProjectStartDate": str(row.get("ProjectStartDate") or row.get("start date", "2023-01-01")),
            "ProjectSchedulingEndDate": str(row.get("ProjectSchedulingEndDate") or row.get("end date", "2026-12-31")),
            "ParentProjectId": explicit_parent,
            "LineProperty": "Chargeable",
            "_seq_key": seq_key,
        }
        if not explicit_parent and row.get("_parent_seq_key"):
            proj["_parent_seq_key"] = str(row.get("_parent_seq_key"))
        projects_v2.append(proj)

    hierarchy = {}
    for p in projects_v2:
        parent = p.get("ParentProjectId")
        if not parent:
            hierarchy[p["ProjectID"]] = []
    for p in projects_v2:
        parent = p.get("ParentProjectId")
        if parent and parent in hierarchy:
            hierarchy[parent].append(p["ProjectID"])

    return {**meta, "hierarchy": hierarchy, "ProjectsV2": projects_v2}


def _extract_ifrs15_obligations(xl: pd.ExcelFile) -> dict:
    sheet = _find_sheet(xl, "ifrs", "performance obligation", "pob", "contract line", "obligation")
    meta = {
        "_meta": {
            "extractedOn": datetime.utcnow().strftime("%Y-%m-%d"),
            "accountingFramework": "IFRS 15",
            "payloadVersion": "1.0.0",
            "purpose": "IFRS 15 performance obligations as project contract lines with SSP allocation.",
        }
    }

    if sheet is None:
        sheet = xl.sheet_names[min(3, len(xl.sheet_names) - 1)]

    df = _read_sheet(xl, sheet)
    
    # If first row is mostly empty/NaN and second row looks like headers, use row 1 as headers
    if len(df) > 1:
        first_row_empty = df.iloc[0].isna().sum() > len(df.columns) / 2
        if first_row_empty:
            # Use row 1 as headers and data from row 2 onwards
            df.columns = [str(v).strip() if v is not None else f"col_{i}" for i, v in enumerate(df.iloc[1])]
            df = df.iloc[2:].reset_index(drop=True)

    lines = []
    pob_rows = []

    # Extract contract ID from Contract Summary sheet for consistency
    contract_id_from_summary = ""
    summary_sheet = _find_sheet(xl, "contract summary", "summary")
    if summary_sheet:
        sdf = _read_sheet(xl, summary_sheet)
        sk = next((c for c in sdf.columns if c.lower() in ("field", "key", "label", "parameter", "name")), None)
        sv = next((c for c in sdf.columns if c.lower() in ("value", "data", "answer", "detail")), None)
        if sk is None and len(sdf.columns) >= 2:
            sk = sdf.columns[0]
        if sv is None and len(sdf.columns) >= 2:
            sv = sdf.columns[1]
        if sk and sv:
            for _, row in sdf.dropna(subset=[sk]).iterrows():
                k = str(row[sk]).strip().lower()
                if any(kw in k for kw in ("contract id", "contract number", "reference number")):
                    contract_id_from_summary = _clean(row[sv]) or ""
                    break

    # Try to detect rows with POB/obligation data
    desc_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("description", "obligation", "pob", "service", "solution"))), None)
    amount_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("amount", "value", "price", "allocated"))), None)
    rev_method_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("revenue recognition", "recognition method"))), None)
    progress_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("progress", "measurement", "satisfaction"))), None)

    if desc_col:
        # Skip empty rows and potential header rows by checking if first data row looks like a header
        data_rows = df.dropna(subset=[desc_col])
        line_number = 0
        
        for idx, (_, row) in enumerate(data_rows.iterrows()):
            d = _row_to_dict(row)
            desc_val = str(d.get(desc_col, "")).strip()
            amount = _clean(row.get(amount_col)) if amount_col else 0.0
            desc_norm = " ".join(desc_val.lower().split())
            if desc_norm in {"total", "grand total", "contract total", "transaction price", "total transaction price"}:
                continue
            
            # Skip rows that look like headers (e.g., "POB ID", "Milestone ID", "Description")
            header_keywords = ("id", "description", "name", "amount", "date", "field", "key", "column")
            is_header_row = any(kw in desc_val.lower() for kw in header_keywords) and isinstance(amount, (type(None), float)) and (amount is None or amount == 0.0)
            
            if is_header_row and idx == 0:
                # Skip the first row if it looks like a header
                continue
            
            line_number += 1
            
            # Extract or use defaults for optional fields
            contract_id = d.get("ProjectContractId") or d.get("contract id") or contract_id_from_summary or ""
            data_area = d.get("dataAreaId") or d.get("data area") or "2020"
            project_id = d.get("ProjectId") or d.get("project id") or f"PROJ-001-0{line_number}"
            revenue_method = d.get(rev_method_col) if rev_method_col else (d.get("RevenueRecognitionMethod") or "CompletedPercentage")
            progress_meas = d.get(progress_col) if progress_col else (d.get("ProgressMeasurement") or "OutputMilestoneValue")
            tax_group = d.get("SalesTaxGroup") or d.get("tax group") or "AbuDhabi"
            
            # Field names match the real ProjectContractLines (ProjProjectContractLineEntity)
            # schema in this tenant — ContractLineId is left blank for number-sequence assignment.
            lines.append({
                "dataAreaId": data_area,
                "ProjectContractId": contract_id,
                "ContractLineId": d.get("ContractLineId") or "",
                "ContractLineNumber": line_number,
                "LineProjectId": project_id,
                "ProjectId": project_id,
                "Description": desc_val,
                "LineType": "LumpSum",
                "BillingMethod": "FixedPriceMilestone",
                "LineAmountExcludingTax": float(amount) if amount else 0.0,
                "LineAmount": float(amount) if amount else 0.0,
                "SalesTaxGroup": tax_group,
                "SalesTaxGroupCode": tax_group,
                "CurrencyCode": d.get("CurrencyCode") or "AED",
                "RevenueRecognitionMethod": revenue_method,
                "ProgressMeasurement": progress_meas,
                "StartDate": str(d.get("StartDate") or d.get("start date", "2023-01-01")),
                "EndDate": str(d.get("EndDate") or d.get("end date", "2026-12-31")),
            })
            pob_rows.append({
                "pobId": d.get("pobId") or f"POB-{line_number}",
                "contractLineNumber": line_number,
                "projectId": project_id,
                "description": desc_val,
                "allocatedTransactionPrice": float(amount) if amount else 0.0,
                "satisfiedOverTime": True,
                "revenueRecognitionMethod": revenue_method,
                "measureOfProgress": progress_meas,
            })

    return {
        **meta,
        "ProjectContractLines": lines,
        "ifrs15PerformanceObligations": pob_rows,
    }


def _extract_milestone_billing(xl: pd.ExcelFile) -> dict:
    sheet = _find_sheet(xl, "milestone", "billing schedule", "payment schedule", "billing")
    meta = {
        "_meta": {
            "extractedOn": datetime.utcnow().strftime("%Y-%m-%d"),
            "accountingFramework": "IFRS 15",
            "payloadVersion": "1.0.0",
            "purpose": "7 contractual milestones — billing trigger and IFRS 15 revenue recognition trigger.",
        }
    }

    if sheet is None:
        sheet = xl.sheet_names[min(4, len(xl.sheet_names) - 1)]

    df = _read_sheet(xl, sheet)
    
    # If first row is mostly empty/NaN and second row looks like headers, use row 1 as headers
    if len(df) > 1:
        first_row_empty = df.iloc[0].isna().sum() > len(df.columns) / 2
        if first_row_empty:
            # Use row 1 as headers and data from row 2 onwards
            df.columns = [str(v).strip() if v is not None else f"col_{i}" for i, v in enumerate(df.iloc[1])]
            df = df.iloc[2:].reset_index(drop=True)

    lines = []
    # For milestone description, prioritize "name" columns over generic keywords
    desc_col = None
    for c in df.columns:
        lower_c = c.lower()
        if "name" in lower_c and "schedule" not in lower_c and "id" not in lower_c:
            desc_col = c
            break
    # If no name column, try other keywords
    if not desc_col:
        desc_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("description", "milestone", "package", "deliverable"))), None)
    
    amount_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("amount", "value", "invoice", "billing", "price", "%"))), None)
    date_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("date", "due", "billing date", "milestone date"))), None)
    milestone_id_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("milestone id", "milestoneid"))), None)
    billing_sched_id_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("billing schedule id", "scheduleid", "schedule id"))), None)
    linked_pob_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("linked pob", "performance obligation", "pob"))), None)

    # Extract contract ID from Contract Summary sheet for consistency
    contract_id = ""
    summary_sheet = _find_sheet(xl, "contract summary", "summary")
    if summary_sheet:
        sdf = _read_sheet(xl, summary_sheet)
        sk = next((c for c in sdf.columns if c.lower() in ("field", "key", "label", "parameter", "name")), None)
        sv = next((c for c in sdf.columns if c.lower() in ("value", "data", "answer", "detail")), None)
        if sk is None and len(sdf.columns) >= 2:
            sk = sdf.columns[0]
        if sv is None and len(sdf.columns) >= 2:
            sv = sdf.columns[1]
        if sk and sv:
            for _, row in sdf.dropna(subset=[sk]).iterrows():
                k = str(row[sk]).strip().lower()
                if any(kw in k for kw in ("contract id", "contract number", "reference number", "reference no")):
                    contract_id = _clean(row[sv]) or ""
                    break
    
    # Keep blank when no explicit contract ID is found; Step 2 assigns/validates it.
    
    # Try to extract billing_schedule_id from data, otherwise derive from contract
    billing_schedule_id = ""

    if desc_col:
        # Skip empty rows and potential header rows
        data_rows = df.dropna(subset=[desc_col])
        line_number = 0
        
        for idx, (_, row) in enumerate(data_rows.iterrows()):
            d = _row_to_dict(row)
            desc_val = str(d.get(desc_col, "")).strip()
            amount = float(_clean(row.get(amount_col)) or 0.0) if amount_col else 0.0
            due_date = str(_clean(row.get(date_col)) or "") if date_col else ""
            data_area = d.get("dataAreaId") or d.get("data area") or "2020"
            
            # Skip rows that look like headers (e.g., "Milestone ID", "Description", "Amount")
            header_keywords = ("id", "name", "amount", "date", "description", "field", "key", "column")
            is_header_row = any(kw in desc_val.lower() for kw in header_keywords) and (amount == 0.0 or amount is None)
            
            if is_header_row and idx == 0:
                # Skip the first row if it looks like a header
                continue
            
            line_number += 1
            
            # Extract or derive milestone ID
            if milestone_id_col:
                milestone_id = str(d.get(milestone_id_col, f"M{line_number - 1}")).strip()
            else:
                milestone_id = d.get("MilestoneId") or f"M{line_number - 1}"
            
            # Extract or derive billing schedule ID (use first-row value or derive)
            if billing_sched_id_col and line_number == 1:
                billing_schedule_id = str(d.get(billing_sched_id_col, f"BS-{contract_id}")).strip()
            elif line_number == 1:
                billing_schedule_id = d.get("BillingScheduleId") or f"BS-{contract_id}"
            
            tax_rate = 0.05
            tax_amount = round(amount * tax_rate, 2)
            # Prefer source ProjectId; otherwise derive from contract ID, then fallback.
            project_id = d.get("ProjectId") or (contract_id.replace("PC-", "PROJ-") if contract_id else "PROJ-001")
            
            # ProjOnaccounttrans entity — on-account transaction header
            trans_dict = {
                "dataAreaId": data_area,
                "ProjectId": project_id,
                "ProjectContractId": contract_id,
                "TransactionDate": due_date,
                "BillingDate": due_date,
                "Description": desc_val,
                "Amount": amount,
                "TaxAmount": tax_amount,
                "AmountIncludingTax": round(amount + tax_amount, 2),
                "CurrencyCode": d.get("CurrencyCode") or "AED",
                "TransactionType": "OnAccount",
                "MilestoneId": milestone_id,
                "MilestoneDescription": desc_val,
            }
            if amount_col:
                trans_dict["_amount_source_column"] = str(amount_col)
                trans_dict["_amount_is_pob_percent"] = "%" in str(amount_col) or "percent" in str(amount_col).lower()
            if linked_pob_col:
                linked_raw = str(d.get(linked_pob_col) or "").strip()
                if linked_raw:
                    linked_pobs = re.findall(r"POB[-\s]*(\d+)", linked_raw, flags=re.I)
                    trans_dict["_linked_pobs"] = [f"POB-{n}" for n in linked_pobs] or [linked_raw]
            lines.append(trans_dict)

    return {
        **meta,
        "ProjOnaccounttrans": lines,
    }


def _extract_invoice_schedule(xl: pd.ExcelFile) -> dict:
    sheet = _find_sheet(xl, "invoicing", "invoice", "invoice schedule", "billing proposal")
    meta = {
        "_meta": {
            "extractedOn": datetime.utcnow().strftime("%Y-%m-%d"),
            "accountingFramework": "IFRS 15",
            "payloadVersion": "1.0.0",
            "purpose": "Milestone on-account invoicing — one invoice proposal per milestone on acceptance.",
        }
    }

    if sheet is None:
        sheet = xl.sheet_names[min(5, len(xl.sheet_names) - 1)]

    df = _read_sheet(xl, sheet)
    has_invoice_table_header = any("invoice date" in str(c).lower() for c in df.columns) and any(
        "trigger" in str(c).lower() or "milestone" in str(c).lower() for c in df.columns
    )
    if not has_invoice_table_header:
        raw_df = xl.parse(sheet, header=None)
        header_idx = None
        for idx, row in raw_df.iterrows():
            values = [str(v).strip().lower() for v in row.tolist() if _clean(v) is not None]
            joined = " | ".join(values)
            if "inv. no" in joined and "invoice date" in joined:
                header_idx = idx
                break
        if header_idx is not None:
            headers_from_row = [
                str(v).strip() if _clean(v) is not None else f"col_{i}"
                for i, v in enumerate(raw_df.iloc[header_idx].tolist())
            ]
            df = raw_df.iloc[header_idx + 1:].reset_index(drop=True)
            df.columns = headers_from_row

    headers = []
    lines = []
    desc_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("trigger", "milestone", "description"))), None)
    amount_col = next((c for c in df.columns if "amount" in c.lower() and "excl" in c.lower()), None)
    if amount_col is None:
        amount_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("amount", "value", "total"))), None)
    date_col = next((c for c in df.columns if "invoice date" in c.lower()), None)
    if date_col is None:
        date_col = next((c for c in df.columns if "date" in c.lower()), None)
    invoice_no_col = next((c for c in df.columns if "inv" in c.lower() and "no" in c.lower()), None)
    linked_pob_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("linked pob", "performance obligation", "pob"))), None)
    status_col = next((c for c in df.columns if "status" in c.lower()), None)
    payment_terms_col = next((c for c in df.columns if "payment" in c.lower() and "term" in c.lower()), None)
    currency_col = next((c for c in df.columns if "currency" in c.lower()), None)

    # Extract contract ID from Contract Summary sheet for consistency
    contract_id = ""
    summary_sheet = _find_sheet(xl, "contract summary", "summary")
    if summary_sheet:
        sdf = _read_sheet(xl, summary_sheet)
        sk = next((c for c in sdf.columns if c.lower() in ("field", "key", "label", "parameter", "name")), None)
        sv = next((c for c in sdf.columns if c.lower() in ("value", "data", "answer", "detail")), None)
        if sk is None and len(sdf.columns) >= 2:
            sk = sdf.columns[0]
        if sv is None and len(sdf.columns) >= 2:
            sv = sdf.columns[1]
        if sk and sv:
            for _, row in sdf.dropna(subset=[sk]).iterrows():
                k = str(row[sk]).strip().lower()
                if any(kw in k for kw in ("contract id", "contract number", "reference number")):
                    contract_id = _clean(row[sv]) or ""
                    break
    
    # Keep blank when no explicit contract ID is found; Step 2 assigns/validates it.

    if desc_col:
        line_number = 0
        for idx, (_, row) in enumerate(df.dropna(subset=[desc_col]).iterrows()):
            d = _row_to_dict(row)
            desc_val = str(d.get(desc_col, "")).strip()
            amount = float(_clean(row.get(amount_col)) or 0.0) if amount_col else 0.0
            inv_date = str(_clean(row.get(date_col)) or "") if date_col else ""
            data_area = d.get("dataAreaId") or d.get("data area") or "2020"
            desc_norm = desc_val.lower()
            if not desc_val or desc_norm in {"total", "grand total"} or "tcv check" in desc_norm or "invoicing total" in desc_norm:
                continue
            
            # Skip rows that look like headers (e.g., "Inv. No.", "Invoice No", "Amount", "Date")
            header_keywords = ("no.", "no", "amount", "date", "invoice", "field", "key", "column")
            is_header_row = any(kw in desc_val.lower() for kw in header_keywords) and (amount == 0.0 or amount is None)
            
            if is_header_row and idx == 0:
                # Skip the first row if it looks like a header
                continue
            
            line_number += 1
            invoice_no = str(d.get(invoice_no_col) or f"INV-{line_number:03d}").strip() if invoice_no_col else f"INV-{line_number:03d}"
            linked_pob = str(d.get(linked_pob_col) or "").strip() if linked_pob_col else ""
            proposal_id = f"PIP-{invoice_no}"
            headers.append({
                "dataAreaId": data_area,
                "ProposalId": proposal_id,
                "ProjectContractId": contract_id,
                "ProjectId": d.get("ProjectId") or f"PROJ-001",
                "InvoiceAccount": d.get("InvoiceAccount") or "C-CUST-001",
                "InvoiceDate": inv_date,
                "CurrencyCode": d.get(currency_col) if currency_col else (d.get("CurrencyCode") or "AED"),
                "PaymentTerms": d.get(payment_terms_col) if payment_terms_col else (d.get("PaymentTerms") or "N060"),
                "CustomerReference": invoice_no,
                "Description": desc_val,
                "PostingStatus": d.get(status_col) if status_col else (d.get("PostingStatus") or "NotCreated"),
                "LinkedPOB": linked_pob,
            })
            tax_amount = round(amount * 0.05, 2)
            lines.append({
                "dataAreaId": data_area,
                "ProposalId": proposal_id,
                "LineNumber": 1,
                "ProjectId": d.get("ProjectId") or f"PROJ-001",
                "Description": desc_val,
                "AmountExcludingTax": amount,
                "TaxAmount": tax_amount,
                "AmountIncludingTax": round(amount + tax_amount, 2),
                "CurrencyCode": d.get(currency_col) if currency_col else (d.get("CurrencyCode") or "AED"),
                "SalesTaxGroup": d.get("SalesTaxGroup") or "AbuDhabi",
                "LinkedPOB": linked_pob,
            })

    return {
        **meta,
        "ProjectInvoiceProposalHeaders": headers,
        "ProjectInvoiceProposalOnAccountLines": lines,
    }


def _extract_revenue_recognition(xl: pd.ExcelFile) -> dict:
    sheet = _find_sheet(xl, "revenue recognition", "revenue", "period", "estimate", "recognition")
    meta = {
        "_meta": {
            "extractedOn": datetime.utcnow().strftime("%Y-%m-%d"),
            "accountingFramework": "IFRS 15",
            "payloadVersion": "1.0.0",
            "purpose": "Month-end revenue recognition schedule driving the fixed-price percentage-of-completion estimate process.",
        }
    }

    if sheet is None:
        sheet = xl.sheet_names[min(6, len(xl.sheet_names) - 1)]

    df = _read_sheet(xl, sheet)

    schedule = []
    period_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("period", "month", "fiscal"))), None)
    rev_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("revenue", "amount", "recognised"))), None)
    pct_col = next((c for c in df.columns if any(kw in c.lower() for kw in ("percent", "%", "complete", "completion"))), None)

    if period_col:
        for _, row in df.dropna(subset=[period_col]).iterrows():
            d = _row_to_dict(row)
            period = str(d.get(period_col, ""))
            revenue = float(_clean(row.get(rev_col)) or 0.0) if rev_col else 0.0
            pct = float(_clean(row.get(pct_col)) or 0.0) if pct_col else 0.0
            schedule.append({
                "fiscalPeriod": period,
                "revenueRecognisedTotal": revenue,
                "percentCompleteTotal": pct,
                "postingRequired": revenue != 0.0,
            })

    return {
        **meta,
        "method": {
            "revenueRecognitionMethod": "CompletedPercentage",
            "ifrs15MeasureOfProgress": "OUTPUT method - accepted milestone value",
            "currency": "AED",
        },
        "ProjectEstimateProjects": [
            {
                "dataAreaId": "2020",
                "ProjectId": "PROJ-001-01",
                "EstimateProjectId": "EST-PROJ-001-01",
                "CostTemplateId": "CT-FP-MILESTONE",
                "PeriodFrequency": "Monthly",
                "CompletionMethod": "ManualCompletionPercentage",
            }
        ],
        "revenueRecognitionSchedule": schedule,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

EXTRACTORS = [
    ("reference_data", _extract_reference_data),
    ("project_contract", _extract_project_contract),
    ("project_master", _extract_project_master),
    ("ifrs15_obligations", _extract_ifrs15_obligations),
    ("milestone_billing", _extract_milestone_billing),
    ("invoice_schedule", _extract_invoice_schedule),
    ("revenue_recognition", _extract_revenue_recognition),
]


def extract_all(file_path: str) -> dict[str, dict]:
    """Extract all 7 payloads from the uploaded Excel workbook.

    Returns a mapping of step_id → extracted payload dict.
    Raises on file I/O errors; per-step exceptions are caught and stored
    under the key ``_extraction_error`` so the caller can surface them
    without aborting the whole pipeline.
    """
    xl = pd.ExcelFile(file_path, engine="openpyxl")
    results: dict[str, dict] = {}
    for step_id, extractor in EXTRACTORS:
        try:
            results[step_id] = extractor(xl)
        except Exception as exc:  # noqa: BLE001
            results[step_id] = {
                "_extraction_error": str(exc),
                "_meta": {"extractedOn": datetime.utcnow().strftime("%Y-%m-%d"), "step": step_id},
            }
    return results
