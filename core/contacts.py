"""Contactos y envio con confirmacion.

El modelo solo ve nombres y TIPOS de canal (nunca telefonos ni correos). Para enviar, prepara un
borrador (acciones_pendientes) y el procesador lo ejecuta unicamente cuando el usuario contesta 'si'.
"""
import difflib
import logging
import re
import unicodedata
import urllib.parse

from core.db import get_connection

log = logging.getLogger("jarvis.contacts")

PENDING_MINUTES = 15
CHANNELS = {"correo": "correo", "whatsapp": "telefono"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS acciones_pendientes (
    id SERIAL PRIMARY KEY,
    creado TIMESTAMPTZ DEFAULT now(),
    tipo TEXT NOT NULL,
    contacto_id INTEGER,
    destino TEXT NOT NULL,
    asunto TEXT,
    texto TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente'
)
"""

YES = re.compile(r"^\W*(s[ií]|vale|ok|okey|dale|adelante|env[ií]alo|m[aá]ndalo|conf[ií]rmo|hazlo|claro|perfecto)(\W+(por favor|gracias))?\W*$", re.I)
NO = re.compile(r"^\W*(no|cancela|cancelar|cancelalo|c[aá]ncelalo|d[eé]jalo|olv[ií]dalo|mejor no|para)\W*$", re.I)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def _query(sql: str, args=(), fetch="all", commit=False):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, args)
        rows = cur.fetchall() if fetch == "all" else cur.fetchone() if fetch == "one" else None
        if commit:
            conn.commit()
        return rows
    finally:
        cur.close()
        conn.close()


def _ensure_schema():
    _query(SCHEMA, fetch=None, commit=True)


def find(name: str, channel: str = "") -> list[dict]:
    wanted = CHANNELS.get(channel.lower(), channel.lower()) if channel else ""
    rows = _query(
        "SELECT c.id, c.nombre, c.empresa, c.busqueda, COALESCE(array_agg(DISTINCT k.tipo) FILTER (WHERE k.tipo IS NOT NULL), '{}') "
        "FROM contactos c LEFT JOIN canales k ON k.contacto_id = c.id GROUP BY c.id"
    )
    query, scored = _norm(name), []
    tokens = query.split()
    if not tokens:
        return []
    for cid, nombre, empresa, busqueda, kinds in rows:
        if wanted and wanted not in kinds:
            continue
        words = busqueda.split()
        hits = sum(1 for t in tokens if any(w.startswith(t) for w in words))
        score = hits / len(tokens)
        if score < 1:
            score = max(score * 0.8, difflib.SequenceMatcher(None, query, busqueda).ratio() * 0.9)
        if score >= 0.6:
            scored.append((score, cid, nombre, empresa, kinds))
    scored.sort(key=lambda s: (-s[0], len(s[2])))
    return [{"id": cid, "nombre": nombre, "empresa": empresa or "", "canales": sorted(kinds), "coincidencia": round(score, 2)}
            for score, cid, nombre, empresa, kinds in scored[:5]]


def buscar_contacto(nombre: str, canal: str = "") -> dict:
    found = find(nombre, canal)
    if not found:
        return {"encontrados": [], "nota": "No hay ningun contacto con ese nombre."}
    return {"encontrados": found,
            "nota": "Si hay varios con coincidencia parecida, pregunta cual. Los numeros y correos NO se muestran: usa preparar_mensaje."}


def _cancel_older():
    _query("UPDATE acciones_pendientes SET estado = 'sustituida' WHERE estado = 'pendiente'", fetch=None, commit=True)


def _store(kind: str, contact_id, dest: str, subject: str, text: str):
    _ensure_schema()
    _cancel_older()
    _query("INSERT INTO acciones_pendientes (tipo, contacto_id, destino, asunto, texto) VALUES (%s,%s,%s,%s,%s)",
           (kind, contact_id, dest, subject or None, text), fetch=None, commit=True)


def preparar_mensaje(contacto_id: int, canal: str, texto: str, asunto: str = "") -> dict:
    channel = canal.lower().strip()
    if channel not in CHANNELS:
        return {"error": f"Canal '{canal}' no soportado. Usa 'correo' o 'whatsapp'."}
    if not texto or not texto.strip():
        return {"error": "Falta el texto del mensaje."}
    person = _query("SELECT nombre FROM contactos WHERE id = %s", (int(contacto_id),), fetch="one")
    if not person:
        return {"error": f"No existe el contacto {contacto_id}. Usa buscar_contacto primero."}
    row = _query("SELECT valor_norm FROM canales WHERE contacto_id = %s AND tipo = %s ORDER BY preferido DESC, id LIMIT 1",
                 (int(contacto_id), CHANNELS[channel]), fetch="one")
    if not row:
        return {"error": f"{person[0]} no tiene {'correo' if channel == 'correo' else 'telefono'} guardado."}
    if channel == "correo" and not asunto.strip():
        return {"error": "Falta el asunto del correo."}
    _store(channel, int(contacto_id), row[0], asunto.strip(), texto.strip())
    return {"estado": "pendiente_de_confirmacion", "para": person[0], "canal": channel, "asunto": asunto.strip(), "texto": texto.strip(),
            "instruccion": "Ensena el borrador al usuario y preguntale si lo envias. NO digas que se ha enviado: solo sale cuando el usuario responde 'si'."}


def preparar_correo_directo(to: str, subject: str, body: str) -> dict:
    _store("correo", None, to.strip(), subject.strip(), body.strip())
    return {"estado": "pendiente_de_confirmacion", "para": to.strip(), "canal": "correo", "asunto": subject.strip(), "texto": body.strip(),
            "instruccion": "Ensena el borrador al usuario y preguntale si lo envias. NO digas que se ha enviado: solo sale cuando el usuario responde 'si'."}


def _execute(action) -> str:
    _, kind, contact_id, dest, subject, text = action
    name = None
    if contact_id:
        row = _query("SELECT nombre FROM contactos WHERE id = %s", (contact_id,), fetch="one")
        name = row[0] if row else None
    label = name or dest
    if kind == "correo":
        from connectors.google_tools import send_email
        send_email(dest, subject or "(sin asunto)", text)
        return f"✅ Correo enviado a {label}."
    digits = re.sub(r"\D", "", dest)
    link = f"https://wa.me/{digits}?text={urllib.parse.quote(text)}"
    return f"📲 Mensaje listo para {label}. Toca el enlace y pulsa enviar en WhatsApp: {link}"


def handle_confirmation(message: str) -> str | None:
    """Si hay un borrador reciente y el usuario responde si/no, lo ejecuta o lo cancela. Si no, None."""
    is_yes, is_no = bool(YES.match(message)), bool(NO.match(message))
    if not (is_yes or is_no):
        return None
    try:
        _ensure_schema()
        action = _query(
            "SELECT id, tipo, contacto_id, destino, asunto, texto FROM acciones_pendientes "
            "WHERE estado = 'pendiente' AND creado > now() - make_interval(mins => %s) ORDER BY id DESC LIMIT 1",
            (PENDING_MINUTES,), fetch="one")
        if not action:
            return None
        new_state = "confirmada" if is_yes else "cancelada"
        _query("UPDATE acciones_pendientes SET estado = %s WHERE id = %s", (new_state, action[0]), fetch=None, commit=True)
        if is_no:
            return "Vale, cancelado. No he enviado nada."
        try:
            return _execute(action)
        except Exception as e:
            log.warning(f"[contacts] fallo al ejecutar la accion {action[0]}: {e}")
            _query("UPDATE acciones_pendientes SET estado = 'fallida' WHERE id = %s", (action[0],), fetch=None, commit=True)
            return f"No he podido enviarlo: {e}"
    except Exception as e:
        log.warning(f"[contacts] confirmacion fallo: {e}")
        return None


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "buscar_contacto",
        "description": ("Busca a una persona en la agenda del usuario por nombre, apodo o empresa. Devuelve id, nombre y los TIPOS de canal "
                        "que tiene (telefono, correo); nunca numeros ni direcciones. Si hay varios parecidos, pregunta cual."),
        "parameters": {"type": "object", "properties": {
            "nombre": {"type": "string", "description": "Nombre, apodo o empresa a buscar"},
            "canal": {"type": "string", "description": "Opcional: 'correo' o 'whatsapp' para filtrar a quien tenga ese canal"}},
            "required": ["nombre"]}}},
    {"type": "function", "function": {
        "name": "preparar_mensaje",
        "description": ("Prepara (NO envia) un mensaje a un contacto por 'correo' o 'whatsapp'. Queda como borrador y solo se envia cuando "
                        "el usuario conteste 'si'. Antes busca al contacto con buscar_contacto para obtener su id."),
        "parameters": {"type": "object", "properties": {
            "contacto_id": {"type": "integer", "description": "id devuelto por buscar_contacto"},
            "canal": {"type": "string", "description": "'correo' o 'whatsapp'"},
            "texto": {"type": "string", "description": "Texto del mensaje"},
            "asunto": {"type": "string", "description": "Asunto (obligatorio solo para correo)"}},
            "required": ["contacto_id", "canal", "texto"]}}},
]
