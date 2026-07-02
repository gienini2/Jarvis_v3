"""
core/tools.py
Registro de herramientas para el tool-calling loop (core/agent.py).

Fase 1 de ADR-0001 (docs/adr/0001-tool-calling-architecture.md): SOLO herramientas
de lectura / bajo riesgo. Ninguna función de aquí escribe en el Centro de Mando,
en Google, ni en el propio código de Jarvis. Cada tool envuelve una función que
ya existía en el proyecto -- no se reescribe lógica de negocio, solo se expone
con un schema para que el LLM la pueda elegir.

Fase 2 (escritura sobre Centro de Mando) y Fase 3 (autonomía sobre archivos propios)
se añadirán aquí como nuevas entradas en TOOLS + FUNCTIONS cuando se validen, no antes.
"""
from core.tasks import find_tasks_by_project, find_tasks_by_keyword
from core.rag import search_memories
from connectors.google_tools import (
    get_recent_emails,
    search_emails,
    get_upcoming_events,
    list_drive_files,
    search_drive_files,
)

# ---------------------------------------------------------------------------
# Schemas (formato tools de OpenAI/NVIDIA/Ollama)
# ---------------------------------------------------------------------------

TOOLS = [
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
                    "limit": {"type": "integer", "description": "Maximo de resultados", "default": 10},
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
                    "max_results": {"type": "integer", "default": 5},
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
                    "max_results": {"type": "integer", "default": 5},
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
                    "max_results": {"type": "integer", "default": 10},
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
                    "max_results": {"type": "integer", "default": 10},
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
]

# ---------------------------------------------------------------------------
# Implementaciones -- envuelven funciones ya existentes en el proyecto
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


FUNCTIONS = {
    "query_tasks": query_tasks,
    "search_memory": search_memory,
    "list_recent_emails": list_recent_emails,
    "search_gmail": search_gmail,
    "list_calendar_events": list_calendar_events,
    "search_files_drive": search_files_drive,
    "start_audit": start_audit,
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
