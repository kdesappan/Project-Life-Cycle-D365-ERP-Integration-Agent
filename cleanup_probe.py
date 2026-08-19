"""Delete the probe customer created during mandatory-field discovery."""
from dotenv import load_dotenv
load_dotenv()
from backend.services.d365_client import build_client_from_env
import httpx

c = build_client_from_env()
c.preflight_auth()
acc = "C00001361"
url = f"{c.base_url}/CustomersV3(dataAreaId='{c.data_area_id}',CustomerAccount='{acc}')"
resp = httpx.delete(url, headers=c._headers(), params={"cross-company": "true"}, timeout=60)
print(f"DELETE HTTP {resp.status_code} — probe record removed")
