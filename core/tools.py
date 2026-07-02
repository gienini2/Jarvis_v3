"""
core/tools.py
Registro de herramientas para el tool-calling loop (core/agent.py).

Fase 1 (ADR-0001): herramientas de lectura -- query_tasks, search_memory, Gmail,
Calendar, Drive, start_audit. No modifican nada.

Fase 2 (ADR-0001): herramientas de escritura sobre el Centro de Mando --
add_task, update_task, delete_task. Cada una valida contra datos reales antes
de ejecutar (resuelve el proyecto/tarea primero) en vez de confiar ciegamente
en lo que el LLM cree que existe. Si hay ambiguedad (varias tareas coinciden,
o el proyecto no se reconoce), la tool devuelve la lista de candidatos como
error para que el LLM se lo pregunte a Juan Pablo en vez de adivinar.

Fase 3 (autonomia sobre el propio codigo de Jarvis) todavia no esta aqui.
"""
from core.tasks import find_tasks_by_project, find_tasks_by_keyword, sync_tasks_from_json
from core.rag import search_memories
from connectors.google_tools import (
    get_recent_emails,
    search_emails,
    get_upcoming_events,
    list_drive_files,
    search_drive_files,
)
from connectors.mando_tasks import (
    add_task as _mando_add_task,
    update_task as _mando_update_task,
    delete_task as _mando_delete_task,
    find_project_id,
)

# ---------------------------------------------------------------------------
# Schemas (formato tools de OpenAI/NVIDIA/Ollama)
# NOTA: sin la clave "default" en los schemas -- Ollama /api/chat devuelve
# 400 Bad Request con algunos JSON schemas que la incluyen. Los defaults
# reales viven en las firmas de las funciones Python de abajo.
# ---------------------------------------------------------------------------

TOOLS = [
    # ---- Fase 1: solo lectura ------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "query_tasks",
            "description": (
                "Consulta tareas pendientes del Centro de Mando por proyecto y/o palabra "
                "clave. Solo lectura, no modifica nada. Usar cuando el usuario pregunte "
                "que tiene pendiente, en que proyecto, o busque una tarea concreta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Nombre o id del proyecto, ej. 'tingbot', 'jarvis', 'bitacola'. Vacio si no aplica.",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Palabra clave a buscar en el texto de la tarea. Vacio si no aplica.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Busca en el historial de conversaciones pasadas de Juan Pablo (PostgreSQL "
                "+ embeddings). Usar cuando pregunte 'de que hablamos', 'recuerdas cuando', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Que buscar en la memoria"},
                    "limit": {"type": "integer", "description": "Maximo de resultados, por defecto 10 si se omite"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_emails",
            "description": "Lista los correos mas recientes de Gmail. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "por defecto 5 si se omite"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_gmail",
            "description": "Busca correos en Gmail por texto. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto a buscar"},
                    "max_results": {"type": "integer", "description": "por defecto 5 si se omite"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_calendar_events",
            "description": "Lista los proximos eventos de Google Calendar. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "por defecto 10 si se omite"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files_drive",
            "description": "Busca archivos en Google Drive por nombre. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto a buscar en el nombre del archivo"},
                    "max_results": {"type": "integer", "description": "por defecto 10 si se omite"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_audit",
            "description": (
                "Lanza una auditoria de codigo sobre un repositorio local. Es asincrono: "
                "devuelve un job_id, el resultado llega despues por Telegram. No modifica "
                "el repositorio auditado, solo lo analiza."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta absoluta del repositorio a auditar"},
                },
                "required": ["path"],
            },
        },
    },
    # ---- Fase 2: escritura sobre Centro de Mando -----------------------------
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": (
                "Anade una tarea nueva a un proyecto del Centro de Mando. Usar cuando "
                "el usuario pida crear/anadir/apuntar una tarea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Nombre o id del proyecto, ej. 'tingbot', 'jarvis'"},
                    "text": {"type": "string", "description": "Texto de la tarea"},
                    "priority": {"type": "string", "description": "'high', 'mid' o 'low'. Si no se sabe, usar 'mid'."},
                },
                "required": ["project", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": (
                "Modifica el texto y/o la prioridad de una tarea existente. Se identifica "
                "la tarea por una palabra clave de su texto actual, no por indice. Si hay "
                "varias tareas que coinciden, la herramienta devuelve la lista para que "
                "se lo preguntes a Juan Pablo en vez de adivinar cual es."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ref": {"type": "string", "description": "Palabra clave que identifica la tarea a modificar"},
                    "text": {"type": "string", "description": "Nuevo texto de la tarea. Omitir si no cambia."},
                    "priority": {"type": "string", "description": "Nueva prioridad: 'high', 'mid' o 'low'. Omitir si no cambia."},
                },
                "required": ["task_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": (
                "Elimina una tarea existente. Se identifica por una palabra clave de su "
                "texto, no por indice. Si hay varias coincidencias, devuelve la lista en "
                "vez de borrar la que no toca."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ref": {"type": "string", "description": "Palabra clave que identifica la tarea a eliminar"},
                },
                "required": ["task_ref"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Implementaciones -- Fase 1 (envuelven funciones ya existentes, solo lectura)
# ---------------------------------------------------------------------------


def query_tasks(project: str = "", keyword: str = "") -> list[dict]:
    if project:
        tasks = find_tasks_by_project(project)
        if tasks:
            return tasks
    if keyword:
        return find_tasks_by_keyword(keyword)
    return []


def search_memory(query: str, limit: int = 10) -> list[dict]:
    return search_memories(query, limit=limit)


def list_recent_emails(max_results: int = 5) -> list[dict]:
    return get_recent_emails(max_results)


def search_gmail(query: str, max_results: int = 5) -> list[dict]:
    return search_emails(query, max_results)


def list_calendar_events(max_results: int = 10) -> list[dict]:
    return get_upcoming_events(max_results)


def search_files_drive(query: str, max_results: int = 10) -> list[dict]:
    return search_drive_files(query, max_results)


def start_audit(path: str) -> dict:
    from auditor.runner import start_audit_thread
    job_id = start_audit_thread(path)
    return {"job_id": job_id, "path": path, "status": "started"}


# ---------------------------------------------------------------------------
# Implementaciones -- Fase 2 (escritura, con validacion antes de ejecutar)
# ---------------------------------------------------------------------------


def _resolve_single_task(task_ref: str) -> dict:
    """Busca la tarea por keyword. Lanza ValueError con la lista de candidatos
    si hay 0 o mas de 1 -- el llamador debe convertir eso en un resultado que
    el LLM pueda leer y usar para preguntar, no para adivinar."""
    matches = find_tasks_by_keyword(task_ref)
    if not matches:
        raise ValueError(f"No encontre ninguna tarea pendiente con '{task_ref}'.")
    if len(matches) > 1:
        opciones = [f"[{m['priority']}] {m['project']} -- {m['title']}" for m in matches[:5]]
        raise ValueError(
            f"Hay {len(matches)} tareas que coinciden con '{task_ref}', hace falta mas "
            f"detalle para saber cual: " + " | ".join(opciones)
        )
    return matches[0]


def add_task(project: str, text: str, priority: str = "mid") -> dict:
    if priority not in ("high", "mid", "low"):
        priority = "mid"
    project_id = project
    if not any(c in project_id for c in ["-", "_"]):
        resolved = find_project_id(project_id)
        if not resolved:
            return {"error": f"No reconozco el proyecto '{project}'. Dime el nombre exacto del Centro de Mando."}
        project_id = resolved
    result = _mando_add_task(project_id, text, priority)
    sync_tasks_from_json()
    return {"ok": True, "project_id": project_id, "text": text, "priority": priority, "mando_key": result.get("mando_key")}


def update_task(task_ref: str, text: str = None, priority: str = None) -> dict:
    if not text and not priority:
        return {"error": "No hay nada que cambiar -- falta el nuevo texto o la nueva prioridad."}
    try:
        t = _resolve_single_task(task_ref)
    except ValueError as e:
        return {"error": str(e)}
    if priority and priority not in ("high", "mid", "low"):
        priority = None
    project_id, idx = t["mando_key"].rsplit("_", 1)
    _mando_update_task(project_id, int(idx), text=text, priority=priority)
    sync_tasks_from_json()
    return {"ok": True, "titulo_anterior": t["title"], "nuevo_texto": text, "nueva_prioridad": priority}


def delete_task(task_ref: str) -> dict:
    try:
        t = _resolve_single_task(task_ref)
    except ValueError as e:
        return {"error": str(e)}
    project_id, idx = t["mando_key"].rsplit("_", 1)
    _mando_delete_task(project_id, int(idx))
    sync_tasks_from_json()
    return {"ok": True, "eliminada": t["title"], "project": t["project"]}


FUNCTIONS = {
    "query_tasks": query_tasks,
    "search_memory": search_memory,
    "list_recent_emails": list_recent_emails,
    "search_gmail": search_gmail,
    "list_calendar_events": list_calendar_events,
    "search_files_drive": search_files_drive,
    "start_audit": start_audit,
    "add_task": add_task,
    "update_task": update_task,
    "delete_task": delete_task,
}


def call_tool(name: str, arguments: dict):
    """Ejecuta una tool por nombre. Nunca lanza excepcion -- el error vuelve como
    resultado para que el LLM lo vea y pueda reaccionar (reintentar, pedir mas info, etc)."""
    fn = FUNCTIONS.get(name)
    if not fn:
        return {"error": f"Herramienta desconocida: {name}"}
    try:
        return fn(**arguments)
    except Exception as e:
        return {"error": str(e)}
