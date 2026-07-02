"""
core/processor.py
Logica central de procesamiento de mensajes.
Usado por los 3 flujos: api/main.py, scripts/chat.py, connectors/relay_client.py
"""
import logging
import threading
from core.llm import generate
from core.memory import save_message
from core.rag import search_memories, store_memory
from core.intent import classify, log_intent
from core.tasks import (
    resolve_task_ref,
    complete_task,
    find_tasks_by_project,
    find_tasks_by_keyword,
    sync_tasks_from_json,
)
from connectors.google_tools import handle_google_request
from connectors.mando_tasks import add_task, find_project_id

log = logging.getLogger("jarvis.processor")


def process(message: str) -> tuple[str, str]:
    save_message("user", message)
    intent = classify(message)
    log.debug(f"intent={intent.type} conf={intent.confidence}")

    if intent.type == "complete_task" and intent.task_ref:
        response = _complete_task(intent.task_ref)
        log_intent(message, "complete_task", {"task_ref": intent.task_ref}, executed=True)

    elif intent.type == "query_task":
        response = _query_task(intent.project_ref or "", message)
        log_intent(message, "query_task", {"project_ref": intent.project_ref})

    elif intent.type in ("google_gmail", "google_calendar", "google_drive"):
        response = handle_google_request(intent.type, message)
        log_intent(message, intent.type, intent.payload or None)

    elif intent.type == "mando_add_task":
        response = _mando_add(intent)
        log_intent(message, "mando_add_task", intent.payload, executed=True)

    elif intent.type == "mando_update_task":
        response = _mando_update(intent)
        log_intent(message, "mando_update_task", intent.payload, executed=True)

    elif intent.type == "mando_delete_task":
        response = _mando_delete(intent)
        log_intent(message, "mando_delete_task", intent.payload, executed=True)

    elif intent.type == "audit":
        response = _audit(intent)
        log_intent(message, "audit", intent.payload, executed=True)

    elif intent.type == "memory_search":
        memories = search_memories(intent.payload.get("query", message), limit=10)
        response = generate(message, rag_memories=memories, intent="memory_search") if memories else f"No encontre nada sobre '{intent.payload.get('query')}'."
        log_intent(message, "memory_search", intent.payload)

    elif intent.type == "remote_audit":
        response = _remote_audit(intent)
        log_intent(message, "remote_audit", intent.payload, executed=True)

    else:
        memories = search_memories(message, limit=5)
        if memories:
            log.info(f"[RAG] {len(memories)} memorias encontradas (top sim={memories[0]['similarity']:.2f})")
        response = generate(message, rag_memories=memories if memories else None, intent=intent.type)
        log_intent(message, intent.type, intent.payload or None)
        save_message("assistant", response)

    threading.Thread(
        target=store_memory,
        args=(f"user: {message}\nassistant: {response}",),
        kwargs={"source": "conversation"},
        daemon=True,
    ).start()

    return response, intent.type


# ---------------------------------------------------------------------------
# Handlers internos
# ---------------------------------------------------------------------------

def _complete_task(task_ref: str) -> str:
    matches = resolve_task_ref(task_ref)
    if not matches:
        return f"No encontre ninguna tarea pendiente con '{task_ref}'."
    if len(matches) == 1:
        t = matches[0]
        ok = complete_task(t["mando_key"])
        if ok:
            return f"Tarea marcada como completada:\n[{t['priority']}] {t['project']} -> {t['title']}"
        return "No pude actualizar el estado de la tarea."
    lines = "\n".join(
        f"  {i+1}. [{t['priority']}] {t['mando_key']} -- {t['title']}"
        for i, t in enumerate(matches[:5])
    )
    return f"Encontre varias tareas con '{task_ref}'. Cual quieres marcar como hecha?\n{lines}"


def _query_task(project_ref: str, original_message: str) -> str:
    tasks = find_tasks_by_project(project_ref) if project_ref else []
    if not tasks:
        tasks = find_tasks_by_keyword(project_ref)
    if not tasks:
        return generate(original_message)
    lines = "\n".join(f"  [{t['priority']}] {t['title']}" for t in tasks[:10])
    return f"Tareas pendientes -- {tasks[0]['project']}:\n" + lines


def _mando_add(intent) -> str:
    project_id = intent.project_ref
    text       = intent.payload.get("text", "")
    priority   = intent.payload.get("priority", "mid")
    if not project_id or not text:
        return "No entendi el proyecto o el texto de la tarea."
    if not any(c in project_id for c in ["-", "_"]):
        resolved = find_project_id(project_id)
        if resolved:
            project_id = resolved
    try:
        result = add_task(project_id, text, priority)
        sync_tasks_from_json()
        return f"Tarea anadida al proyecto '{project_id}':\n[{priority}] {text}\nmando_key: {result.get('mando_key', '?')}"
    except Exception as e:
        return f"No pude anadir la tarea: {e}"


def _mando_update(intent) -> str:
    task_ref = intent.task_ref
    if not task_ref:
        return "No entendi que tarea quieres modificar."
    matches = resolve_task_ref(task_ref)
    if not matches:
        return f"No encontre ninguna tarea pendiente con '{task_ref}'."
    if len(matches) > 1:
        lines = "\n".join(
            f"  {i+1}. [{t['priority']}] {t['mando_key']} -- {t['title']}"
            for i, t in enumerate(matches[:5])
        )
        return f"Encontre varias tareas con '{task_ref}'. Cual quieres modificar?\n{lines}"

    t = matches[0]
    project_id, idx = t["mando_key"].rsplit("_", 1)
    new_text = intent.payload.get("text")
    new_priority = intent.payload.get("priority")

    try:
        from connectors.mando_tasks import update_task
        update_task(project_id, int(idx), text=new_text, priority=new_priority)
        sync_tasks_from_json()
        cambios = []
        if new_text:
            cambios.append(f"texto -> {new_text}")
        if new_priority:
            cambios.append(f"prioridad -> {new_priority}")
        return f"Tarea actualizada: {t['title']}\n" + "\n".join(cambios)
    except Exception as e:
        return f"No pude modificar la tarea: {e}"


def _mando_delete(intent) -> str:
    task_ref = intent.task_ref
    if not task_ref:
        return "No entendi que tarea quieres eliminar."
    matches = resolve_task_ref(task_ref)
    if not matches:
        return f"No encontre ninguna tarea pendiente con '{task_ref}'."
    if len(matches) > 1:
        lines = "\n".join(
            f"  {i+1}. [{t['priority']}] {t['mando_key']} -- {t['title']}"
            for i, t in enumerate(matches[:5])
        )
        return f"Encontre varias tareas con '{task_ref}'. Cual quieres eliminar?\n{lines}"

    t = matches[0]
    project_id, idx = t["mando_key"].rsplit("_", 1)

    try:
        from connectors.mando_tasks import delete_task
        delete_task(project_id, int(idx))
        sync_tasks_from_json()
        return f"Tarea eliminada: [{t['priority']}] {t['project']} -> {t['title']}"
    except Exception as e:
        return f"No pude eliminar la tarea: {e}"


def _audit(intent) -> str:
    path = intent.payload.get("path", "")
    if not path:
        return "No entendi que repositorio auditar."
    try:
        from auditor.runner import start_audit_thread
        job_id = start_audit_thread(path)
        return f"Auditoria iniciada (job_id={job_id})\nRuta: {path}\nTe aviso cuando termine."
    except Exception as e:
        return f"No pude iniciar la auditoria: {e}"


def _remote_audit(intent) -> str:
    project = intent.payload.get("project", "")
    if not project:
        return "No entendi que proyecto auditar en Figaro."
    try:
        from connectors.remote_audit import fetch_and_audit
        job_id, msg = fetch_and_audit(project)
        return msg
    except Exception as e:
        return f"No pude auditar {project}: {e}"
