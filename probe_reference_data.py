"""Live probe: test Customer POST, PaymentTerms POST, and ProjectGroups GET against D365."""
from dotenv import load_dotenv
load_dotenv()
from backend.services.d365_client import build_client_from_env
from backend.services.excel_extractor import extract_all
import json

c = build_client_from_env()
c.preflight_auth()
da = c.data_area_id

payloads = extract_all(
    "Sample contract excel file which user upload/"
    "Project agent 1a - Engagement Letter - Presight and Daypop_IFRS15_Analysis.xlsx"
)
ref = payloads["reference_data"]

SEP = "-" * 60

# ── 1. Customer GET (by name) ──────────────────────────────────
org = ref["customer"].get("OrganizationName", "")
enc = org.replace("'", "''")
print(SEP)
print(f"1. Customer GET (name={org!r})")
s, b = c.get(f"/CustomersV3?$filter=dataAreaId eq '{da}' and OrganizationName eq '{enc}'&$top=1")
print(f"   HTTP {s}")
exists = s == 200 and bool((b or {}).get("value"))
print(f"   exists={exists}")

if not exists:
    post_body = {
        "dataAreaId": da,
        "OrganizationName": org,
        "CustomerGroupId": "L_NGVN",
        "SalesCurrencyCode": ref["customer"].get("SalesCurrencyCode", "AED"),
        "SalesTaxGroup": ref["customer"].get("SalesTaxGroup", "AbuDhabi"),
    }
    print(f"\n   POST body: {json.dumps(post_body, indent=4)}")
    s2, b2 = c.post("/CustomersV3", post_body)
    print(f"   POST HTTP {s2}")
    print(f"   {json.dumps(b2, indent=4)[:600]}")

# ── 2. PaymentTerms GET then POST ─────────────────────────────
pt = ref["paymentTerms"]
pt_name = pt.get("Name", "")
print(f"\n{SEP}")
print(f"2. PaymentTerms GET (Name={pt_name!r})")
s, b = c.get(f"/PaymentTerms(dataAreaId='{da}',Name='{pt_name}')")
print(f"   HTTP {s}")
if s == 404:
    post_body = {
        "dataAreaId": da,
        "Name": pt_name,
        "Description": pt.get("Description", f"Payment terms {pt_name}"),
        "NumberOfDays": int(pt.get("NumberOfDays") or 0),
        "PaymentMethodType": "Net",
    }
    print(f"\n   POST body: {json.dumps(post_body, indent=4)}")
    s2, b2 = c.post("/PaymentTerms", post_body)
    print(f"   POST HTTP {s2}")
    print(f"   {json.dumps(b2, indent=4)[:600]}")

# ── 3. ProjectGroups — try filter-based query instead of key-based ────────────
pg_id = ref["projectGroup"].get("ProjectGroupId", "FP-WIP")
print(f"\n{SEP}")
print(f"3a. ProjectGroups filter GET (ProjectGroupId={pg_id!r})")
s, b = c.get(f"/ProjectGroups?$filter=dataAreaId eq '{da}' and ProjectGroupId eq '{pg_id}'&$top=1")
print(f"   HTTP {s}  |  {json.dumps(b, indent=4)[:400]}")

print(f"\n3b. ProjectGroups list (first 1)")
s, b = c.get(f"/ProjectGroups?$filter=dataAreaId eq '{da}'&$top=1")
print(f"   HTTP {s}  |  {json.dumps(b, indent=4)[:400]}")

print(f"\n3c. ProjGroup (alternative entity name)")
s, b = c.get(f"/ProjGroups?$filter=dataAreaId eq '{da}'&$top=1")
print(f"   HTTP {s}  |  {json.dumps(b, indent=4)[:400]}")
