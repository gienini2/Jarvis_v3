"""Prueba del importador de chats de WhatsApp y de las herramientas de solo fechas.
Ejecutar: python tests/test_whatsapp.py
Usa chats INVENTADOS y dos contactos de prueba (se borran al final). No imprime datos personales.
"""
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import contacts, tools
from core.db import get_connection

checks = []


def check(name, ok):
    checks.append(ok)
    print(f"  [{'OK' if ok else 'FALLO'}] {name}")


def db(sql, args=()):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall() if cur.description else None
    conn.commit()
    cur.close()
    conn.close()
    return rows


def run_import(folder, *extra):
    out = subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "scripts" / "whatsapp_importar.py"), str(folder), *extra],
                         capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    return out.stdout + out.stderr


ids = []
for name in ("ZZ Prueba Alfa", "ZZ Prueba Beta", "ZZ Prueba Gamma"):
    cid = db("INSERT INTO contactos (nombre, busqueda) VALUES (%s, %s) RETURNING id", (name, name.lower()))[0][0]
    ids.append(cid)
alfa, beta, gamma = ids
had_unassigned = (ROOT / "data" / "whatsapp_sin_asignar.csv").exists()

android = (
    "2/12/25, 18:32 - Los mensajes y las llamadas están cifrados de extremo a extremo.\n"
    "2/12/25, 18:31 - Yo Mismo: IMG-20251202-WA0039.jpg (archivo adjunto)\n"
    "2/12/25, 18:32 - ZZ Prueba Alfa: <Multimèdia omès>\n"
    "3/12/25, 11:10 - ZZ Prueba Alfa: hola, ¿quedamos el viernes?\n"
    "3/12/25, 11:12 - Yo Mismo: vale: a las 5\ny llevo yo el pastel\n"
    "3/12/25, 11:13 - ZZ Prueba Alfa: perfecto\n"
)
ios = (
    "‎[24/09/2026, 21:05:12] ZZ Prueba Beta: buenas tardes\n"
    "[24/09/2026, 21:06:01] Yo Mismo: ¡hola! ¿qué tal?\n"
    "[24/09/2026, 9:07:30 p. m.] ZZ Prueba Beta: bien, gracias\n"
)
us = ("[9/24/2026, 9:07:30 PM] ZZ Prueba Gamma: hello\n[9/25/2026, 8:15:00 AM] Yo Mismo: hi there\n"
      "[9/26/2026, 11:59:59 PM] ZZ Prueba Gamma: good night\n")
group = "1/1/26, 10:00 - Ana: hola\n1/1/26, 10:01 - Luis: buenas\n1/1/26, 10:02 - Yo Mismo: qué tal\n"

with tempfile.TemporaryDirectory() as tmp:
    folder = Path(tmp)
    (folder / "Xat de WhatsApp amb ZZ Prueba Alfa.txt").write_text(android, encoding="utf-8")
    with zipfile.ZipFile(folder / "WhatsApp Chat - ZZ Prueba Beta.zip", "w") as z:
        z.writestr("_chat.txt", ios)
    with zipfile.ZipFile(folder / "WhatsApp Chat - ZZ Prueba Gamma.zip", "w") as z:
        z.writestr("_chat.txt", us)
    (folder / "Chat de WhatsApp con Familia Grupo.txt").write_text(group, encoding="utf-8")
    (folder / "Chat de WhatsApp con Qwerty Desconocido Zzz.txt").write_text(android, encoding="utf-8")

    print("Importacion")
    out = run_import(folder, "--yo", "Yo Mismo")
    check("lee los 5 chats, omite 1 grupo y deja 1 sin asignar", "chats leidos: 5" in out and "grupos omitidos: 1" in out and "sin asignar: 1" in out)
    check("cuenta 11 mensajes (5 Android + 3 iPhone + 3 formato EE.UU.), 2 multimedia", "mensajes: 11 (multimedia 2)" in out and "nuevos en BD: 11" in out)
    rows = db("SELECT de_mi, es_multimedia, texto FROM mensajes_chat WHERE contacto_id = %s ORDER BY fecha, id", (alfa,))
    check("Android: 5 mensajes de Alfa (el aviso del sistema no cuenta)", len(rows) == 5)
    check("de_mi correcto (los 'Yo Mismo' son mios, los de Alfa no)", [r[0] for r in rows].count(True) == 2)
    check("detecta adjunto y multimedia omitido", sum(1 for r in rows if r[1]) == 2)
    check("conserva los mensajes de varias lineas", any("\ny llevo yo el pastel" in r[2] for r in rows))
    check("el aviso de cifrado (sistema) no se importa como mensaje", not any("cifrados" in r[2] for r in rows))
    rows_b = db("SELECT fecha, de_mi FROM mensajes_chat WHERE contacto_id = %s ORDER BY fecha", (beta,))
    check("iPhone .zip: 3 mensajes y la hora p. m. se convierte a 21:07", len(rows_b) == 3 and rows_b[-1][0].hour == 21 and rows_b[-1][0].minute == 7)
    out2 = run_import(folder, "--yo", "Yo Mismo")
    rows_g = db("SELECT fecha FROM mensajes_chat WHERE contacto_id = %s ORDER BY fecha", (gamma,))
    check("formato mes/dia: no se descarta ningun mensaje (dia 24/25/26) y las fechas son correctas",
          len(rows_g) == 3 and rows_g[0][0].month == 9 and rows_g[0][0].day == 24 and rows_g[2][0].hour == 23 and "descartadas: 0" in out)
    check("ninguna fecha cae en el futuro", db("SELECT count(*) FROM mensajes_chat WHERE contacto_id = ANY(%s) AND fecha > now()", (ids,))[0][0] == 0)
    check("reimportar no duplica (0 nuevos)", "nuevos en BD: 0" in out2)
    check("los chats sin asignar quedan en un CSV para resolverlos", (ROOT / "data" / "whatsapp_sin_asignar.csv").exists())

print("Herramientas de solo fechas")
res = tools.call_tool("ultimo_contacto", {"nombre": "ZZ Prueba Alfa"})
first = res["resultados"][0]
check("ultimo_contacto devuelve fecha, quien escribio y recuentos", first["ultimo_mensaje"] == "2025-12-03 11:13" and first["lo_ultimo_lo_escribio"] == "la otra persona" and first["mensajes_en_total"] == 5)
check("ultimo_contacto NO devuelve el texto de los mensajes", "pastel" not in str(res) and "quedamos" not in str(res))
res2 = tools.call_tool("contactos_sin_hablar", {"dias": 30, "minimo_mensajes": 5})
check("contactos_sin_hablar lista a Alfa (hace meses, 5 mensajes) y no a Beta (3 mensajes)",
      any(r["id"] == alfa for r in res2["resultados"]) and not any(r["id"] == beta for r in res2["resultados"]))
check("contactos_sin_hablar tampoco devuelve contenido", "pastel" not in str(res2))
check("las dos herramientas estan registradas", {"ultimo_contacto", "contactos_sin_hablar"} <= {t["function"]["name"] for t in tools.TOOLS})

db("DELETE FROM contactos WHERE id = ANY(%s)", (ids,))
if not had_unassigned:
    (ROOT / "data" / "whatsapp_sin_asignar.csv").unlink(missing_ok=True)
print(f"\nRESULTADO: {sum(checks)}/{len(checks)} comprobaciones OK")
sys.exit(0 if all(checks) else 1)
