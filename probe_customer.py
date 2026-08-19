"""POST a minimal CustomersV3 payload to D365 and print the validation error,
which lists every mandatory field that is missing.
Run with: python probe_customer.py
"""
from dotenv import load_dotenv
load_dotenv()

from backend.services.d365_client import build_client_from_env
import json

c = build_client_from_env()
ok, msg = c.preflight_auth()
print("Auth:", msg)
if not ok:
    raise SystemExit("Auth failed")

# Minimal probe — deliberately missing fields so D365 tells us what is required
probe = {
    "dataAreaId": c.data_area_id,
    "CustomerGroupId": "L_NGVN",
    "OrganizationName": "__PROBE_DELETE_ME__",
    "SalesCurrencyCode": "AED",
    "SalesTaxGroup": "AbuDhabi",
}

print("\nPOSTing minimal probe to /CustomersV3 ...")
status, body = c.post("/CustomersV3", probe)
print(f"HTTP {status}")
print(json.dumps(body, indent=2))
