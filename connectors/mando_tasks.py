"""
connectors/mando_tasks.py — CRUD tareas Centro de Mando
Llama a mando-api (Fígaro:10003) para crear/modificar/eliminar tareas.
"""

import requests
from config.settings import settings

# URL base del mando-api en Fígaro
MANDO_API = getattr(settings, "MANDO_API_URL", "https://figaro-server.taild7b9e6.ts.net/mando-api")


def _url(path: str) -> str:
    return f"{MANDO_API}{path}"


def list_projects() -> list:
    """Devuelve todos los proyectos con sus tareas."""
    r = requests.get(_url("/tareas"), timeout=10)
    r.raise_for_status()
    return r.json()


def add_task(project_id: str, text: str, priority: str = "mid") -> dict:
    """
    Añade una tarea a un proyecto.
    priority: 'high' | 'mid' | 'low'
    Devuelve: { ok, mando_key, taskIdx }
    """
    r = requests.post(
        _url(f"/tareas/{project_id}"),
        json={"text": text, "priority": priority},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def update_task(project_id: str, task_idx: int, text: str = None, priority: str = None) -> dict:
    """Modifica texto y/o prioridad de una tarea existente."""
    body = {}
    if text:     body["text"]     = text
    if priority: body["priority"] = priority
    r = requests.patch(
        _url(f"/tareas/{project_id}/{task_idx}"),
        json=body,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def delete_task(project_id: str, task_idx: int) -> dict:
    """Elimina una tarea por índice."""
    r = requests.delete(
        _url(f"/tareas/{project_id}/{task_idx}"),
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def find_project_id(name: str) -> str | None:
    """
    Busca el project_id por nombre parcial (case-insensitive).
    Útil para lenguaje natural: "jarvis" → "dragai-tech"
    """
    projects = list_projects()
    name_lower = name.lower()
    for p in projects:
        if name_lower in p["id"].lower() or name_lower in p["title"].lower():
            return p["id"]
    return None
