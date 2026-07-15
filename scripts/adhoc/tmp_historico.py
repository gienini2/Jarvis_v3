import sys, json
sys.path.insert(0, '.')
from core.db import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute("SELECT message, created_at FROM conversations WHERE role='user' ORDER BY id")
rows = cur.fetchall()
with open('historico_juan_pablo.txt', 'w', encoding='utf-8') as f:
    for msg, ts in rows:
        f.write(f"[{ts}] {msg}\n\n")
print(f'{len(rows)} mensajes exportados')
