"""Prueba de que una pregunta pendiente de Alpha50 caduca (no se come un 'no' dicho horas despues).
Ejecutar: python tests/test_alpha50_sesion.py     (usa una base temporal, no toca tu cronologia real)
"""
import sqlite3
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "alpha50"))
sys.modules.setdefault("schedule", types.SimpleNamespace())

from alpha50 import scheduler as sch

sch.DB_PATH = str(Path(tempfile.mkdtemp()) / "t.db")
checks = []


def check(name, ok):
    checks.append(ok)
    print(f"  [{'OK' if ok else 'FALLO'}] {name}")


sch._sesion_update(esperando="confirmacion", contexto={})
check("una pregunta reciente sigue pendiente", sch._sesion_get()["esperando"] == "confirmacion")
con = sqlite3.connect(sch.DB_PATH)
con.execute("UPDATE alpha50_sesion SET actualizado = datetime('now','localtime','-3 hours')")
con.commit()
con.close()
check("una pregunta de hace 3 horas ya no cuenta", sch._sesion_get()["esperando"] is None)

for frase in ("no", "a", "hecho", "si", "qué entreno me toca hoy", "hablemos de otra cosa"):
    check(f"'{frase}' ya no lo atiende Alpha50", sch.alpha50_intent_handler(frase) is None)
check("la pregunta pendiente se contesta con /alpha50 (el prefijo lo reconoce)", sch._EXPLICITO.match("/alpha50 hecho").group(1) == "hecho" and sch._EXPLICITO.match("alpha50: a").group(1) == "a")

print(f"\nRESULTADO: {sum(checks)}/{len(checks)} comprobaciones OK")
sys.exit(0 if all(checks) else 1)
