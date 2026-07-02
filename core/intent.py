import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.db import get_connection

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    type: str
    task_ref: Optional[str] = None
    project_ref: Optional[str] = None
    payload: dict = field(default_factory=dict)
    confidence: float = 1.0


PROJECT_ALIASES = {
    "dragai": "dragai-tech",
    "drag": "dragai-tech",
    "bitacola": "dragai-tech",
    "bitàcola": "dragai-tech",
    "figaro": "figaro-policial",
    "figaró": "figaro-policial",
    "arboc": "arboc-policial",
    "arboç": "arboc-policial",
    "betatesters": "betatesters",
    "acoso": "acoso-laboral",
    "laboral": "acoso-laboral",
    "juicio": "juicio-pension",
    "pension": "juicio-pension",
    "pensión": "juicio-pension",
    "renta": "declaracion-renta",
    "aeat": "declaracion-renta",
    "mossos": "opos-mossos",
    "castellbisbal": "opos-castellbisbal",
    "mataro": "opos-mataro",
    "mataró": "opos-mataro",
    "prat": "opos-prat",
    "calafell": "opos-calafell",
    "terrassa": "opos-terrassa",
    "delta": "delta",
    "cursos": "cursos-chatgpt",
    "sinergia": "cursos-chatgpt",
    "tingbot": "tingbot",
    "noctorial": "fondeo-noctorial",
    "cft": "fondeo-cft",
    "wsf": "fondeo-wsf",
    "trading": "trading-general",
    "jarvis": "dragai-tech",
    "fondeo": None,
    "opos": None,
}

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_COMPLETE = [
    r"(?:marca[r]?|pon[er]*|marcar)\s+(?:como\s+)?(?:hech[oa]|complet[ao]d[ao]|done|listo|finalizado)\s+(.+)",
    r"(.+?)\s+(?:está|esta|queda|ya\s+(?:está|esta))\s+(?:hech[oa]|complet[ao]d[ao]|done|listo|finalizado|terminad[ao])",
    r"(?:complet[ao]r?|finaliz[ao]r?|cerrar?|done)\s+(.+)",
]

_CREATE = [
    r"(?:recuérdame|recuérdate|recuerda(?:me)?)\s+(.+)",
    r"(?:añade?|agrega?|crea?)\s+(?:una?\s+)?(?:tarea|nota|recordatorio)[:\s]+(.+)",
    r"(?:nueva\s+tarea|nuevo\s+recordatorio)[:\s]+(.+)",
    r"(?:apunta|apúntate)\s+(?:que\s+)?(.+)",
]

_QUERY = [
    r"(?:qué|que)\s+(?:hay|tengo|está|esta|queda)\s+(?:pendiente|en\s+curso|activo)\s+(?:en|para|de|sobre)?\s*(.+)",
    r"(?:estado|status)\s+(?:de[l]?|en)?\s+(.+)",
    r"(?:tareas|pendientes|agenda)\s+(?:de[l]?|en|para)?\s*(.+)",
    r"(?:muéstrame|muestra(?:me)?|ver|dame)\s+(?:las?\s+)?(?:tareas|pendientes)\s+(?:de[l]?|en)?\s*(.+)",
    r"(?:cómo|como)\s+(?:va|está|esta|vamos)\s+(?:con\s+)?(?:lo\s+de\s+)?(.+)",
]

_GOOGLE_GMAIL = [
    r"(?:lee?|muestra|dame|ver)\s+(?:mis?\s+)?(?:correos?|mails?|emails?)",
    r"(?:hay|tienes?)\s+(?:correos?|mails?|emails?)",
    r"(?:envía?|manda?|escribe?)\s+(?:un\s+)?(?:correo|mail|email)\s+(.+)",
    r"(?:busca?)\s+(?:correos?|mails?)\s+(.+)",
    r"(?:manda|mandes|envía|envíes|envia|envies)\s+(?:un\s+)?(?:mail|correo|email)",
]

_GOOGLE_CALENDAR = [
    r"(?:qué|que)\s+(?:tengo|hay)\s+(?:hoy|mañana|esta\s+semana|el\s+lunes|el\s+martes|el\s+miércoles|el\s+jueves|el\s+viernes)",
    r"(?:crea?|añade?|agrega?)\s+(?:un\s+)?(?:evento|cita|reunión)\s+(.+)",
    r"(?:mi\s+)?(?:agenda|calendario)\s+(?:de\s+)?(?:hoy|mañana|esta\s+semana)?",
]

_GOOGLE_DRIVE = [
    r"(?:busca?|encuentra?|dame?)\s+(?:el\s+|la\s+|un\s+|una\s+)?(?:archivo|documento|fichero|doc)\s+(.+)",
    r"(?:qué|que)\s+(?:archivos?|documentos?)\s+(?:tengo|hay)\s+(?:en\s+drive)?",
    r"(?:lista?|muestra?)\s+(?:mis?\s+)?(?:archivos?|documentos?)\s+(?:de\s+drive)?",
]

_MANDO_ADD = [
    r"(?:añade?|agrega?|crea?|apunta)\s+(?:una?\s+)?tarea\s+(?:en|al?|para)\s+(?:proyecto\s+)?(.+?)[:\s]+(.+)",
    r"(?:añade?|agrega?)\s+(?:al?\s+)?(?:proyecto\s+)?(.+?)\s+(?:la\s+tarea|una\s+tarea)[:\s]+(.+)",
    r"(?:nueva\s+tarea)\s+(?:en|para|al?)\s+(.+?)[:\s]+(.+)",
    r"(?:en|al?)\s+(?:proyecto\s+)?(.+?)\s+añad[ei][r]?\s+(.+)",
]

_MANDO_UPDATE = [
    r"(?:modifica?|cambia?|actualiza?|edita?)\s+(?:la\s+)?tarea\s+(.+?)\s+(?:de[l]?\s+proyecto\s+)?(.+?)(?:\s+a\s+|\s*:\s*)(.+)",
    r"(?:renombra?)\s+(?:la\s+)?tarea\s+(.+?)\s+(?:a|por|como)\s+(.+)",
    r"(?:cambia?|pon[er]*)\s+(?:la\s+)?prioridad\s+(?:de\s+)?(.+?)\s+a\s+(alta?|media?|baja?|high|mid|low)",
]

_MANDO_DELETE = [
    r"(?:elimina?|borra?|quita?|remove?)\s+(?:la\s+)?tarea\s+(.+?)(?:\s+del?\s+(?:proyecto\s+)?(.+))?$",
    r"(?:borra?|elimina?)\s+(?:del?\s+)?(?:proyecto\s+)?(.+?)\s+(?:la\s+tarea\s+)?(.+)",
]

_AUDIT = [
    r"(?:audita?|analiza?|revisa?)\s+(?:el\s+)?(?:repo|repositorio|proyecto|código)\s+(.+)",
    r"(?:audita?|analiza?)\s+(.+)",
    r"(?:pasa[r]?\s+(?:el\s+)?auditor\s+(?:a|por|en))\s+(.+)",
    r"(?:qué\s+(?:tal\s+)?está|cómo\s+está)\s+(?:el\s+código\s+de\s+)?(.+)",
]
_REMOTE_AUDIT = [
    r"audita(?:me)?\s+(.+?)\s+en\s+figaro",
    r"audita(?:me)?\s+(?:el\s+)?(?:proyecto\s+)?(.+?)\s+(?:de|en)\s+(?:fígaro|figaro|el\s+servidor)",
    r"revisa(?:me)?\s+(?:el\s+código\s+de\s+)?(.+?)\s+en\s+figaro",
    r"analiza(?:me)?\s+(.+?)\s+en\s+figaro",
]

# Búsqueda en memoria histórica
_MEMORY_SEARCH = [
    # Específicos con "chat/conversacion" — VAN PRIMERO
    r"busca(?:me)?\s+chats?\s+(?:que\s+)?(?:contengan?|sobre|de|con)\s+([^,]+)",
    r"busca(?:me)?\s+(?:conversaciones?|chats?|historial)\s+(?:de|sobre|con)?\s*([^,]+)",
    r"busca\s+(?:en\s+)?chats?\s+(?:sobre|de|acerca\s+de)?\s*([^,]+)",
    r"busca\s+([^,]+)\s+en\s+(?:mis?\s+)?chats?",
    r"(?:busca?|encuentra?|revisa?)\s+(?:en\s+)?(?:chats?|conversaciones?|historial|memoria)\s+(?:sobre\s+|de\s+)?([^,]+)",
    # Temporales
    r"(?:hablamos|comentamos|dijiste|vimos)\s+(?:sobre\s+|de\s+)?(.+?)\s+(?:la\s+semana|ayer|el\s+otro\s+día|hace)",
    r"(?:cuándo|cuando)\s+(?:hablamos|comentamos|dijiste)\s+(?:de\s+|sobre\s+)?(.+)",
    # Genéricos — VAN AL FINAL
    r"(?:recuerdas?|te\s+acuerdas?)\s+(?:de\s+|cuando\s+|lo\s+de\s+)?(.+)",
    r"(?:qué|que)\s+(?:hablamos|dijiste|comentamos|discutimos)\s+(?:sobre|de|acerca\s+de)?\s*(.+)",
    r"(?:qué|que)\s+(?:sé|sabes|sabemos)\s+(?:sobre|de)\s+(.+)",
    r"(?:mira|dime|muestra(?:me)?)\s+(?:de\s+cuando\s+son|cuando\s+(?:fue|hablamos))\s+(?:los?\s+chats?\s+(?:de|sobre)\s+)?(.+)",
]

def _load_repo_aliases() -> dict[str, str]:
    path = Path(__file__).parent.parent / "config" / "repo_aliases.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

_REPO_ALIASES: dict[str, str] = _load_repo_aliases()
# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify(message: str) -> Intent:
    msg = message.strip()

    # ── ML primero ──────────────────────────────────────────────────────────
    try:
        from core.intent_ml import predict
        ml_intent, ml_confidence = predict(msg)
        if ml_confidence >= 0.75 and ml_intent != "general":
            return _build_intent(ml_intent, msg)
    except Exception:
        pass

    # ── Regex como fallback ─────────────────────────────────────────────────
    for pattern in _COMPLETE:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            return Intent(type="complete_task", task_ref=m.group(1).strip(), confidence=0.9)

    for pattern in _CREATE:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            return Intent(type="create_task", payload={"text": m.group(1).strip()}, confidence=0.9)

    for pattern in _QUERY:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().rstrip("?.,!")
            project_id = _resolve_project(raw)
            return Intent(type="query_task", project_ref=project_id or raw, confidence=0.85)

    for pattern in _GOOGLE_GMAIL:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            return Intent(type="google_gmail", payload={"text": msg}, confidence=0.9)

    for pattern in _GOOGLE_CALENDAR:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            return Intent(type="google_calendar", payload={"text": msg}, confidence=0.9)

    for pattern in _GOOGLE_DRIVE:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            return Intent(type="google_drive", payload={"text": msg}, confidence=0.9)

    for pattern in _MANDO_ADD:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            project_raw = m.group(1).strip()
            task_text   = m.group(2).strip()
            project_id  = _resolve_project(project_raw) or project_raw
            return Intent(
                type="mando_add_task",
                project_ref=project_id,
                payload={"text": task_text, "priority": _infer_priority(msg)},
                confidence=0.9,
            )

    for i, pattern in enumerate(_MANDO_UPDATE):
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            if i == 2:  # "cambia la prioridad de X a alta/media/baja"
                task_ref = m.group(1).strip().rstrip("?.,!")
                priority = _normalize_priority(m.group(2).strip())
                return Intent(type="mando_update_task", task_ref=task_ref, payload={"priority": priority}, confidence=0.85)
            if i == 1:  # "renombra la tarea X a/por/como Y"
                task_ref = m.group(1).strip().rstrip("?.,!")
                new_text = m.group(2).strip()
                return Intent(type="mando_update_task", task_ref=task_ref, payload={"text": new_text}, confidence=0.85)
            # i == 0: "modifica/cambia/actualiza/edita la tarea X [del proyecto Y] a/: Z"
            task_ref = m.group(1).strip().rstrip("?.,!")
            new_text = m.group(3).strip()
            return Intent(type="mando_update_task", task_ref=task_ref, payload={"text": new_text}, confidence=0.85)

    for i, pattern in enumerate(_MANDO_DELETE):
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            if i == 0:
                task_ref = m.group(1).strip().rstrip("?.,!")
                project_raw = (m.group(2) or "").strip() if m.lastindex and m.lastindex >= 2 else ""
            else:
                project_raw = m.group(1).strip()
                task_ref = m.group(2).strip().rstrip("?.,!")
            project_id = _resolve_project(project_raw) if project_raw else None
            return Intent(type="mando_delete_task", task_ref=task_ref, project_ref=project_id, confidence=0.85)
    for pattern in _REMOTE_AUDIT:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            project = m.group(1).strip().rstrip("?.,!")
            return Intent(type="remote_audit", payload={"project": project}, confidence=0.9)
    for pattern in _AUDIT:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            repo_raw = m.group(1).strip().rstrip("?.,!")
            repo_path = _REPO_ALIASES.get(repo_raw.lower(), repo_raw)
            return Intent(type="audit", payload={"path": repo_path}, confidence=0.85)

    for pattern in _MEMORY_SEARCH:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            query = m.group(1).strip().rstrip("?.,!")
            return Intent(type="memory_search", payload={"query": query}, confidence=0.9)

    # ML de baja confianza como último recurso
    try:
        from core.intent_ml import predict
        ml_intent, _ = predict(msg)
        if ml_intent != "general":
            return _build_intent(ml_intent, msg)
    except Exception:
        pass

    return Intent(type="general", confidence=1.0)


def _build_intent(intent_type: str, msg: str) -> Intent:
    """Construye un Intent a partir del tipo ML, extrayendo payload básico."""
    if intent_type == "audit":
        for pattern in _AUDIT:
            m = re.search(pattern, msg, re.IGNORECASE)
            if m:
                repo_raw = m.group(1).strip().rstrip("?.,!")
                repo_path = _REPO_ALIASES.get(repo_raw.lower(), repo_raw)
                return Intent(type="audit", payload={"path": repo_path}, confidence=0.75)
        # Sin ruta clara -> no lanzar auditor
        return Intent(type="general", confidence=0.5)

    if intent_type == "memory_search":
        # Limpiar palabras de búsqueda para extraer query
        import re as _re
        query = _re.sub(
            r"(?:comprueba|busca(?:me)?|encuentra|revisa|conversaciones?|chats?|historial|memoria|anteriores?|que\s+hablen?\s+de|puedes\s+mirar|tienes\s+algo\s+sobre)\s*",
            " ", msg, flags=_re.IGNORECASE
        ).strip()
        return Intent(type="memory_search", payload={"query": query or msg}, confidence=0.75)

    if intent_type == "google_calendar":
        return Intent(type="google_calendar", payload={"text": msg}, confidence=0.75)

    if intent_type == "google_gmail":
        return Intent(type="google_gmail", payload={"text": msg}, confidence=0.75)

    if intent_type == "google_drive":
        return Intent(type="google_drive", payload={"text": msg}, confidence=0.75)

    if intent_type == "query_task":
        return Intent(type="query_task", project_ref=msg, confidence=0.6)

    if intent_type == "complete_task":
        return Intent(type="complete_task", task_ref=msg, confidence=0.6)

    if intent_type == "remote_audit":
        return Intent(type="remote_audit", payload={"project": msg}, confidence=0.6)

    if intent_type in ("mando_update_task", "mando_delete_task"):
        # El ML solo da la etiqueta, no los grupos -- reusar el parseo regex.
        patterns = _MANDO_UPDATE if intent_type == "mando_update_task" else _MANDO_DELETE
        for i, pattern in enumerate(patterns):
            m = re.search(pattern, msg, re.IGNORECASE)
            if m:
                if intent_type == "mando_update_task":
                    if i == 2:
                        return Intent(type=intent_type, task_ref=m.group(1).strip().rstrip("?.,!"),
                                      payload={"priority": _normalize_priority(m.group(2))}, confidence=0.6)
                    if i == 1:
                        return Intent(type=intent_type, task_ref=m.group(1).strip().rstrip("?.,!"),
                                      payload={"text": m.group(2).strip()}, confidence=0.6)
                    return Intent(type=intent_type, task_ref=m.group(1).strip().rstrip("?.,!"),
                                  payload={"text": m.group(3).strip()}, confidence=0.6)
                else:
                    if i == 0:
                        task_ref = m.group(1).strip().rstrip("?.,!")
                        project_raw = (m.group(2) or "").strip() if m.lastindex and m.lastindex >= 2 else ""
                    else:
                        project_raw = m.group(1).strip()
                        task_ref = m.group(2).strip().rstrip("?.,!")
                    return Intent(type=intent_type, task_ref=task_ref,
                                  project_ref=_resolve_project(project_raw) if project_raw else None, confidence=0.6)
        # Sin match claro -> no ejecutar a ciegas
        return Intent(type="general", confidence=0.5)

    return Intent(type=intent_type, payload={"text": msg}, confidence=0.7)

def _resolve_project(raw: str) -> Optional[str]:
    key = raw.lower().strip()
    return PROJECT_ALIASES.get(key)


def _normalize_priority(raw: str) -> str:
    raw = raw.lower().strip()
    if raw in ("alta", "high"):
        return "high"
    if raw in ("baja", "low"):
        return "low"
    return "mid"


def _infer_priority(msg: str) -> str:
    msg_lower = msg.lower()
    if any(w in msg_lower for w in ["urgente", "alta", "crítico", "crítica", "high"]):
        return "high"
    if any(w in msg_lower for w in ["baja", "low", "cuando pueda"]):
        return "low"
    return "mid"


# ---------------------------------------------------------------------------
# Intent log
# ---------------------------------------------------------------------------

def log_intent(message: str, intent_type: str, payload: dict = None, executed: bool = False):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO intents (message, intent_type, payload, executed)
        VALUES (%s, %s, %s, %s)
        """,
        (message, intent_type, json.dumps(payload) if payload else None, executed),
    )
    conn.commit()
    cur.close()
    conn.close()
