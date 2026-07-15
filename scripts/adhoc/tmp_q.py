import requests
from config.settings import settings
r = requests.get(f'{settings.RELAY_URL}/queue/pending', timeout=5)
msgs = r.json()
print(f'{len(msgs)} mensajes pendientes')
for m in msgs:
    print(m.get('id'), '|', str(m.get('message',''))[:60])
