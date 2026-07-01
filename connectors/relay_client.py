"""
relay_client.py
Drena la cola de mensajes pendientes en figaro-server al arrancar Jarvis.
Se llama una vez en el startup de FastAPI.
"""

import logging
import httpx

from config.settings import settings
from core.memory import save_message
from core.intent import classify, log_intent
from core.tasks import resolve_task_ref, complete_task, find_tasks_by_project, find_tasks_by_keyword
from core.llm import generate
from core.dashboard import get_pending_tasks

log = logging.getLogger("relay_client")

RELAY_BASE = settings.RELAY_URL   # http://figaro-server.taild7b9e6.ts.net:10004


def drain_queue():
    """
    Obtiene mensajes pendientes del relay, los procesa y hace ACK.
    Llamar una vez al arrancar FastAPI.
    """
    try:
        resp = httpx.get(f"{RELAY_BASE}/queue/pending", timeout=5)
        resp.raise_for_status()
        pending = resp.json()
    except Exception as e:
        log.warning(f"No se pudo conectar al relay: {e}")
        return 0

    if not pending:
        return 0

    log.info(f"Cola: {len(pending)} mensajes pendientes")
    processed = 0

    for item in pending:
        msg_id  = item["id"]
        message = item["message"]

        try:
            response = _process(message)
            _ack(msg_id, response)
            processed += 1
            log.info(f"Procesado cola id={msg_id}")
        except Exception as e:
            log.error(f"Error procesando cola id={msg_id}: {e}")

    return processed


def _process(message: str) -> str:
    save_message("user", message)
    intent = classify(message)

    if intent.type == "complete_task" and intent.task_ref:
        from api.main import _handle_complete_task
        response = _handle_complete_task(intent.task_ref)
        log_intent(message, "complete_task", {"task_ref": intent.task_ref}, executed=True)

    elif intent.type == "query_task":
        from api.main import _handle_query_task
        response = _handle_query_task(intent.project_ref or "", message)
        log_intent(message, "query_task", {"project_ref": intent.project_ref})

    else:
        response = generate(message)
        log_intent(message, intent.type, intent.payload or None)

    save_message("assistant", response)
    return response


def _ack(msg_id: int, response: str):
    httpx.post(
        f"{RELAY_BASE}/queue/ack",
        json={"id": msg_id, "response": response},
        timeout=5,
    )