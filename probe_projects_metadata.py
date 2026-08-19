from dotenv import load_dotenv
import re
from backend.services.d365_client import build_client_from_env

load_dotenv()
c = build_client_from_env()
print('auth', c.preflight_auth())
s, b = c.get('/$metadata')
xml = (b or {}).get('raw', '')

sets = re.findall(r'EntitySet Name="([^"]+)" EntityType="Microsoft\.Dynamics\.DataEntities\.([^"]+)"', xml)
for es, et in sets:
    if es == 'ProjectsV2' or 'ProjectsV2' in es or et == 'ProjectV2':
        print('SET', es, 'TYPE', et)

for et in ['ProjectV2', 'Project', 'ProjectV3']:
    m = re.search(rf'EntityType Name="{re.escape(et)}">(.*?)</EntityType>', xml, flags=re.S)
    if not m:
        continue
    props = re.findall(r'Property Name="([^"]+)"', m.group(1))
    print('\n', et, len(props))
    print(props)
