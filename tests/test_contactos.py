"""Prueba del flujo de contactos y envio con confirmacion (core/contacts.py).
Ejecutar: python tests/test_contactos.py
NO envia nada real (Gmail simulado) y NO imprime datos personales; usa contactos reales de la BD.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


contacts._ensure_schema()
start = db("SELECT now()")[0][0]
sent = []
import connectors.google_tools as gt
real_send_email = gt.send_email
gt.send_email = lambda to, subject, body: sent.append((to, subject, body)) or True

person_mail = db("SELECT c.id, c.nombre, k.valor_norm FROM contactos c JOIN canales k ON k.contacto_id = c.id AND k.tipo = 'correo' ORDER BY c.id LIMIT 1")[0]
person_tel = db("SELECT c.id, c.nombre, k.valor_norm FROM contactos c JOIN canales k ON k.contacto_id = c.id AND k.tipo = 'telefono' ORDER BY c.id DESC LIMIT 1")[0]
no_tel = db("SELECT c.id FROM contactos c WHERE NOT EXISTS (SELECT 1 FROM canales k WHERE k.contacto_id = c.id AND k.tipo = 'telefono') LIMIT 1")

print("Busqueda")
res = tools.call_tool("buscar_contacto", {"nombre": person_mail[1]})
check("encuentra a un contacto existente por su nombre", any(r["id"] == person_mail[0] for r in res["encontrados"]))
blob = json.dumps(res, ensure_ascii=False)
check("la respuesta al modelo NO contiene correos ni telefonos", "@" not in blob and not re.search(r"\d{6,}", blob))
check("nombre inexistente -> lista vacia", tools.call_tool("buscar_contacto", {"nombre": "zzzqxw inexistente"})["encontrados"] == [])
check("buscar_contacto y preparar_mensaje estan registradas como tools", {"buscar_contacto", "preparar_mensaje"} <= {t["function"]["name"] for t in tools.TOOLS})

print("Borrador y confirmacion (WhatsApp)")
r = tools.call_tool("preparar_mensaje", {"contacto_id": person_tel[0], "canal": "whatsapp", "texto": "hola, prueba"})
check("prepara borrador pendiente", r.get("estado") == "pendiente_de_confirmacion")
check("nada se envia al preparar", sent == [])
check("un mensaje normal no confirma ni cancela", contacts.handle_confirmation("¿y si cambio el texto?") is None)
out = contacts.handle_confirmation("sí")
check("'sí' devuelve un enlace wa.me con el texto", bool(out) and "https://wa.me/" in out and "text=hola%2C%20prueba" in out)
check("el enlace lleva el numero guardado", bool(out) and person_tel[2].lstrip("+") in out)
check("segundo 'sí' no repite la accion", contacts.handle_confirmation("sí") is None)

print("Correo con confirmacion (Gmail simulado)")
r = tools.call_tool("preparar_mensaje", {"contacto_id": person_mail[0], "canal": "correo", "texto": "cuerpo", "asunto": "asunto"})
check("prepara correo pendiente sin enviarlo", r.get("estado") == "pendiente_de_confirmacion" and sent == [])
out = contacts.handle_confirmation("vale")
check("'vale' envia UNA vez, a la direccion guardada", len(sent) == 1 and sent[0][0] == person_mail[2] and out.startswith("✅"))

print("Cancelar")
sent.clear()
tools.call_tool("preparar_mensaje", {"contacto_id": person_mail[0], "canal": "correo", "texto": "x", "asunto": "y"})
out = contacts.handle_confirmation("no")
check("'no' cancela y no envia", sent == [] and "cancelado" in out.lower())
check("tras cancelar, un 'sí' no envia nada", contacts.handle_confirmation("sí") is None and sent == [])

print("Seguridad")
tools.call_tool("send_email", {"to": "alguien@ejemplo.com", "subject": "s", "body": "b"})
check("send_email del modelo solo deja borrador (no envia)", sent == [])
contacts.handle_confirmation("no")
tools.call_tool("preparar_mensaje", {"contacto_id": person_mail[0], "canal": "correo", "texto": "x", "asunto": "y"})
db("UPDATE acciones_pendientes SET creado = now() - interval '2 hours' WHERE estado = 'pendiente'")
check("un borrador de hace 2 h ha caducado", contacts.handle_confirmation("sí") is None and sent == [])
check("un nuevo borrador sustituye al anterior (solo 1 pendiente)",
      (tools.call_tool("preparar_mensaje", {"contacto_id": person_mail[0], "canal": "correo", "texto": "1", "asunto": "a"}),
       tools.call_tool("preparar_mensaje", {"contacto_id": person_mail[0], "canal": "correo", "texto": "2", "asunto": "b"}),
       db("SELECT count(*) FROM acciones_pendientes WHERE estado = 'pendiente'")[0][0])[2] == 1)
check("contacto sin telefono -> error claro", not no_tel or "error" in tools.call_tool("preparar_mensaje", {"contacto_id": no_tel[0][0], "canal": "whatsapp", "texto": "x"}))
check("canal no soportado -> error", "error" in tools.call_tool("preparar_mensaje", {"contacto_id": person_mail[0], "canal": "telegram", "texto": "x"}))

print("Envio desde tu Gmail")
from config.settings import settings
called = []
gt_get = gt.get_google_service
gt.get_google_service = lambda *a, **k: called.append(1)
old_path, old_flag = settings.GOOGLE_USER_TOKEN_FILE, settings.GOOGLE_EMAIL_FALLBACK_JARVIS
settings.GOOGLE_USER_TOKEN_FILE, settings.GOOGLE_EMAIL_FALLBACK_JARVIS = "config/no_existe_token.json", False
try:
    real_send_email("a@b.com", "s", "b")
    raised = ""
except RuntimeError as e:
    raised = str(e)
check("sin autorizar tu Gmail falla con mensaje claro", "google_autorizar_usuario" in raised)
check("y NO cae a la cuenta de Jarvis por sorpresa", called == [])
settings.GOOGLE_USER_TOKEN_FILE, settings.GOOGLE_EMAIL_FALLBACK_JARVIS = old_path, old_flag
gt.get_google_service = gt_get

db("DELETE FROM acciones_pendientes WHERE creado >= %s", (start,))
print(f"\nRESULTADO: {sum(checks)}/{len(checks)} comprobaciones OK")
sys.exit(0 if all(checks) else 1)
