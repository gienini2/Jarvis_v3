from core.db import get_connection
c = get_connection().cursor()
c.execute("SELECT message, intent_type, COUNT(*) as n FROM intents GROUP BY message, intent_type ORDER BY n DESC LIMIT 30")
for r in c.fetchall(): print(r[2], r[1], '|', r[0][:60])
