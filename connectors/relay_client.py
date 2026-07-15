"""
relay_client.py
Drena la cola de mensajes pendientes en figaro-server.
Llamado al arrancar Jarvis y cada 60s desde el polling de api/main.py.
"""
import logging
import threading
import httpx
from config.settings import settings

log = logging.getLogger("relay_client")
RELAY_BASE = settings.RELAY_URL
_HEADERS = {"X-Relay-Key": settings.RELAY_API_KEY} if settings.RELAY_API_KEY else {}

# Evita drains concurrentes si el polling se solapa con un drain lento
_drain_lock = threading.Lock()


def drain_queue() -> int:
    if not _drain_lock.acquire(blocking=False):
        log.debug("drain_queue ya en curso, omitiendo")
        return 0
    try:
        return _drain()
    finally:
        _drain_lock.release()


def _drain() -> int:
    try:
        resp = httpx.get(f"{RELAY_BASE}/queue/pending", headers=_HEADERS, timeout=5)
        resp.raise_for_status()
        pending = resp.json()
    except Exception as e:
        log.warning(f"No se pudo conectar al relay: {e}")
        return 0

    if not pending:
        return 0

    log.info(f"Cola: {len(pending)} mensajes pendientes")
    from core.processor import process
    processed = 0
    for item in pending:
        msg_id  = item["id"]
        message = item["message"]
        try:
            response, _ = process(message)
            if _ack(msg_id, response):
                processed += 1
            else:
                log.warning(f"ACK no confirmado id={msg_id}; se reintentara en el siguiente drain")
        except Exception as e:
            log.error(f"Error procesando cola id={msg_id}: {e}")
    return processed


def _ack(msg_id: int, response: str) -> bool:
    try:
        resp = httpx.post(
            f"{RELAY_BASE}/queue/ack",
            json={"id": msg_id, "response": response},
            headers=_HEADERS,
            timeout=5,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        log.warning(f"ACK fallido id={msg_id}: {e}")
        return False


def send_telegram_message(text: str) -> bool:
    """Manda un mensaje a Juan Pablo por Telegram fuera del ciclo pregunta/respuesta
    normal, reusando el mismo endpoint /notify que auditor y Alpha50 (ver
    api/main.py:audit_notify y alpha50/scheduler.py:enviar_telegram). Usado por la
    tool send_telegram_message de core/tools.py (05/07/2026)."""
    try:
        resp = httpx.post(
            f"{RELAY_BASE}/notify",
            json={"message": text},
            headers=_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        log.warning(f"send_telegram_message fallo: {e}")
        return False
