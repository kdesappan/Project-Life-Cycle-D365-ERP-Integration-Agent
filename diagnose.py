"""One-shot connectivity diagnostic — run with: python diagnose.py"""
from dotenv import load_dotenv
load_dotenv()

from backend.services.d365_client import build_client_from_env

c = build_client_from_env()
print("=" * 60)
print("D365 Client Configuration")
print("=" * 60)
print(f"  base_url     : {c.base_url}")
print(f"  resource_host: {c._resource_host}")
print(f"  tenant_id    : {c.tenant_id}")
print(f"  client_id    : {c.client_id}")
print(f"  secret set   : {bool(c.client_secret)}")
print(f"  data_area_id : {c.data_area_id}")

print()
print("Step 1 — Azure AD token acquisition")
print("-" * 40)
ok, msg = c.preflight_auth()
print(f"  result : {'OK' if ok else 'FAILED'}")
print(f"  detail : {msg}")

if ok:
    print()
    print("Step 2 — GET LegalEntities (company 2020 existence check)")
    print("-" * 40)
    try:
        status, body = c.get(f"/LegalEntities?$filter=LegalEntityId eq '{c.data_area_id}'")
        print(f"  HTTP status : {status}")
        print(f"  Response    : {str(body)[:400]}")
    except Exception as e:
        print(f"  EXCEPTION: {e}")
else:
    print()
    print("Skipping OData calls — auth failed.")
    print()
    print("Common causes:")
    print("  1. Wrong Client Secret (check for leading/trailing spaces in .env)")
    print("  2. Expired secret — regenerate in Azure Portal > App registrations")
    print("  3. App not registered in D365: System admin > Entra ID applications")
    print("  4. Corporate proxy blocking login.microsoftonline.com")
    print("  5. Scope issue — the D365_BASE_URL must match the registered app audience")
