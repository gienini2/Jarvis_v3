"""
Jarvis Relay — figaro-server
- Recibe mensajes de Telegram
- Si el PC está encendido: reenvía a Jarvis y devuelve respuesta
- Si el PC está apagado: guarda en cola SQLite
- Expone /queue/pending y /queue/ack para que el PC drene la cola al arrancar
"""

import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
AUTHORIZED_ID   = int(os.environ["AUTHORIZED_CHAT_ID"])   # 81742
# Antes el default era una IP publica (79.154.128.21) -- si JARVIS_URL faltaba
# en el .env de Figaro, el relay intentaba salir a internet en vez de usar
# Tailscale. Default seguro: Tailscale IP del PC (100.127.159.59), solo
# alcanzable dentro de la tailnet.
JARVIS_URL      = os.environ.get("JARVIS_URL", "http://100.127.159.59:3000/chat")
# Antes 10s -- Ollama+Mem0 a veces tarda mas que eso y el timeout disparaba
# el "offline" falso (ver handle_message). Subido a 60s para dar margen real.
JARVIS_TIMEOUT  = float(os.environ.get("JARVIS_TIMEOUT", "60"))
# Reintentos de conexión antes de declarar "offline": cubre el caso de que
# JarvisAPI esté arrancando (PC encendido pero el servicio aún no acepta
# conexiones). Con esto se evita el "offline" falso + la respuesta duplicada.
JARVIS_CONNECT_RETRIES     = int(os.environ.get("JARVIS_CONNECT_RETRIES", "3"))
JARVIS_CONNECT_RETRY_DELAY = float(os.environ.get("JARVIS_CONNECT_RETRY_DELAY", "5"))
DB_PATH         = Path(os.environ.get("QUEUE_DB", "/opt/jarvis-relay/queue.db"))

# Claves compartidas -- ver config/settings.py (JARVIS_API_KEY / RELAY_API_KEY)
JARVIS_API_KEY  = os.environ.get("JARVIS_API_KEY", "")
RELAY_API_KEY   = os.environ.get("RELAY_API_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("relay")

# ---------------------------------------------------------------------------
# Cola SQLite
# ---------------------------------------------------------------------------

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER NOT NULL,
            message     TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now')),
            processed   INTEGER DEFAULT 0
        )
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(queue)")}
    if "response" not in columns:
        conn.execute("ALTER TABLE queue ADD COLUMN response TEXT")
    if "response_ready" not in columns:
        conn.execute("ALTER TABLE queue ADD COLUMN response_ready INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


def enqueue(chat_id: int, message: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO queue (chat_id, message) VALUES (?, ?)",
        (chat_id, message),
    )
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    log.info(f"Encolado mensaje id={msg_id}")
    return msg_id


def get_pending() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, chat_id, message, created_at FROM queue "
        "WHERE processed=0 AND response_ready=0 ORDER BY id",
    ).fetchall()
    conn.close()
    return [{"id": r[0], "chat_id": r[1], "message": r[2], "created_at": r[3]} for r in rows]


def mark_processed(msg_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE queue SET processed=1 WHERE id=?", (msg_id,))
    conn.commit()
    conn.close()


def get_chat_id(msg_id: int) -> int | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT chat_id FROM queue WHERE id=?", (msg_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def save_response(msg_id: int, response: str) -> bool:
    """Persiste la respuesta antes de intentar entregarla a Telegram.

    Asi, si el PC pierde la conexion tras procesar un mensaje, un reintento no
    vuelve a ejecutar herramientas con efectos reales: el relay reintenta solo
    la entrega de la respuesta ya guardada.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "UPDATE queue SET response=?, response_ready=1 WHERE id=? AND processed=0",
        (response, msg_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_ready_responses() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, chat_id, response FROM queue "
        "WHERE processed=0 AND response_ready=1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [{"id": row[0], "chat_id": row[1], "response": row[2]} for row in rows]

# ---------------------------------------------------------------------------
# Telegram bot
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != AUTHORIZED_ID:
        log.warning(f"Mensaje rechazado de chat_id={update.effective_chat.id}")
        return

    text = update.message.text
    log.info(f"Mensaje recibido: {text[:60]}")

    headers = {"X-Jarvis-Key": JARVIS_API_KEY} if JARVIS_API_KEY else {}
    ultimo_conn_err = None

    # Reintentar la conexión antes de declarar "offline": si JarvisAPI está
    # arrancando (PC encendido pero servicio no listo), un reintento a los pocos
    # segundos lo pilla ya en marcha y evita el "offline" falso.
    for intento in range(JARVIS_CONNECT_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=JARVIS_TIMEOUT) as client:
                resp = await client.post(JARVIS_URL, json={"message": text}, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                await update.message.reply_text(data["response"])
                log.info("Respuesta enviada directamente")
                return

        except (httpx.ConnectError, httpx.ConnectTimeout, ConnectionRefusedError) as e:
            # JarvisAPI no acepta conexión aún: puede estar arrancando → reintentar.
            ultimo_conn_err = e
            if intento < JARVIS_CONNECT_RETRIES - 1:
                log.info(f"PC no responde aún ({e}); reintento en {JARVIS_CONNECT_RETRY_DELAY}s")
                await asyncio.sleep(JARVIS_CONNECT_RETRY_DELAY)
                continue

        except httpx.TimeoutException as e:
            # El PC aceptó la conexión pero tarda más de JARVIS_TIMEOUT (Ollama en
            # frío). No encolamos para no duplicar la respuesta: solo avisamos.
            log.warning(f"Jarvis tardó más de {JARVIS_TIMEOUT}s en responder ({e})")
            await update.message.reply_text(
                "⏳ Jarvis está tardando más de lo normal en responder. "
                "Si no contesta en un minuto, vuelve a escribir."
            )
            return

        except Exception as e:
            log.warning(f"Error inesperado hablando con Jarvis ({e}) — encolando")
            enqueue(update.effective_chat.id, text)
            await update.message.reply_text(
                "⏳ Jarvis offline. Mensaje guardado — lo procesará cuando arranque."
            )
            return

    # Agotados los reintentos de conexión → offline real. Encolamos.
    log.warning(f"PC no disponible tras {JARVIS_CONNECT_RETRIES} intentos ({ultimo_conn_err}) — encolando")
    enqueue(update.effective_chat.id, text)
    await update.message.reply_text(
        "⏳ Jarvis offline. Mensaje guardado — lo procesará cuando arranque."
    )


telegram_app = None  # se asigna en run_bot() -- /notify reutiliza telegram_app.bot


async def run_bot():
    global telegram_app
    telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("Bot Telegram iniciado")
    async with telegram_app:
        await telegram_app.start()
        await telegram_app.updater.start_polling(drop_pending_updates=True)
        # Espera indefinida hasta cancelación
        await asyncio.Event().wait()
        await telegram_app.updater.stop()
        await telegram_app.stop()

# ---------------------------------------------------------------------------
# FastAPI — endpoints de cola para el PC
# ---------------------------------------------------------------------------

bot_task: asyncio.Task | None = None
delivery_task: asyncio.Task | None = None
_delivery_lock = asyncio.Lock()


async def _deliver_ready_responses() -> int:
    """Intenta entregar respuestas ya persistidas, sin volver a procesarlas."""
    if telegram_app is None:
        return 0
    delivered = 0
    async with _delivery_lock:
        for item in get_ready_responses():
            try:
                await telegram_app.bot.send_message(
                    chat_id=item["chat_id"], text=item["response"]
                )
                mark_processed(item["id"])
                delivered += 1
                log.info(f"Respuesta de cola entregada id={item['id']}")
            except Exception as e:
                log.warning(f"[queue] entrega pendiente id={item['id']}: {e}")
    return delivered


async def _retry_deliveries():
    while True:
        await asyncio.sleep(30)
        await _deliver_ready_responses()


@asynccontextmanager
async def lifespan(api: FastAPI):
    global bot_task, delivery_task
    init_db()
    bot_task = asyncio.create_task(run_bot())
    delivery_task = asyncio.create_task(_retry_deliveries())
    yield
    for task in (bot_task, delivery_task):
        if task:
            task.cancel()


api = FastAPI(lifespan=lifespan)


class AckRequest(BaseModel):
    id: int
    response: str = ""   # opcional — para logging futuro


class NotifyRequest(BaseModel):
    message: str


def _check_relay_key(x_relay_key: str = Header(default="")):
    """Protege /queue/* -- solo el PC (que conoce RELAY_API_KEY) puede leer/ack
    la cola. Si RELAY_API_KEY no esta configurada, no bloquea (dev)."""
    if RELAY_API_KEY and x_relay_key != RELAY_API_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")


@api.get("/queue/pending")
def queue_pending(x_relay_key: str = Header(default="")):
    """El PC llama esto al arrancar para obtener mensajes pendientes."""
    _check_relay_key(x_relay_key)
    return get_pending()


@api.post("/queue/ack")
async def queue_ack(req: AckRequest, x_relay_key: str = Header(default="")):
    """
    El PC confirma que proceso un mensaje. Antes esto SOLO marcaba processed=1
    y tiraba req.response (el comentario del campo decia literalmente "opcional
    -- para logging futuro"). O sea: cualquier mensaje que llegara mientras el
    PC estaba offline se procesaba bien pero la respuesta nunca volvia a
    Telegram. Ahora se reenvia al chat_id original.
    """
    _check_relay_key(x_relay_key)
    chat_id = get_chat_id(req.id)

    if not chat_id:
        raise HTTPException(status_code=404, detail="mensaje de cola no encontrado")

    if req.response:
        if not save_response(req.id, req.response):
            return {"status": "already_processed"}
        delivered = await _deliver_ready_responses()
        return {
            "status": "delivered" if delivered else "delivery_pending",
            "id": req.id,
        }

    raise HTTPException(status_code=422, detail="falta la respuesta a entregar")


@api.post("/notify")
async def notify(req: NotifyRequest, x_relay_key: str = Header(default="")):
    """
    Envio proactivo (no es respuesta a un mensaje entrante): lo usan
    auditor (api/main.py) y Alpha50 (scheduler.py) para empujar avisos.
    Antes esta ruta NO EXISTIA -- ambos llamantes recibian 404 en silencio
    y el mensaje nunca llegaba a Telegram.
    """
    _check_relay_key(x_relay_key)
    if telegram_app is None:
        raise HTTPException(status_code=503, detail="bot todavia no arrancado")
    try:
        await telegram_app.bot.send_message(chat_id=AUTHORIZED_ID, text=req.message)
        return {"status": "sent"}
    except Exception as e:
        log.error(f"[notify] fallo enviando a Telegram: {e}")
        raise HTTPException(status_code=502, detail=str(e))


@api.get("/health")
def health():
    return {"status": "ok"}
