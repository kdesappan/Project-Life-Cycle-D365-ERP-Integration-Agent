"""D365 write agent — executes OData calls for a single process step.

Each step maps extracted JSON payload entities to one or more
GET (existence check) + POST (create if absent) sequences, following the
call_sequence.yaml logic.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from backend.models.schemas import D365CallResult, ProcessStep, StepStatus
from backend.services.d365_client import D365Client


def _now() -> datetime:
    return datetime.utcnow()


def _to_odata_datetime(value: Any) -> str:
    """Normalize extracted date-ish values to OData DateTimeOffset text."""
    raw = str(value or "").strip()
    if not raw:
        return datetime.utcnow().strftime("%Y-%m-%dT00:00:00Z")

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%B %Y", "%b %Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            continue

    # Already an ISO-like value.
    if "T" in raw:
        return raw if raw.endswith("Z") else f"{raw}Z"

    return datetime.utcnow().strftime("%Y-%m-%dT00:00:00Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _d365_error_text(body: dict | None) -> str:
    if not isinstance(body, dict):
        return ""
    err = body.get("error") or {}
    inner = err.get("innererror") if isinstance(err, dict) else {}
    parts = []
    if isinstance(err, dict) and err.get("message"):
        parts.append(str(err.get("message")))
    if isinstance(inner, dict) and inner.get("message"):
        parts.append(str(inner.get("message")))
    if body.get("Message"):
        parts.append(str(body.get("Message")))
    if body.get("raw"):
        parts.append(str(body.get("raw")))
    return " | ".join(parts)


def _odata_quote(value: Any) -> str:
    return str(value or "").replace("'", "''")


def _next_available_id(
    client: D365Client,
    entity: str,
    id_field: str,
    da: str,
    candidate_for: "callable[[int], str]",
    max_tries: int = 1000,
) -> str:
    """Find the first unused ID by probing with `eq` (the only filter operator this
    tenant's OData endpoint supports on these string key fields — `startswith`/`ge`
    raise "not Queryable" errors), starting at 1 and incrementing until a gap is found."""
    num = 1
    while num <= max_tries:
        candidate = candidate_for(num)
        path = f"/{entity}?$filter=dataAreaId eq '{da}' and {id_field} eq '{candidate}'&$top=1"
        status, body = client.get(path)
        exists = status == 200 and bool((body or {}).get("value"))
        if not exists:
            return candidate
        num += 1
    raise RuntimeError(f"Could not find an available ID for {entity} after {max_tries} tries.")


def _split_customer_address(raw_address: str) -> dict[str, str]:
    parts = [p.strip() for p in str(raw_address or "").split(",") if p and p.strip()]
    street = parts[0] if parts else ""
    if len(parts) >= 3:
        street = ", ".join(parts[:-2])
    city = ""
    for p in parts:
        if "abu dhabi" in p.lower():
            city = p
            break
    if not city and len(parts) >= 2:
        city = parts[-2]

    country_text = parts[-1] if parts else ""
    country_lower = country_text.lower()
    country_region_id = ""
    if "united arab emirates" in country_lower or country_lower == "uae":
        country_region_id = "ARE"

    return {
        "street": street,
        "city": city,
        "state": city,
        "country_region_id": country_region_id,
        "country_region_iso_code": "AE" if country_region_id == "ARE" else "",
        "postal_code": "",
        "full": str(raw_address or "").strip(),
    }


def _discover_address_entity_sets(client: D365Client) -> list[dict[str, Any]]:
    status, body = client.get("/$metadata")
    if status != 200:
        return []
    xml = (body or {}).get("raw", "")
    if not xml:
        return []

    entity_sets: list[tuple[str, str]] = re.findall(
        r'EntitySet Name="([^"]+)" EntityType="Microsoft\.Dynamics\.DataEntities\.([^"]+)"',
        xml,
    )
    candidates: list[dict[str, Any]] = []
    for set_name, type_name in entity_sets:
        key = f"{set_name} {type_name}".lower()
        if "postal" not in key and "address" not in key:
            continue
        if "customer" not in key and "party" not in key:
            continue

        type_match = re.search(
            rf'EntityType Name="{re.escape(type_name)}">(.*?)</EntityType>',
            xml,
            flags=re.S,
        )
        props = re.findall(r'Property Name="([^"]+)"', type_match.group(1)) if type_match else []
        candidates.append({"entity_set": set_name, "entity_type": type_name, "props": props})

    # Prefer explicit customer postal address V2 first, then other customer postal entities.
    pref = {
        "customerpostaladdressesv2": 0,
        "customerpostaladdresses": 1,
        "customerpostaladdress": 2,
    }
    candidates.sort(key=lambda c: (pref.get(c["entity_set"].lower(), 9), c["entity_set"].lower()))
    return candidates


def _build_address_payload(props: list[str], da: str, customer_account: str, parsed: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    prop_set = set(props)

    if "dataAreaId" in prop_set:
        payload["dataAreaId"] = da
    if "CustomerLegalEntityId" in prop_set:
        payload["CustomerLegalEntityId"] = da
    if "LegalEntity" in prop_set:
        payload["LegalEntity"] = da
    if "Company" in prop_set:
        payload["Company"] = da

    if "CustomerAccountNumber" in prop_set:
        payload["CustomerAccountNumber"] = customer_account
    elif "CustomerAccount" in prop_set:
        payload["CustomerAccount"] = customer_account
    elif "AccountNum" in prop_set:
        payload["AccountNum"] = customer_account

    if "AddressDescription" in prop_set:
        payload["AddressDescription"] = parsed["full"]
    if "Description" in prop_set:
        payload["Description"] = parsed["full"]
    if "Address" in prop_set:
        payload["Address"] = parsed["full"]
    if "Street" in prop_set:
        payload["Street"] = parsed["street"] or parsed["full"]
    if "AddressStreet" in prop_set:
        payload["AddressStreet"] = parsed["street"] or parsed["full"]
    if "City" in prop_set:
        payload["City"] = parsed["city"]
    if "AddressCity" in prop_set:
        payload["AddressCity"] = parsed["city"]
    if "State" in prop_set:
        payload["State"] = parsed["state"]
    if "AddressState" in prop_set:
        payload["AddressState"] = parsed["state"]
    if "County" in prop_set:
        payload["County"] = parsed["state"]
    if "AddressCounty" in prop_set:
        payload["AddressCounty"] = parsed["state"]

    if "CountryRegionId" in prop_set and parsed["country_region_id"]:
        payload["CountryRegionId"] = parsed["country_region_id"]
    if "AddressCountryRegionId" in prop_set and parsed["country_region_id"]:
        payload["AddressCountryRegionId"] = parsed["country_region_id"]
    if "CountryRegionISOCode" in prop_set and parsed["country_region_iso_code"]:
        payload["CountryRegionISOCode"] = parsed["country_region_iso_code"]
    if "AddressCountryRegionISOCode" in prop_set and parsed["country_region_iso_code"]:
        payload["AddressCountryRegionISOCode"] = parsed["country_region_iso_code"]
    if "ZipCode" in prop_set and parsed["postal_code"]:
        payload["ZipCode"] = parsed["postal_code"]
    if "PostalCode" in prop_set and parsed["postal_code"]:
        payload["PostalCode"] = parsed["postal_code"]
    if "AddressZipCode" in prop_set and parsed["postal_code"]:
        payload["AddressZipCode"] = parsed["postal_code"]

    if "IsPrimary" in prop_set:
        payload["IsPrimary"] = "Yes"
    if "IsRoleDelivery" in prop_set:
        payload["IsRoleDelivery"] = "Yes"
    if "IsPostalAddress" in prop_set:
        payload["IsPostalAddress"] = "Yes"

    # Ensure we only attempt posts that include an account + address value.
    has_account = any(k in payload for k in ("CustomerAccountNumber", "CustomerAccount", "AccountNum"))
    has_address = any(k in payload for k in ("Street", "AddressDescription"))
    if not (has_account and has_address):
        return {}
    return payload


def _norm_addr(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[,\n\r]+", " ", text)
    return text.strip()


def _address_match_score(existing_row: dict[str, Any], parsed: dict[str, str]) -> int:
    full_candidates = [
        existing_row.get("AddressDescription"),
        existing_row.get("Description"),
        existing_row.get("Address"),
    ]
    street_candidates = [
        existing_row.get("Street"),
        existing_row.get("AddressStreet"),
    ]
    city_candidates = [
        existing_row.get("City"),
        existing_row.get("AddressCity"),
    ]
    country_candidates = [
        existing_row.get("CountryRegionId"),
        existing_row.get("AddressCountryRegionId"),
        existing_row.get("CountryRegionISOCode"),
        existing_row.get("AddressCountryRegionISOCode"),
    ]

    full = _norm_addr(parsed.get("full"))
    street = _norm_addr(parsed.get("street") or parsed.get("full"))
    city = _norm_addr(parsed.get("city"))
    country = _norm_addr(parsed.get("country_region_id") or parsed.get("country_region_iso_code"))

    score = 0
    if full and any(_norm_addr(v) == full for v in full_candidates):
        score += 2
    if street and any(_norm_addr(v) == street for v in street_candidates):
        score += 1
    if city and any(_norm_addr(v) == city for v in city_candidates):
        score += 1
    if country and any(_norm_addr(v) == country for v in country_candidates):
        score += 1
    return score


def _find_existing_customer_address(
    client: D365Client,
    entity_set: str,
    props: list[str],
    da: str,
    customer_account: str,
    parsed: dict[str, str],
) -> tuple[int, dict, dict | None]:
    account_field = ""
    if "CustomerAccountNumber" in props:
        account_field = "CustomerAccountNumber"
    elif "CustomerAccount" in props:
        account_field = "CustomerAccount"
    elif "AccountNum" in props:
        account_field = "AccountNum"

    if not account_field:
        return 0, {}, None

    # Try narrow filter first; if unsupported, fall back to broader query.
    filter_expr = f"{account_field} eq '{customer_account}'"
    if "dataAreaId" in props:
        filter_expr = f"dataAreaId eq '{da}' and {filter_expr}"

    status, body = client.get(f"/{entity_set}?$filter={filter_expr}&$top=50")
    if status != 200 or not isinstance(body, dict):
        status, body = client.get(f"/{entity_set}?$top=100")
        if status != 200 or not isinstance(body, dict):
            return status, body if isinstance(body, dict) else {}, None

    values = body.get("value") or []
    if not isinstance(values, list):
        return status, body, None

    # Filter in-memory for account/legal entity when we used broad query.
    rows: list[dict[str, Any]] = []
    for row in values:
        if not isinstance(row, dict):
            continue
        row_acc = str(row.get(account_field) or "")
        if row_acc != customer_account:
            continue
        if "dataAreaId" in props and str(row.get("dataAreaId") or "") not in ("", da):
            continue
        rows.append(row)

    if not rows:
        return status, body, None

    best = max(rows, key=lambda r: _address_match_score(r, parsed))
    if _address_match_score(best, parsed) >= 2:
        return status, body, best
    return status, body, None


def _create_customer_address_calls(client: D365Client, da: str, customer_account: str, raw_address: str) -> list[D365CallResult]:
    if not customer_account or not str(raw_address or "").strip():
        return []

    parsed = _split_customer_address(raw_address)
    candidates = _discover_address_entity_sets(client)
    if not candidates:
        return [
            D365CallResult(
                entity="CustomerPostalAddress",
                method="POST",
                path="/$metadata",
                status_code=404,
                success=False,
                response_body={},
                error="Could not discover any customer postal address entity set from D365 metadata.",
                executed_at=_now(),
            )
        ]

    attempts: list[dict[str, Any]] = []
    for candidate in candidates:
        entity_set = candidate["entity_set"]
        props = candidate["props"]
        payload = _build_address_payload(props, da, customer_account, parsed)
        if not payload:
            continue

        # Idempotency guard: if same customer already has same address, skip create.
        get_status, get_body, matched = _find_existing_customer_address(
            client, entity_set, props, da, customer_account, parsed
        )
        if matched is not None:
            return [D365CallResult(
                entity=entity_set,
                method="GET",
                path=f"/{entity_set}",
                status_code=get_status,
                success=True,
                response_body={
                    "_action": "skipped_create_address_exists",
                    "matched_address": matched,
                    "request_payload": payload,
                },
                error=None,
                executed_at=_now(),
            )]

        status, body = client.post(f"/{entity_set}", payload)
        success = status in (200, 201, 204, 409)
        attempts.append({
            "entity_set": entity_set,
            "status_code": status,
            "request_payload": payload,
            "response": body,
        })
        if success:
            return [D365CallResult(
                entity=entity_set,
                method="POST",
                path=f"/{entity_set}",
                status_code=status,
                success=True,
                response_body={"request_payload": payload, "response": body, "attempts": attempts},
                error=None,
                executed_at=_now(),
            )]

    return [D365CallResult(
        entity="CustomerPostalAddress",
        method="POST",
        path="/CustomerPostalAddress*",
        status_code=400,
        success=False,
        response_body={"attempts": attempts},
        error="All discovered customer postal address entity attempts failed.",
        executed_at=_now(),
    )]


# ---------------------------------------------------------------------------
# Entity call plans
# ---------------------------------------------------------------------------

def _plan_reference_data(payload: dict, client: D365Client) -> list[D365CallResult]:
    calls: list[D365CallResult] = []
    da = payload.get("legalEntity", {}).get("DataAreaId", "2020")

    # ── Step 1: Legal entity existence check (GET only — never POST; must exist in D365) ──
    le_status, le_body = client.get(f"/LegalEntities?$filter=LegalEntityId eq '{da}'")
    le_found = le_status == 200 and bool((le_body or {}).get("value"))
    le_network_err = le_status == 0
    le_error = (le_body or {}).get("error") if le_network_err else (None if le_found else f"Legal entity '{da}' not found — create it in D365 before proceeding")
    calls.append(D365CallResult(
        entity="LegalEntities",
        method="GET",
        path=f"/LegalEntities?$filter=LegalEntityId eq '{da}'",
        status_code=le_status,
        success=le_found,
        response_body=le_body,
        error=le_error,
        executed_at=_now(),
    ))

    # ── Step 2: Customer — verify by name + group; create only if neither matches ──
    customer = payload.get("customer", {})
    org_name = customer.get("OrganizationName", "")
    customer_address = str(customer.get("_address", "")).strip()
    grp_id = "L_NGVN"
    resolved_customer_account = ""
    if org_name:
        encoded = org_name.replace("'", "''")
        # Filter by both OrganizationName and CustomerGroupId
        path = (
            f"/CustomersV3?$filter=dataAreaId eq '{da}'"
            f" and OrganizationName eq '{encoded}'"
            f" and CustomerGroupId eq '{grp_id}'&$top=1"
        )
        status, body = client.get(path)
        exists = status == 200 and bool((body or {}).get("value"))
        existing_account = (body or {}).get("value", [{}])[0].get("CustomerAccount", "") if exists else ""
        calls.append(D365CallResult(
            entity="CustomersV3", method="GET",
            path=path,
            status_code=status,
            success=status in (200, 404),
            response_body=body,
            error=None if status in (200, 404) else f"Unexpected HTTP {status} checking customer",
            executed_at=_now(),
        ))
        if exists:
            resolved_customer_account = existing_account
            # Surface the matched account number so it can be used downstream
            calls[-1].response_body = {
                **((body or {})),
                "_matched_account": existing_account,
                "_action": "skipped_create — customer already exists",
            }
        else:
            post_body = {
                "dataAreaId": da,
                "OrganizationName": org_name,
                "CustomerGroupId": grp_id,
                "SalesCurrencyCode": customer.get("SalesCurrencyCode", "AED"),
                "SalesTaxGroup": customer.get("SalesTaxGroup", "AbuDhabi"),
            }
            status2, body2 = client.post("/CustomersV3", post_body)
            # Capture the auto-assigned CustomerAccount from the response
            new_account = (body2 or {}).get("CustomerAccount", "")
            resolved_customer_account = new_account
            calls.append(D365CallResult(
                entity="CustomersV3", method="POST", path="/CustomersV3",
                status_code=status2, success=status2 in (200, 201, 409),
                response_body={
                    **body2,
                    "_assigned_account": new_account,
                    "_address_to_create": customer_address,
                } if new_account else body2,
                executed_at=_now(),
            ))

    if customer_address and resolved_customer_account:
        calls.extend(_create_customer_address_calls(client, da, resolved_customer_account, customer_address))
    elif customer_address and not resolved_customer_account:
        calls.append(D365CallResult(
            entity="CustomerPostalAddress",
            method="POST",
            path="/CustomerPostalAddress*",
            status_code=400,
            success=False,
            response_body={},
            error="Address extracted but no CustomerAccount was available from existing lookup or create response.",
            executed_at=_now(),
        ))

    # ── Step 3: Payment terms — GET check, POST only if absent ──
    # Confirmed mandatory: dataAreaId, Name  (all others are optional)
    pt = payload.get("paymentTerms", {})
    pt_name = pt.get("Name", "")
    if pt_name:
        status, body = client.get(f"/PaymentTerms(dataAreaId='{da}',Name='{pt_name}')")
        calls.append(D365CallResult(entity="PaymentTerms", method="GET", path=f"/PaymentTerms(dataAreaId='{da}',Name='{pt_name}')", status_code=status, success=status in (200, 404), response_body=body, executed_at=_now()))
        if status == 404:
            post_body = {
                "dataAreaId": da,
                "Name": pt_name,
                "Description": pt.get("Description", f"Payment terms {pt_name}"),
                "NumberOfDays": int(pt.get("NumberOfDays") or 0),
                "PaymentMethodType": "Net",
            }
            status2, body2 = client.post("/PaymentTerms", post_body)
            calls.append(D365CallResult(entity="PaymentTerms", method="POST", path="/PaymentTerms", status_code=status2, success=status2 in (200, 201, 409), response_body=body2, executed_at=_now()))

    # ── Step 3b: Ensure customer master has Terms of Payment set ──
    if resolved_customer_account and pt_name:
        customer_path = f"/CustomersV3(dataAreaId='{da}',CustomerAccount='{resolved_customer_account}')"
        patch_body = {"PaymentTerms": pt_name}
        patch_status, patch_body_resp = client.patch(customer_path, patch_body)
        calls.append(D365CallResult(
            entity="CustomersV3",
            method="PATCH",
            path=customer_path,
            status_code=patch_status,
            success=patch_status in (200, 204),
            response_body={"request_payload": patch_body, "response": patch_body_resp},
            error=None if patch_status in (200, 204) else (
                f"Failed to update customer payment terms to '{pt_name}' for account '{resolved_customer_account}'."
            ),
            executed_at=_now(),
        ))

    # ── Step 4: Project group — GET check only; must already exist in D365 ──
    # D365 key field is 'ProjectGroup' (not 'ProjectGroupId')
    pg = payload.get("projectGroup", {})
    pg_id = pg.get("ProjectGroupId", "")
    if pg_id:
        status, body = client.get(f"/ProjectGroups?$filter=dataAreaId eq '{da}' and ProjectGroup eq '{pg_id}'&$top=1")
        pg_found = status == 200 and bool((body or {}).get("value"))
        calls.append(D365CallResult(
            entity="ProjectGroups",
            method="GET",
            path=f"/ProjectGroups?$filter=dataAreaId eq '{da}' and ProjectGroup eq '{pg_id}'&$top=1",
            status_code=status,
            success=pg_found,
            response_body=body,
            error=None if pg_found else f"Project group '{pg_id}' not found in company '{da}' — create it in D365 first.",
            executed_at=_now(),
        ))

    return calls


def _plan_project_contract(payload: dict, client: D365Client) -> list[D365CallResult]:
    calls: list[D365CallResult] = []

    def _error_text(body: dict | None) -> str:
        if not isinstance(body, dict):
            return ""
        err = body.get("error") or {}
        inner = err.get("innererror") if isinstance(err, dict) else {}
        if isinstance(inner, dict) and inner.get("message"):
            return str(inner.get("message"))
        if isinstance(err, dict) and err.get("message"):
            return str(err.get("message"))
        if body.get("Message"):
            return str(body.get("Message"))
        return ""

    def _is_placeholder_customer(account: str) -> bool:
        a = str(account or "").strip().upper()
        return (not a) or a.startswith("C-CUST") or a == "CUSTOMER NAME"

    def _resolve_customer_account(da: str, account_hint: str, customer_name: str) -> str:
        hint = str(account_hint or "").strip()
        if hint and not _is_placeholder_customer(hint):
            return hint

        name = str(customer_name or "").strip()
        if not name:
            return ""
        encoded = name.replace("'", "''")
        path = (
            f"/CustomersV3?$filter=dataAreaId eq '{da}'"
            f" and OrganizationName eq '{encoded}'&$top=1"
        )
        status, body = client.get(path)
        found = status == 200 and bool((body or {}).get("value"))
        resolved = (body or {}).get("value", [{}])[0].get("CustomerAccount", "") if found else ""
        calls.append(D365CallResult(
            entity="CustomersV3",
            method="GET",
            path=path,
            status_code=status,
            success=found,
            response_body={**(body or {}), "_resolved_account": resolved} if found else body,
            error=None if found else f"Customer '{name}' not found in company '{da}'.",
            executed_at=_now(),
        ))
        return resolved

    headers = payload.get("ProjectContractHeaders", [])
    funding_sources = payload.get("ProjectContractFundingSources", [])
    funding_rules = payload.get("ProjectContractFundingRules", [])

    # Pre-check: in this tenant, ProjectParameterV2 returns zero rows when Project Operations
    # integration is not enabled for the legal entity used by contract posting.
    pre_da = str((headers[0].get("dataAreaId") if headers else "2020") or "2020")
    pre_status, pre_body = client.get("/ProjectParameterV2?$top=1")
    pre_rows = (pre_body or {}).get("value", []) if isinstance(pre_body, dict) else []
    legacy_mode = pre_status == 200 and not pre_rows
    calls.append(D365CallResult(
        entity="ProjectParameters",
        method="GET",
        path="/ProjectParameterV2?$top=1",
        status_code=pre_status,
        success=pre_status == 200,
        response_body={**(pre_body or {}), "_mode": "legacy" if legacy_mode else "project_operations"},
        error=(
            f"Project Operations Integration appears disabled for legal entity '{pre_da}'. "
            "Using legacy ProjectContracts fallback path for Step 2."
            if legacy_mode
            else None
        ),
        executed_at=_now(),
    ))

    # Resolve and normalize customer account before any contract write.
    for header in headers:
        da = str(header.get("dataAreaId", "2020"))
        resolved = _resolve_customer_account(
            da,
            str(header.get("CustomerAccount", "")),
            str(header.get("_customer_name", "")),
        )
        if not resolved:
            calls.append(D365CallResult(
                entity="ProjectContractHeaders",
                method="POST",
                path="/ProjectContractHeaders",
                status_code=400,
                success=False,
                response_body=header,
                error="Cannot create project contract without a valid CustomerAccount.",
                executed_at=_now(),
            ))
            return calls

        header["CustomerAccount"] = resolved
        for fs in funding_sources:
            if str(fs.get("ProjectContractId", "")) == str(header.get("ProjectContractId", "")):
                fs["CustomerAccount"] = resolved

    # Header: GET by natural key, POST only if absent. When source data has no explicit
    # contract ID, derive the next one from the existing PC-###### sequence in this company,
    # since this tenant's ProjectContractID field is manual (D365 does not expose a
    # number-sequence "get next" action over OData and rejects a blank/empty value on create).
    header_failed = False
    placeholder_contract_ids = {"PC-001", "PC001", "TBD", "TEMP", "NA", "N/A"}
    for header in headers:
        original_contract_id = str(header.get("ProjectContractId", "") or "")
        contract_id = original_contract_id
        # Template IDs (for example PC-001) are not unique in real runs; treat as missing
        # so each new upload gets the next available contract number.
        if contract_id.strip().upper() in placeholder_contract_ids:
            contract_id = ""
        da = header.get("dataAreaId", "2020")

        if legacy_mode:
            entity_name = "ProjectContracts"
            get_path = f"/ProjectContracts?$filter=dataAreaId eq '{da}' and ProjectContractID eq '{contract_id}'&$top=1"
        else:
            entity_name = "ProjectContractHeaders"
            get_path = f"/ProjectContractHeaders?$filter=dataAreaId eq '{da}' and ProjectContractId eq '{contract_id}'&$top=1"

        if contract_id:
            status, body = client.get(get_path)
            exists = status == 200 and bool((body or {}).get("value"))
            matched_contract_id = ""
            if exists:
                row0 = (body or {}).get("value", [{}])[0]
                matched_contract_id = str(row0.get("ProjectContractID") or row0.get("ProjectContractId") or contract_id)
            calls.append(D365CallResult(
                entity=entity_name,
                method="GET",
                path=get_path,
                status_code=status,
                success=status == 200,
                response_body={
                    **(body or {}),
                    "_action": "skip_create",
                    "_matched_contract_id": matched_contract_id,
                } if exists else body,
                error=None if status == 200 else f"Unexpected HTTP {status} checking project contract.",
                executed_at=_now(),
            ))
        else:
            exists = False
            id_field = "ProjectContractID" if legacy_mode else "ProjectContractId"
            contract_id = _next_available_id(
                client, entity_name, id_field, da, lambda n: f"PC-{n:06d}"
            )
            header["ProjectContractId"] = contract_id
            for fs in funding_sources:
                if str(fs.get("ProjectContractId", "")) == original_contract_id:
                    fs["ProjectContractId"] = contract_id
            for fr in funding_rules:
                if str(fr.get("ProjectContractId", "")) == original_contract_id:
                    fr["ProjectContractId"] = contract_id
            calls.append(D365CallResult(
                entity=entity_name,
                method="INFO",
                path=f"/{entity_name}?$filter=dataAreaId eq '{da}' and {id_field} eq '{contract_id}'&$top=1",
                status_code=200,
                success=True,
                response_body={
                    "_action": "create_new",
                    "_assigned_contract_id": contract_id,
                    "_note": (
                        "No contract ID supplied; found next unused ID by probing the "
                        "PC-###### sequence since this tenant's ProjectContractID field "
                        "requires a manual value and rejects startswith/ge filters."
                    ),
                },
                error=None,
                executed_at=_now(),
            ))

        if not exists:
            if legacy_mode:
                post_body = {
                    "dataAreaId": da,
                    "Name": header.get("Name", "Project Contract"),
                    "SalesCurrency": header.get("CurrencyCode", "AED"),
                    "SalesTaxGroup": header.get("SalesTaxGroup", "AbuDhabi"),
                }
                if contract_id:
                    post_body["ProjectContractID"] = contract_id
                post_path = "/ProjectContracts"
                post_entity = "ProjectContracts"
            else:
                post_body = {
                    "dataAreaId": da,
                    "Name": header.get("Name", "Project Contract"),
                    "CustomerAccountNumber": header.get("CustomerAccount", ""),
                    "SalesCurrencyCode": header.get("CurrencyCode", "AED"),
                    "TermsOfPayment": header.get("PaymentTerms", "N060"),
                    "SalesTaxGroupCode": header.get("SalesTaxGroup", "AbuDhabi"),
                }
                if contract_id:
                    post_body["ProjectContractId"] = contract_id
                post_path = "/ProjectContractHeaders"
                post_entity = "ProjectContractHeaders"

            post_body = {k: v for k, v in post_body.items() if v not in (None, "")}
            status2, body2 = client.post(post_path, post_body)
            err_text = _error_text(body2)
            blocked_by_prereq = "has not turned on Project Operations Integration" in err_text
            calls.append(D365CallResult(
                entity=post_entity,
                method="POST",
                path=post_path,
                status_code=status2,
                success=status2 in (200, 201, 409),
                response_body=body2,
                error=(
                    "Project Operations Integration is disabled for legal entity "
                    f"'{da}'. Enable it in Project parameters before Step 2 can create contracts."
                    if blocked_by_prereq
                    else None
                ),
                executed_at=_now(),
            ))
            if status2 not in (200, 201, 409):
                header_failed = True
            elif status2 in (200, 201) and isinstance(body2, dict):
                assigned_id = body2.get("ProjectContractID") or body2.get("ProjectContractId")
                if assigned_id and str(assigned_id) != original_contract_id:
                    assigned_id = str(assigned_id)
                    header["ProjectContractId"] = assigned_id
                    for fs in funding_sources:
                        if str(fs.get("ProjectContractId", "")) == original_contract_id:
                            fs["ProjectContractId"] = assigned_id
                    for fr in funding_rules:
                        if str(fr.get("ProjectContractId", "")) == original_contract_id:
                            fr["ProjectContractId"] = assigned_id

    # Do not post funding objects when contract header create/check failed.
    if header_failed:
        return calls

    # Funding source: use ProjectFundingSources entity set in this environment.
    for fs in funding_sources:
        da = str(fs.get("dataAreaId") or (headers[0].get("dataAreaId") if headers else "2020"))
        contract_id = str(fs.get("ProjectContractId") or (headers[0].get("ProjectContractId") if headers else ""))
        fs_id = str(fs.get("FundingSourceId", "FS-001"))

        fs_get_path = (
            f"/ProjectFundingSources?$filter=dataAreaId eq '{da}'"
            f" and ProjectContractID eq '{contract_id}'"
            f" and FundingSourceId eq '{fs_id}'&$top=1"
        )
        fs_status, fs_body = client.get(fs_get_path)
        fs_exists = fs_status == 200 and bool((fs_body or {}).get("value"))
        calls.append(D365CallResult(
            entity="ProjectFundingSources",
            method="GET",
            path=fs_get_path,
            status_code=fs_status,
            success=fs_status == 200,
            response_body={**(fs_body or {}), "_action": "skip_create"} if fs_exists else fs_body,
            error=None if fs_status == 200 else f"Unexpected HTTP {fs_status} checking funding source.",
            executed_at=_now(),
        ))
        if fs_exists:
            continue

        post_body = {
            "dataAreaId": da,
            "ProjectContractID": contract_id,
            "FundingSourceId": fs_id,
            "FundingType": fs.get("FundingSourceType", "Customer"),
            "CustomerOrOrganization": fs.get("CustomerAccount", ""),
            "TermsOfPayment": fs.get("PaymentTerms", "N060"),
            "CreateDefaultFundingRule": "No",
        }
        if not legacy_mode:
            post_body["IsPrimaryFundingSource"] = "Yes"
        post_body = {k: v for k, v in post_body.items() if v not in (None, "")}
        status2, body2 = client.post("/ProjectFundingSources", post_body)
        calls.append(D365CallResult(
            entity="ProjectFundingSources",
            method="POST",
            path="/ProjectFundingSources",
            status_code=status2,
            success=status2 in (200, 201, 409),
            response_body=body2,
            executed_at=_now(),
        ))

    # Funding rule: in legacy mode, defer until Step 3 after projects exist.
    if legacy_mode and funding_rules:
        calls.append(D365CallResult(
            entity="ProjectFundingRules",
            method="DEFER",
            path="/ProjectFundingRules",
            status_code=202,
            success=True,
            response_body={
                "deferred_count": len(funding_rules),
                "reason": "Legacy mode requires existing ProjectId for funding rule creation.",
            },
            error=None,
            executed_at=_now(),
        ))
    else:
        for fr in funding_rules:
            da = str(fr.get("dataAreaId") or (headers[0].get("dataAreaId") if headers else "2020"))
            contract_id = str(fr.get("ProjectContractId") or (headers[0].get("ProjectContractId") if headers else ""))
            post_body = {
                "dataAreaId": da,
                "ProjectContractId": contract_id,
                "ProjectId": fr.get("ProjectId", contract_id.replace("PC-", "PROJ-")),
                "FundingSourceId": fr.get("FundingSourceId") or (funding_sources[0].get("FundingSourceId") if funding_sources else "FS-001"),
                "Priority": 1,
                "AllocationPercentage": float(fr.get("ContributionPercent") or 100.0),
                "AllocateRounding": "No",
            }
            post_body = {k: v for k, v in post_body.items() if v not in (None, "")}
            status2, body2 = client.post("/ProjectFundingRules", post_body)
            calls.append(D365CallResult(
                entity="ProjectFundingRules",
                method="POST",
                path="/ProjectFundingRules",
                status_code=status2,
                success=status2 in (200, 201, 409),
                response_body=body2,
                executed_at=_now(),
            ))

    return calls


def _plan_project_master(payload: dict, client: D365Client) -> list[D365CallResult]:
    calls: list[D365CallResult] = []
    projects = payload.get("ProjectsV2", [])
    if not projects:
        calls.append(D365CallResult(
            entity="ProjectsV2",
            method="POST",
            path="/ProjectsV2",
            status_code=400,
            success=False,
            response_body={},
            error="No project rows extracted for Step 3.",
            executed_at=_now(),
        ))
        return calls

    def _error_text(body: dict | None) -> str:
        if not isinstance(body, dict):
            return ""
        err = body.get("error") or {}
        inner = err.get("innererror") if isinstance(err, dict) else {}
        if isinstance(inner, dict) and inner.get("message"):
            return str(inner.get("message"))
        if isinstance(err, dict) and err.get("message"):
            return str(err.get("message"))
        if body.get("Message"):
            return str(body.get("Message"))
        return ""

    def _is_placeholder_customer(account: str) -> bool:
        a = str(account or "").strip().upper()
        return (not a) or a.startswith("C-CUST") or a == "CUSTOMER NAME"

    def _resolve_customer_account(da: str, account_hint: str, customer_name: str) -> str:
        hint = str(account_hint or "").strip()
        if hint and not _is_placeholder_customer(hint):
            return hint
        name = str(customer_name or "").strip()
        if not name:
            return ""
        encoded = name.replace("'", "''")
        path = (
            f"/CustomersV3?$filter=dataAreaId eq '{da}'"
            f" and OrganizationName eq '{encoded}'&$top=1"
        )
        status, body = client.get(path)
        found = status == 200 and bool((body or {}).get("value"))
        resolved = (body or {}).get("value", [{}])[0].get("CustomerAccount", "") if found else ""
        calls.append(D365CallResult(
            entity="CustomersV3",
            method="GET",
            path=path,
            status_code=status,
            success=found,
            response_body={**(body or {}), "_resolved_account": resolved} if found else body,
            error=None if found else f"Customer '{name}' not found in company '{da}'.",
            executed_at=_now(),
        ))
        return resolved

    # Mode detection matches Step 2 behavior.
    pre_status, pre_body = client.get("/ProjectParameterV2?$top=1")
    pre_rows = (pre_body or {}).get("value", []) if isinstance(pre_body, dict) else []
    legacy_mode = pre_status == 200 and not pre_rows

    calls.append(D365CallResult(
        entity="ProjectParameters",
        method="GET",
        path="/ProjectParameterV2?$top=1",
        status_code=pre_status,
        success=pre_status == 200,
        response_body={**(pre_body or {}), "_mode": "legacy" if legacy_mode else "project_operations"},
        error=(
            "Project Operations Integration appears disabled; using legacy Projects fallback path for Step 3."
            if legacy_mode
            else None
        ),
        executed_at=_now(),
    ))

    # Pre-check: required contract must already exist for every referenced ProjectContractId.
    # Accept either ProjectContractHeaders (Project Ops) or ProjectContracts (legacy mode).
    contracts = {(str(p.get("dataAreaId", "2020")), str(p.get("ProjectContractId", ""))) for p in projects if p.get("ProjectContractId")}
    for da, contract_id in contracts:
        path1 = f"/ProjectContractHeaders?$filter=dataAreaId eq '{da}' and ProjectContractId eq '{contract_id}'&$top=1"
        status1, body1 = client.get(path1)
        exists1 = status1 == 200 and bool((body1 or {}).get("value"))

        path2 = f"/ProjectContracts?$filter=dataAreaId eq '{da}' and ProjectContractID eq '{contract_id}'&$top=1"
        status2, body2 = client.get(path2)
        exists2 = status2 == 200 and bool((body2 or {}).get("value"))
        exists = exists1 or exists2

        response_body = {
            "headers_check": {"status": status1, "exists": exists1, "body": body1},
            "legacy_check": {"status": status2, "exists": exists2, "body": body2},
        }
        calls.append(D365CallResult(
            entity="ProjectContracts",
            method="GET",
            path=f"{path1} OR {path2}",
            status_code=200 if exists else status1,
            success=exists,
            response_body=response_body,
            error=None if exists else (
                f"Project contract '{contract_id}' not found in company '{da}'. "
                "Complete Step 2 successfully before Step 3."
            ),
            executed_at=_now(),
        ))
        if not exists:
            return calls

    # Parent first, then children (children are identified either by an explicit
    # ParentProjectId or by an unresolved `_parent_seq_key` correlation from extraction).
    ordered_projects = sorted(
        projects,
        key=lambda p: (0 if not (p.get("ParentProjectId") or p.get("_parent_seq_key")) else 1),
    )

    seq_key_to_real_id: dict[str, str] = {}
    project_entity = "Projects" if legacy_mode else "ProjectsV2"
    project_id_field = "ProjectID" if legacy_mode else "ProjectId"

    for proj in ordered_projects:
        da = str(proj.get("dataAreaId") or "2020")
        project_id = str(proj.get("ProjectID") or proj.get("ProjectId") or "")

        # Resolve parent link first: correlation key (unassigned source) takes
        # priority, falling back to whatever explicit ParentProjectId was supplied.
        parent_seq_key = proj.get("_parent_seq_key")
        real_parent_id = str(proj.get("ParentProjectId") or "") or ""
        if parent_seq_key and parent_seq_key in seq_key_to_real_id:
            real_parent_id = seq_key_to_real_id[parent_seq_key]
            proj["ParentProjectId"] = real_parent_id

        if not project_id:
            if real_parent_id:
                # Sub-project: derive next child code under the resolved parent ID.
                project_id = _next_available_id(
                    client, project_entity, project_id_field, da,
                    lambda n, p=real_parent_id: f"{p}-{n:02d}",
                )
                seq_note = (
                    f"No ProjectID supplied; found next unused sub-project ID under parent '{real_parent_id}'."
                )
            else:
                # Top-level project: find next unused number in the PROJ-###### sequence,
                # since D365 requires a manual value and rejects startswith/ge filters here.
                project_id = _next_available_id(
                    client, project_entity, project_id_field, da,
                    lambda n: f"PROJ-{n:06d}",
                )
                seq_note = (
                    "No ProjectID supplied; found next unused ID by probing the PROJ-###### "
                    "sequence since this tenant's ProjectID field requires a manual value."
                )

            proj["ProjectID"] = project_id
            calls.append(D365CallResult(
                entity=project_entity,
                method="INFO",
                path="(project sequence)",
                status_code=200,
                success=True,
                response_body={"_action": "assign_new", "_assigned_project_id": project_id, "_note": seq_note},
                error=None,
                executed_at=_now(),
            ))

        if proj.get("_seq_key"):
            seq_key_to_real_id[str(proj["_seq_key"])] = project_id

        if not project_id:
            calls.append(D365CallResult(
                entity="ProjectsV2",
                method="POST",
                path="/ProjectsV2",
                status_code=400,
                success=False,
                response_body=proj,
                error="ProjectID is required for ProjectsV2 create.",
                executed_at=_now(),
            ))
            return calls

        resolved_customer = _resolve_customer_account(da, str(proj.get("CustomerAccount", "")), str(proj.get("_customer_name", "")))
        if not resolved_customer:
            calls.append(D365CallResult(
                entity="ProjectsV2",
                method="POST",
                path="/ProjectsV2",
                status_code=400,
                success=False,
                response_body=proj,
                error="Cannot create project without a valid CustomerAccount.",
                executed_at=_now(),
            ))
            return calls
        proj["CustomerAccount"] = resolved_customer

        if legacy_mode:
            get_path = f"/Projects?$filter=dataAreaId eq '{da}' and ProjectID eq '{project_id}'&$top=1"
            get_entity = "Projects"
        else:
            get_path = f"/ProjectsV2?$filter=dataAreaId eq '{da}' and ProjectId eq '{project_id}'&$top=1"
            get_entity = "ProjectsV2"

        status, body = client.get(get_path)
        exists = status == 200 and bool((body or {}).get("value"))
        calls.append(D365CallResult(
            entity=get_entity,
            method="GET",
            path=get_path,
            status_code=status,
            success=status == 200,
            response_body={**(body or {}), "_action": "skip_create"} if exists else body,
            error=None if status == 200 else f"Unexpected HTTP {status} checking project '{project_id}'.",
            executed_at=_now(),
        ))

        if not exists:
            if legacy_mode:
                # Legacy Projects entity fields differ from ProjectsV2 and enforces working dates.
                start_date = str(proj.get("ProjectStartDate") or "")[:10]
                end_date = str(proj.get("ProjectSchedulingEndDate") or start_date)[:10]
                post_body = {
                    "dataAreaId": da,
                    "ProjectID": project_id,
                    "ProjectName": proj.get("ProjectName", project_id),
                    "ProjectGroup": proj.get("ProjectGroupId", "FP-WIP"),
                    "ProjectType": proj.get("ProjectType", "FixedPrice"),
                    "ProjectStage": proj.get("ProjectStage", "InProcess"),
                    "CustomerAccount": resolved_customer,
                    "ProjectContractID": proj.get("ProjectContractId", ""),
                    "StartDate1": start_date,
                    "EndDate1": end_date,
                }
                parent_id = proj.get("ParentProjectId")
                if parent_id:
                    post_body["ParentProject"] = parent_id

                post_body = {k: v for k, v in post_body.items() if v not in (None, "")}
                status2, body2 = client.post("/Projects", post_body)
                err_text = _error_text(body2)

                # Retry once with today's date when calendar rejects the supplied start date.
                if status2 not in (200, 201, 409) and "Selected date is not a working date" in err_text:
                    today = datetime.utcnow().strftime("%Y-%m-%d")
                    retry_body = {**post_body, "StartDate1": today, "EndDate1": today}
                    status2, body2 = client.post("/Projects", retry_body)

                calls.append(D365CallResult(
                    entity="Projects",
                    method="POST",
                    path="/Projects",
                    status_code=status2,
                    success=status2 in (200, 201, 409),
                    response_body=body2,
                    executed_at=_now(),
                ))
            else:
                post_body = {
                    "dataAreaId": da,
                    "ProjectId": project_id,
                    "ProjectName": proj.get("ProjectName", project_id),
                    "ProjectGroupId": proj.get("ProjectGroupId", "FP-WIP"),
                    "ProjectStage": proj.get("ProjectStage", "InProcess"),
                    "ProjectContractId": proj.get("ProjectContractId", ""),
                    "CustomerAccountNumber": resolved_customer,
                    "ScheduleStartDate": str(proj.get("ProjectStartDate") or "")[:10],
                    "ScheduleEndDate": str(proj.get("ProjectSchedulingEndDate") or "")[:10],
                }
                parent_id = proj.get("ParentProjectId")
                if parent_id:
                    post_body["ParentProjectId"] = parent_id
                post_body = {k: v for k, v in post_body.items() if v not in (None, "")}
                status2, body2 = client.post("/ProjectsV2", post_body)
                calls.append(D365CallResult(
                    entity="ProjectsV2",
                    method="POST",
                    path="/ProjectsV2",
                    status_code=status2,
                    success=status2 in (200, 201, 409),
                    response_body=body2,
                    executed_at=_now(),
                ))

            if status2 not in (200, 201, 409):
                return calls

    return calls


def _plan_ifrs15_obligations(payload: dict, client: D365Client) -> list[D365CallResult]:
    calls: list[D365CallResult] = []
    lines = payload.get("ProjectContractLines", [])
    if not lines:
        return calls

    # Mode detection matches Steps 2/3: this tenant rejects ProjectContractLines writes
    # outright when Project Operations Integration is off for the legal entity.
    pre_status, pre_body = client.get("/ProjectParameterV2?$top=1")
    pre_rows = (pre_body or {}).get("value", []) if isinstance(pre_body, dict) else []
    legacy_mode = pre_status == 200 and not pre_rows
    calls.append(D365CallResult(
        entity="ProjectParameters",
        method="GET",
        path="/ProjectParameterV2?$top=1",
        status_code=pre_status,
        success=pre_status == 200,
        response_body={**(pre_body or {}), "_mode": "legacy" if legacy_mode else "project_operations"},
        error=None,
        executed_at=_now(),
    ))

    if legacy_mode:
        calls.append(D365CallResult(
            entity="Projects",
            method="INFO",
            path="/Projects",
            status_code=200,
            success=True,
            response_body={
                "_action": "carry_pob_allocation_on_subproject",
                "line_count": len(lines),
                "reason": (
                    "Project Operations Integration is disabled; ProjectContractLines writes are skipped. "
                    "Allocated POB amounts are written to each legacy sub-project record instead."
                ),
            },
            error=None,
            executed_at=_now(),
        ))

        for line in lines:
            da = str(line.get("dataAreaId") or "2020")
            line_project_id = str(line.get("LineProjectId") or line.get("ProjectId") or "")
            amount = _to_float(line.get("LineAmountExcludingTax") or line.get("LineAmount"), 0.0)

            if not line_project_id:
                calls.append(D365CallResult(
                    entity="Projects",
                    method="PATCH",
                    path="/Projects",
                    status_code=400,
                    success=False,
                    response_body=line,
                    error="Cannot carry POB allocation because the sub-project ID is missing.",
                    executed_at=_now(),
                ))
                return calls

            get_path = (
                f"/Projects?$filter=dataAreaId eq '{_odata_quote(da)}' and "
                f"ProjectID eq '{_odata_quote(line_project_id)}'&$top=1"
            )
            status, body = client.get(get_path)
            exists = status == 200 and bool((body or {}).get("value"))
            calls.append(D365CallResult(
                entity="Projects",
                method="GET",
                path=get_path,
                status_code=status,
                success=status == 200,
                response_body={**(body or {}), "_action": "verify_subproject_for_pob_allocation"} if exists else body,
                error=None if status == 200 else f"Unexpected HTTP {status} checking sub-project '{line_project_id}'.",
                executed_at=_now(),
            ))
            if not exists:
                calls.append(D365CallResult(
                    entity="Projects",
                    method="PATCH",
                    path="/Projects",
                    status_code=404,
                    success=False,
                    response_body=line,
                    error=f"Sub-project '{line_project_id}' was not found for POB allocation update.",
                    executed_at=_now(),
                ))
                return calls

            currency = str(line.get("CurrencyCode") or "").strip() or "AED"
            description = str(line.get("Description") or f"POB allocation for {line_project_id}").strip()
            allocation_note = f"IFRS15 allocated POB amount: {currency} {amount:.2f}"
            patch_path = f"/Projects(dataAreaId='{_odata_quote(da)}',ProjectID='{_odata_quote(line_project_id)}')"
            patch_body = {
                "Notes": allocation_note,
                "Description": f"{description[:160]} | {allocation_note}"[:250],
            }
            status2, body2 = client.patch(patch_path, patch_body)
            calls.append(D365CallResult(
                entity="Projects",
                method="PATCH",
                path=patch_path,
                status_code=status2,
                success=status2 in (200, 204),
                response_body={**(body2 or {}), "_patched": patch_body} if isinstance(body2, dict) else {"_patched": patch_body},
                error=None if status2 in (200, 204) else f"HTTP {status2} updating sub-project POB allocation.",
                executed_at=_now(),
            ))
            if status2 not in (200, 204):
                return calls

        return calls

    for line in lines:
        da = str(line.get("dataAreaId") or "2020")
        contract_id = str(line.get("ProjectContractId") or "")
        line_project_id = str(line.get("LineProjectId") or line.get("ProjectId") or "")
        contract_line_id = str(line.get("ContractLineId") or "")

        if not contract_line_id:
            contract_line_id = _next_available_id(
                client, "ProjectContractLines", "ContractLineId", da, lambda n: f"PBR-{n:06d}"
            )

        get_path = (
            f"/ProjectContractLines?$filter=dataAreaId eq '{da}' and ContractLineId eq "
            f"'{contract_line_id}'&$top=1"
        )
        status, body = client.get(get_path)
        exists = status == 200 and bool((body or {}).get("value"))
        calls.append(D365CallResult(
            entity="ProjectContractLines",
            method="GET",
            path=get_path,
            status_code=status,
            success=status == 200,
            response_body={**(body or {}), "_action": "skip_create"} if exists else body,
            error=None if status == 200 else f"Unexpected HTTP {status} checking contract line '{contract_line_id}'.",
            executed_at=_now(),
        ))
        if exists:
            continue

        post_body = {
            "dataAreaId": da,
            "ProjectContractId": contract_id,
            "ContractLineId": contract_line_id,
            "LineProjectId": line_project_id,
            "LineType": line.get("LineType", "LumpSum"),
            "BillingMethod": line.get("BillingMethod", "FixedPrice"),
            "LineAmount": line.get("LineAmountExcludingTax") or line.get("LineAmount") or 0.0,
            "SalesTaxGroupCode": line.get("SalesTaxGroupCode") or line.get("SalesTaxGroup") or "AbuDhabi",
            "StartDate": str(line.get("StartDate") or line.get("ProjectStartDate") or "")[:10],
            "EndDate": str(line.get("EndDate") or line.get("ProjectSchedulingEndDate") or "")[:10],
            "Description": line.get("Description", ""),
        }
        post_body = {k: v for k, v in post_body.items() if v not in (None, "")}
        status2, body2 = client.post("/ProjectContractLines", post_body)
        calls.append(D365CallResult(
            entity="ProjectContractLines",
            method="POST",
            path="/ProjectContractLines",
            status_code=status2,
            success=status2 in (200, 201, 409),
            response_body=body2,
            executed_at=_now(),
        ))
        if status2 not in (200, 201, 409):
            return calls

    return calls


def _post_all_or_defer(
    client: D365Client,
    entity: str,
    path: str,
    rows: list[dict],
    calls: list[D365CallResult],
    unavailable_note: str,
    include_defer_diagnostics: bool = False,
) -> None:
    """POST each row; if the first attempt shows the entity is missing (404) or
    read-only (403) in this tenant, defer the whole batch instead of repeating
    the same failure for every row."""
    for i, row in enumerate(rows):
        body = {k: v for k, v in row.items() if not k.startswith("_")}
        status2, body2 = client.post(path, body)
        if i == 0 and status2 in (404, 403):
            response_body = {
                "deferred_count": len(rows),
                "http_status_seen": status2,
                "reason": unavailable_note,
            }
            if include_defer_diagnostics:
                err_text = ""
                if isinstance(body2, dict):
                    err = body2.get("error")
                    if isinstance(err, dict):
                        err_text = str(err.get("message") or "")
                        inner = err.get("innererror")
                        if isinstance(inner, dict):
                            inner_msg = str(inner.get("message") or "")
                            if inner_msg:
                                err_text = f"{err_text} | {inner_msg}" if err_text else inner_msg
                    elif body2.get("raw"):
                        err_text = str(body2.get("raw"))

                response_body["diagnostic"] = {
                    "first_request_payload": body,
                    "d365_response": body2,
                    "d365_error_text": err_text,
                }

            calls.append(D365CallResult(
                entity=entity,
                method="DEFER",
                path=path,
                status_code=202,
                success=True,
                response_body=response_body,
                error=None,
                executed_at=_now(),
            ))
            return
        duplicate_exists = status2 == 400 and "record already exists" in _d365_error_text(body2).lower()
        response_body = body2
        if duplicate_exists and isinstance(response_body, dict):
            response_body = {**response_body, "_action": "skip_existing_duplicate"}
        calls.append(D365CallResult(
            entity=entity,
            method="POST",
            path=path,
            status_code=status2,
            success=status2 in (200, 201, 202, 409) or duplicate_exists,
            response_body=response_body,
            executed_at=_now(),
        ))


def _plan_milestone_billing(payload: dict, client: D365Client) -> list[D365CallResult]:
    calls: list[D365CallResult] = []
    on_account_note = (
        "Milestone billing recorded via tenant-exposed on-account entity "
        "ProjectOnAccForecasts."
    )

    trans_rows = payload.get("ProjOnaccounttrans", [])

    funding_source_cache: dict[tuple[str, str], str] = {}

    def _resolve_funding_source_id(data_area: str, contract_id: str) -> str:
        if not contract_id:
            return ""
        key = (data_area, contract_id)
        if key in funding_source_cache:
            return funding_source_cache[key]

        path = (
            f"/ProjectFundingSources?$filter=dataAreaId eq '{data_area}'"
            f" and ProjectContractID eq '{contract_id}'&$top=1"
        )
        status, body = client.get(path)
        fs_id = ""
        if status == 200 and isinstance(body, dict):
            rows = body.get("value") or []
            if rows:
                fs_id = str(rows[0].get("FundingSourceId") or "")
        funding_source_cache[key] = fs_id
        return fs_id

    # Tenant metadata discovery confirms these exact endpoint names are exposed.
    forecast_rows: list[dict[str, Any]] = []
    for i, row in enumerate(trans_rows, start=1):
        amount = _to_float(row.get("Amount"), 0.0)
        da = str(row.get("dataAreaId") or "2020")
        contract_id = str(row.get("ProjectContractId") or "")
        funding_source_id = _resolve_funding_source_id(da, contract_id)
        forecast_rows.append({
            "dataAreaId": da,
            "Description": row.get("Description") or row.get("MilestoneDescription") or "Milestone on-account",
            "ProjectID": row.get("ProjectId") or "",
            "FundingSourceID": funding_source_id,
            "InvoiceDate": _to_odata_datetime(row.get("BillingDate") or row.get("TransactionDate")),
            "ExchangeRate": 1.0,
            "SalesCurrency": row.get("CurrencyCode") or "AED",
            "ProjectDate": _to_odata_datetime(row.get("TransactionDate") or row.get("BillingDate")),
            "SalesPrice": amount,
            "EliminationDate": _to_odata_datetime(row.get("BillingDate") or row.get("TransactionDate")),
            "ProjectContractID": contract_id,
            "SalesPaymentDate": _to_odata_datetime(row.get("BillingDate") or row.get("TransactionDate")),
        })

    # Post to ProjectOnAccForecasts — internal on-account forecast transactions.
    _post_all_or_defer(
        client, "ProjectOnAccForecasts", "/ProjectOnAccForecasts",
        forecast_rows, calls, on_account_note, include_defer_diagnostics=True,
    )
    calls.append(D365CallResult(
        entity="ProjectOnAccForecasts",
        method="INFO",
        path="(standard copy follow-up)",
        status_code=200,
        success=True,
        response_body={
            "_action": "manual_standard_copy_required",
            "message": (
                "Standard copy to actual on-account transactions is not exposed through OData; "
                "run D365 standard copy manually or expose a custom service action."
            ),
        },
        error=None,
        executed_at=_now(),
    ))
    return calls


def _plan_invoice_schedule(payload: dict, client: D365Client) -> list[D365CallResult]:
    calls: list[D365CallResult] = []
    unavailable_note = (
        "ProjectInvoiceProposalHeaders/ProjectInvoiceProposalOnAccountLines are not writable in "
        "this tenant. On-account invoices are recorded directly in the D365 UI; the only queryable "
        "entities here are read-only reporting views (DocumentProjectInvoiceBaseV2, "
        "InvoiceMilestonesV2_G42)."
    )
    _post_all_or_defer(
        client, "ProjectInvoiceProposalHeaders", "/ProjectInvoiceProposalHeaders",
        payload.get("ProjectInvoiceProposalHeaders", []), calls, unavailable_note,
    )
    _post_all_or_defer(
        client, "ProjectInvoiceProposalOnAccountLines", "/ProjectInvoiceProposalOnAccountLines",
        payload.get("ProjectInvoiceProposalOnAccountLines", []), calls, unavailable_note,
    )
    return calls



def _plan_revenue_recognition(payload: dict, client: D365Client) -> list[D365CallResult]:
    schedule = payload.get("revenueRecognitionSchedule", [])
    return [
        D365CallResult(
            entity="D365 Revenue Recognition Automation Batch",
            method="INFO",
            path="(D365 scheduled batch)",
            status_code=200,
            success=True,
            response_body={
                "_action": "handled_by_d365_revenue_recognition_batch",
                "schedule_period_count": len(schedule) if isinstance(schedule, list) else 0,
                "message": (
                    "Revenue Recognition is handled automatically inside D365 by the configured "
                    "revenue recognition automation batch based on the extracted schedule. "
                    "No separate posting agent is required."
                ),
            },
            error=None,
            executed_at=_now(),
        )
    ]


STEP_PLANS = {
    "reference_data": _plan_reference_data,
    "project_contract": _plan_project_contract,
    "project_master": _plan_project_master,
    "ifrs15_obligations": _plan_ifrs15_obligations,
    "milestone_billing": _plan_milestone_billing,
    "invoice_schedule": _plan_invoice_schedule,
    "revenue_recognition": _plan_revenue_recognition,
}


def execute_step(step: ProcessStep, client: D365Client) -> ProcessStep:
    """Execute all D365 OData calls for the given step and update step status."""
    step.status = StepStatus.POSTING
    step.started_at = _now()
    step.d365_calls = []

    # ── Pre-flight: extracted payload must exist ──
    if not step.extracted_payload:
        step.status = StepStatus.FAILED
        step.error_message = "Extraction produced no payload for this step — re-run Extract & Process."
        step.completed_at = _now()
        return step

    plan_fn = STEP_PLANS.get(step.id)
    if plan_fn is None:
        step.status = StepStatus.FAILED
        step.error_message = f"No execution plan registered for step '{step.id}'."
        step.completed_at = _now()
        return step

    # ── Pre-flight: Azure AD token acquisition ──
    auth_ok, auth_msg = client.preflight_auth()
    if not auth_ok:
        step.d365_calls = [D365CallResult(
            entity="Azure AD",
            method="TOKEN",
            path=f"https://login.microsoftonline.com/{client.tenant_id}/oauth2/v2.0/token",
            status_code=401,
            success=False,
            error=auth_msg,
            executed_at=_now(),
        )]
        step.status = StepStatus.FAILED
        step.error_message = f"Authentication failed — {auth_msg}"
        step.completed_at = _now()
        return step

    # ── Execute the step plan — each call wrapped to capture partial progress ──
    try:
        calls = plan_fn(step.extracted_payload, client)
        step.d365_calls = calls
        failed = [c for c in calls if not c.success]
        if failed:
            step.status = StepStatus.FAILED
            step.error_message = f"{len(failed)} D365 call(s) failed: " + "; ".join(
                f"{c.entity} {c.method} → HTTP {c.status_code}" for c in failed
            )
        else:
            step.status = StepStatus.POSTED
    except Exception as exc:  # noqa: BLE001
        step.status = StepStatus.FAILED
        step.error_message = str(exc)

    step.completed_at = _now()
    return step
