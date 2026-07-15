import sys
sys.path.insert(0, '.')
from core.db import get_connection
c = get_connection().cursor()
c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='conversations'")
print(c.fetchall())
