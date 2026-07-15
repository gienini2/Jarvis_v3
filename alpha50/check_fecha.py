"""Uso: python check_fecha.py [YYYY-MM-DD]  (por defecto: ayer)"""
import sqlite3
import sys
from datetime import date, timedelta

fecha = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).isoformat()

con = sqlite3.connect("alpha50_cronologia.db")
con.row_factory = sqlite3.Row
row = con.execute("SELECT * FROM historial_dias WHERE fecha=?", (fecha,)).fetchone()
con.close()

if row:
    print(f"Registro para {fecha}:")
    for k in row.keys():
        print(f"  {k}: {row[k]}")
else:
    print(f"Sin registro para {fecha} -- no se llegó a guardar (registrar_dia() no se ejecutó ese día).")
