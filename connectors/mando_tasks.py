"""
connectors/mando_tasks.py — CRUD tareas Centro de Mando
Llama a mando-api (Fígaro:10003) para crear/modificar/eliminar tareas.
"""

import requests
import urllib3
from config.settings import settings

urllib3.disable_warnings()

# URL base del mando-api en Fígaro
MANDO_API = getattr(settings, "MANDO_API_URL", "https://figaro-server.taild7b9e6.ts.net/mando-api")

# El cert TLS de Fígaro (host interno de Tailscale) está caducado y tumbaba TODO
# el Centro de Mando: list/add/update/delete fallaban con CERTIFICATE_VERIFY_FAILED.
# Igual que core/dashboard.py para este mismo host, no verificamos el cert.
# Arreglo de raíz pendiente: renovar el certificado en Fígaro (ver CLAUDE.md).
_session = requests.Session()
_session.verify = False


def _url(path: str) -> str:
    return f"{MANDO_API}{path}"


def list_projects() -> list:
    """Devuelve todos los proyectos con sus tareas."""
    r = _session.get(_url("/tareas"), timeout=10)
    r.raise_for_status()
    return r.json()


def add_task(project_id: str, text: str, priority: str = "mid") -> dict:
    """
    Añade una tarea a un proyecto.
    priority: 'high' | 'mid' | 'low'
    Devuelve: { ok, mando_key, taskIdx }
    """
    r = _session.post(
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
    r = _session.patch(
        _url(f"/tareas/{project_id}/{task_idx}"),
        json=body,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def delete_task(project_id: str, task_idx: int) -> dict:
    """Elimina una tarea por índice."""
    r = _session.delete(
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
