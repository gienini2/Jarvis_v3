"""
core/processor.py
Logica central de procesamiento de mensajes.
Usado por los 3 flujos: api/main.py, scripts/chat.py, connectors/relay_client.py
"""
import logging
import threading
from core.llm import generate
from core import backend_state
from core.memory import save_message as _save_message
from core.rag import search_memories, store_memory_chunks
from core.intent import classify, log_intent as _log_intent
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


def _save_message_safely(role: str, message: str) -> None:
    """La memoria conversacional no debe dejar el chat inutil si Postgres arranca tarde."""
    try:
        _save_message(role, message)
    except Exception as e:
        log.warning("No se pudo guardar mensaje (%s): %s", role, e)


def _log_intent_safely(message: str, intent_type: str, payload=None, executed: bool = False) -> None:
    try:
        _log_intent(message, intent_type, payload, executed=executed)
    except Exception as e:
        log.warning("No se pudo registrar intent=%s: %s", intent_type, e)


def _tag(response: str) -> str:
    """Antepone [groq]/[nvidia]/[qwen-local]/[local] segun que IA respondio.
    Se aplica solo al texto que se devuelve al usuario -- la memoria y los logs
    guardan la respuesta limpia."""
    return f"[{backend_state.get_backend()}] {response}"


def process(message: str) -> tuple[str, str]:
    backend_state.reset()  # nuevo mensaje -> aun no ha respondido ningun backend
    _save_message_safely("user", message)

    # Alpha50 primero: entreno/rutina, por comando o lenguaje natural, y desde
    # cualquier interfaz (Telegram, Jarvis Chat, relay) — todas pasan por aquí.
    try:
        from alpha50.scheduler import alpha50_intent_handler
        alpha50_resp = alpha50_intent_handler(message)
    except Exception as e:
        log.warning(f"[alpha50] handler falló: {e}")
        alpha50_resp = None
    if alpha50_resp:
        log.debug("intent=alpha50")
        _log_intent_safely(message, "alpha50", None, executed=True)
        threading.Thread(
            target=store_memory_chunks,
            args=(f"user: {message}\nassistant: {alpha50_resp}",),
            kwargs={"source": "conversation"},
            daemon=True,
        ).start()
        return _tag(alpha50_resp), "alpha50"

    # Modo codigo explicito: peticiones de "hazme un programa/script/funcion..."
    # (o prefijo /code) se enrutan por rol "code" SIN tools, para que use el modelo
    # especializado en codigo de la cascada (offline: qwen2.5-coder; online: Groq).
    # El agente de tool-calling fuerza rol "tools" y nunca elegia el modelo de codigo.
    try:
        from core.code_mode import code_intent_handler
        code_resp = code_intent_handler(message)
    except Exception as e:
        log.warning(f"[code_mode] handler fallo: {e}")
        code_resp = None
    if code_resp:
        log.debug("intent=code")
        _log_intent_safely(message, "code", None, executed=True)
        _save_message_safely("assistant", code_resp)
        threading.Thread(
            target=store_memory_chunks,
            args=(f"user: {message}\nassistant: {code_resp}",),
            kwargs={"source": "conversation"},
            daemon=True,
        ).start()
        return _tag(code_resp), "code"

    # ------------------------------------------------------------------
    # Camino PRINCIPAL (05/07/2026): tool-calling agent (core/agent.py).
    # Decision explicita de Juan Pablo -- el agente pasa a ser el camino por
    # defecto para TODAS las interfaces (Telegram, chat local, API), no solo
    # para quien llame a /chat/agent a mano. El clasificador de intents de
    # abajo (core/intent.py) queda como FALLBACK: solo se usa si el agente
    # falla del todo (NVIDIA y Ollama caidos a la vez, o cualquier otra
    # excepcion). Ver ADR-0001 y SKILL.md "Cambios aplicados (05/07/2026)".
    # ------------------------------------------------------------------
    try:
        from core.agent import run as agent_run
        response = agent_run(message)
        _log_intent_safely(message, "agent", None, executed=True)
        _save_message_safely("assistant", response)
        threading.Thread(
            target=store_memory_chunks,
            args=(f"user: {message}\nassistant: {response}",),
            kwargs={"source": "conversation"},
            daemon=True,
        ).start()
        return _tag(response), "agent"
    except Exception as e:
        log.warning(f"[agent] fallo, cayendo al clasificador de intents (fallback): {e}")

    # ------------------------------------------------------------------
    # Fallback: clasificador de intents (regex + ML) -- camino original,
    # sin cambios, para cuando el agente no esta disponible.
    # ------------------------------------------------------------------
    intent = classify(message)
    log.debug(f"intent={intent.type} conf={intent.confidence}")

    if intent.type == "complete_task" and intent.task_ref:
        response = _complete_task(intent.task_ref)
        _log_intent_safely(message, "complete_task", {"task_ref": intent.task_ref}, executed=True)

    elif intent.type == "query_task":
        response = _query_task(intent.project_ref or "", message)
        _log_intent_safely(message, "query_task", {"project_ref": intent.project_ref})

    elif intent.type in ("google_gmail", "google_calendar", "google_drive"):
        response = handle_google_request(intent.type, message)
        _log_intent_safely(message, intent.type, intent.payload or None)

    elif intent.type == "mando_add_task":
        response = _mando_add(intent)
        _log_intent_safely(message, "mando_add_task", intent.payload, executed=True)

    elif intent.type == "mando_update_task":
        response = _mando_update(intent)
        _log_intent_safely(message, "mando_update_task", intent.payload, executed=True)

    elif intent.type == "mando_delete_task":
        response = _mando_delete(intent)
        _log_intent_safely(message, "mando_delete_task", intent.payload, executed=True)

    elif intent.type == "audit":
        response = _audit(intent)
        _log_intent_safely(message, "audit", intent.payload, executed=True)

    elif intent.type == "memory_search":
        memories = search_memories(intent.payload.get("query", message), limit=10)
        response = generate(message, rag_memories=memories, intent="memory_search") if memories else f"No encontre nada sobre '{intent.payload.get('query')}'."
        _log_intent_safely(message, "memory_search", intent.payload)

    elif intent.type == "remote_audit":
        response = _remote_audit(intent)
        _log_intent_safely(message, "remote_audit", intent.payload, executed=True)

    elif intent.type == "netscan":
        response = _netscan(intent)
        _log_intent_safely(message, "netscan", intent.payload, executed=True)

    else:
        memories = search_memories(message, limit=5)
        if memories:
            log.info(f"[RAG] {len(memories)} memorias encontradas (top sim={memories[0]['similarity']:.2f})")
        response = generate(message, rag_memories=memories if memories else None, intent=intent.type)
        _log_intent_safely(message, intent.type, intent.payload or None)
        _save_message_safely("assistant", response)

    threading.Thread(
        target=store_memory_chunks,
        args=(f"user: {message}\nassistant: {response}",),
        kwargs={"source": "conversation"},
        daemon=True,
    ).start()

    return _tag(response), intent.type


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


def _netscan(intent) -> str:
    """Lanza el escaneo de red defensivo en background. El informe llega por
    Telegram al terminar (mismo patron que _audit)."""
    p = intent.payload
    subnet = p.get("subnet", "")
    fast = p.get("fast", False)
    nse = p.get("nse_scripts")
    with_udp = p.get("with_udp", False)
    with_os = p.get("with_os", False)
    with_traceroute = p.get("with_traceroute", False)
    host_discovery = p.get("host_discovery", "default")
    try:
        import threading
        from netscan import report as netscan_report
        threading.Thread(
            target=lambda: netscan_report.run_scan(
                subnet=subnet or None, fast=fast, with_cve=True, notify=True,
                nse_scripts=nse, with_udp=with_udp, with_os=with_os,
                with_traceroute=with_traceroute, host_discovery=host_discovery,
            ),
            daemon=True,
        ).start()
        destino = subnet or "tu red local"
        extras = [x for x, on in (
            ("vulnerabilidades", bool(nse)), ("UDP", with_udp),
            ("sistema operativo", with_os), ("traceroute", with_traceroute),
        ) if on]
        detalle = f" (con {', '.join(extras)})" if extras else ""
        return f"Escaneando {destino}{detalle}. Te mando el informe por Telegram en 1-3 minutos."
    except Exception as e:
        return f"No pude iniciar el escaneo de red: {e}"
