"""
core/code_mode.py
Modo codigo explicito de Jarvis.

El camino normal de chat pasa por el agente de tool-calling, que en
core/llm_router.py fuerza el rol "tools" en CADA mensaje -> el modelo
especializado en codigo (rol "code") nunca llegaba a elegirse. Este handler
detecta peticiones de programar y las enruta por router.chat con intent="code"
(rol "code", SIN tools), asi que:
  - online  -> mejor modelo de codigo de la cascada (Groq qwen3.8-27b, ...)
  - offline -> qwen2.5-coder:7b local (el especializado), no el generalista.

Se invoca desde core/processor.py ANTES que el agente, igual que alpha50.
"""
import logging
import re

from core.llm import generate

log = logging.getLogger("jarvis.code_mode")

# Prefijos explicitos: "/code ...", "codigo: ...", "codea: ..."
_PREFIX = re.compile(r"^\s*(?:/code|c[oó]digo|codea)\s*[:>\-]?\s*", re.I)

# Aperturas naturales inequivocas de "hazme codigo". Ancladas al principio y
# exigen un sustantivo de codigo cerca, para no secuestrar el chat normal.
_NATURAL = re.compile(
    r"^\s*(?:quiero que (?:me )?(?:hagas|programes|codees)|h[aá]zme|"
    r"pr[oó]gr[aá]mame|escr[ií]beme|impl?ement[aá](?:me)?|cr[eé]ame|"
    r"gener[aá](?:me)?)\b.{0,40}\b(?:programa|script|c[oó]digo|funci[oó]n|"
    r"clase|scraper|bot|api|endpoint|consulta sql|query)\b",
    re.I,
)

_CODE_SYSTEM = (
    "Actua en MODO CODIGO. Devuelve codigo correcto, ejecutable y directo, con "
    "comentarios solo donde aporten. Si no conoces DE VERDAD una API, una URL, la "
    "estructura HTML de una web o un dato del mundo real, DILO y deja un TODO en vez "
    "de inventartelo -- vale mas un hueco honesto que codigo plausible pero falso. "
    "Si faltan datos para hacerlo bien, pregunta antes.\n\nPeticion:\n"
)


def is_code_request(message: str) -> bool:
    if not message or not message.strip():
        return False
    return bool(_PREFIX.match(message) or _NATURAL.match(message))


def code_intent_handler(message: str) -> str | None:
    """Respuesta en modo codigo, o None si el mensaje no es una peticion de codigo."""
    if not message or not message.strip():
        return None

    m = _PREFIX.match(message)
    if m:
        body = message[m.end():].strip()
        if not body:
            return (
                "Modo codigo activo. Dime que quieres que programe, p.ej.:\n"
                "  /code una funcion Python que valide un IBAN espanol"
            )
    elif _NATURAL.match(message):
        body = message.strip()
    else:
        return None

    log.info("[code_mode] enrutando por rol=code: %.60s", body)
    return generate(_CODE_SYSTEM + body, intent="code")
