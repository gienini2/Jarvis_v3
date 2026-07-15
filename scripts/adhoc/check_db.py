import psycopg2
conn = psycopg2.connect(host="127.0.0.1", port=5432, dbname="jarvis", user="jarvis_user", password="12345")
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
print("TABLAS:", cur.fetchall())
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='memories'")
print("MEMORIES:", cur.fetchall())
cur.close()
conn.close()
