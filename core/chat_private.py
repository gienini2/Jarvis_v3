"""Herramientas PRIVADAS sobre los chats de WhatsApp importados: resumir un chat y redactar como el usuario.

Devuelven contenido de chats, asi que marcan el turno como privado ("_privado"): desde ahi solo responde el modelo local
y nada se guarda (core/privacy.py). El estilo se aprende solo de los mensajes del propio usuario (indice scripts/indexar_estilo.py).
"""
import logging
import re
from collections import Counter

from core import contacts
from core.rag import _to_vector_literal, embed

log = logging.getLogger("jarvis.chat_private")

MAX_CHARS = 4500
NO_CHATS = {"nota": "Todavia no hay chats de WhatsApp importados de esa persona (scripts/whatsapp_importar.py)."}


def _person(nombre: str):
    found = contacts.find(nombre)
    if not found:
        return None, {"nota": "No hay ningun contacto con ese nombre."}
    if len(found) > 1 and contacts._norm(found[0]["nombre"]) != contacts._norm(nombre):
        return None, {"varios": [f["nombre"] for f in found[:5]], "nota": "Hay varios parecidos: pregunta a cual se refiere."}
    return found[0], None


def _fit(lines: list[str]) -> str:
    """Las lineas mas recientes que caben en MAX_CHARS, en orden cronologico."""
    out, size = [], 0
    for line in reversed(lines):
        size += len(line) + 1
        if size > MAX_CHARS:
            break
        out.append(line)
    return "\n".join(reversed(out))


def _line(row, name: str) -> str:
    return f"{row[0].strftime('%d/%m %H:%M')} {'Yo' if row[1] else name}: {row[2][:300]}"


def resumir_chat(nombre: str, dias: int = 30) -> dict:
    person, problem = _person(nombre)
    if problem:
        return problem
    dias = max(1, min(int(dias), 365))
    rows = contacts._query("SELECT fecha, de_mi, texto FROM mensajes_chat WHERE contacto_id = %s AND NOT es_multimedia "
                           "AND fecha > now() - make_interval(days => %s) ORDER BY fecha", (person["id"], dias))
    ventana = f"ultimos {dias} dias"
    if not rows:
        rows = list(reversed(contacts._query("SELECT fecha, de_mi, texto FROM mensajes_chat WHERE contacto_id = %s AND NOT es_multimedia "
                                             "ORDER BY fecha DESC LIMIT 150", (person["id"],))))
        ventana = "ultimos mensajes (no hay nada en esa ventana)"
    if not rows:
        return NO_CHATS
    return {"_privado": True, "persona": person["nombre"], "ventana": ventana, "mensajes": len(rows),
            "chat": _fit([_line(r, person["nombre"]) for r in rows]),
            "instruccion": "Resume la conversacion en pocos puntos: de que habeis hablado, que quedo pendiente y el tono. No copies mensajes literales largos."}


def _similar_mine(intent: str, limit: int = 8) -> list[str]:
    vector = embed(intent)
    if not vector:
        return []
    try:
        rows = contacts._query("SELECT m.texto FROM estilo_mensajes e JOIN mensajes_chat m ON m.id = e.mensaje_id "
                               "ORDER BY e.embedding <=> %s::vector LIMIT %s", (_to_vector_literal(vector), limit))
    except Exception as e:
        log.warning(f"[chat_private] sin indice de estilo: {e}")
        return []
    return [r[0][:200] for r in rows]


EMOJI = re.compile("[🌀-🫿☀-➿]")


def rasgos_de_estilo(person_id: int) -> dict:
    """Rasgos medidos de como escribe el usuario (con esta persona y en general): solo agregados, nunca mensajes."""
    rows = contacts._query("SELECT texto FROM mensajes_chat WHERE contacto_id = %s AND de_mi AND NOT es_multimedia ORDER BY fecha DESC LIMIT 1500", (person_id,))
    if len(rows) < 30:
        rows = contacts._query("SELECT texto FROM mensajes_chat WHERE de_mi AND NOT es_multimedia ORDER BY fecha DESC LIMIT 3000")
    texts = [r[0].strip() for r in rows if r[0].strip()]
    if not texts:
        return {}
    first_words = Counter(t.split()[0].lower().strip(",.!?¡¿") for t in texts)
    pct = lambda n: f"{round(100 * n / len(texts))}%"
    return {"longitud_media_caracteres": round(sum(map(len, texts)) / len(texts)),
            "con_emojis": pct(sum(bool(EMOJI.search(t)) for t in texts)),
            "empieza_en_minuscula": pct(sum(t[0].islower() for t in texts)),
            "sin_punto_final": pct(sum(t[-1] not in ".!?" for t in texts)),
            "con_jaja": pct(sum("jaj" in t.lower() for t in texts)),
            "suele_empezar_con": [w for w, _ in first_words.most_common(8) if w]}


def redactar_como_yo(nombre: str, intencion: str = "") -> dict:
    person, problem = _person(nombre)
    if problem:
        return problem
    last = list(reversed(contacts._query("SELECT fecha, de_mi, texto FROM mensajes_chat WHERE contacto_id = %s AND NOT es_multimedia "
                                         "ORDER BY fecha DESC LIMIT 10", (person["id"],))))
    mine = [r[0][:200] for r in contacts._query("SELECT texto FROM mensajes_chat WHERE contacto_id = %s AND de_mi AND NOT es_multimedia "
                                                "AND length(texto) >= 12 ORDER BY fecha DESC LIMIT 12", (person["id"],))]
    if not last and not mine:
        return NO_CHATS
    intencion = intencion.strip() or "responder al ultimo mensaje de la otra persona como lo haria yo"
    return {"_privado": True, "persona": person["nombre"], "contacto_id": person["id"], "intencion": intencion, "rasgos_de_mi_estilo": rasgos_de_estilo(person["id"]),
            "ultimos_mensajes": "\n".join(_line(r, person["nombre"]) for r in last),
            "como_le_escribo": mine, "como_escribo_en_situaciones_parecidas": _similar_mine(intencion),
            "instruccion": ("Redacta UN borrador corto con mi forma de escribir (mira los ejemplos: longitud, tono, emojis, abreviaturas, tuteo), "
                            "que cumpla la intencion (si es responder, contesta al ultimo mensaje de la otra persona) y encaje con la conversacion reciente. Ensenalo y pregunta si lo preparo; "
                            "si lo aprueba usa preparar_mensaje con este contacto_id. No cites los ejemplos.")}


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "resumir_chat",
        "description": ("Resume tu conversacion de WhatsApp con una persona de la agenda (ultimos dias). Lee el chat de forma privada: "
                        "el resto de la respuesta la da el modelo local y no se guarda."),
        "parameters": {"type": "object", "properties": {
            "nombre": {"type": "string", "description": "Nombre, apodo o empresa de la persona"},
            "dias": {"type": "integer", "description": "Dias hacia atras (por defecto 30)"}}, "required": ["nombre"]}}},
    {"type": "function", "function": {
        "name": "redactar_como_yo",
        "description": ("Prepara un mensaje, o la respuesta al ultimo mensaje recibido, escrito como lo escribe el usuario (aprende de sus propios chats). Lee chats de forma "
                        "privada: lo redacta el modelo local. Para enviarlo despues se usa preparar_mensaje."),
        "parameters": {"type": "object", "properties": {
            "nombre": {"type": "string", "description": "Nombre, apodo o empresa de la persona"},
            "intencion": {"type": "string", "description": "Que quiere decir el usuario (ej. 'quedar el sabado'). Vacio = responder al ultimo mensaje que le llego"}},
            "required": ["nombre"]}}},
]
