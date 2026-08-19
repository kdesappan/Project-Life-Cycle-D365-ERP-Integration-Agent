"""Delete the probe PaymentTerms record and update the agent with confirmed mandatory fields."""
from dotenv import load_dotenv
load_dotenv()
from backend.services.d365_client import build_client_from_env
import httpx, json

c = build_client_from_env()
c.preflight_auth()
url = f"{c.base_url}/PaymentTerms(dataAreaId='{c.data_area_id}',Name='__PROBE_PT__')"
r = httpx.delete(url, headers=c._headers(), params={"cross-company": "true"}, timeout=60)
print(f"DELETE HTTP {r.status_code} — probe record removed")
