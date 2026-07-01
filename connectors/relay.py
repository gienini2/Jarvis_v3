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
from fastapi import FastAPI
from pydantic import BaseModel
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
AUTHORIZED_ID   = int(os.environ["AUTHORIZED_CHAT_ID"])   # 81742
JARVIS_URL      = os.environ.get("JARVIS_URL", "http://79.154.128.21:3000/chat")
JARVIS_TIMEOUT  = float(os.environ.get("JARVIS_TIMEOUT", "10"))
DB_PATH         = Path(os.environ.get("QUEUE_DB", "/opt/jarvis-relay/queue.db"))

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
        "SELECT id, chat_id, message, created_at FROM queue WHERE processed=0 ORDER BY id",
    ).fetchall()
    conn.close()
    return [{"id": r[0], "chat_id": r[1], "message": r[2], "created_at": r[3]} for r in rows]


def mark_processed(msg_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE queue SET processed=1 WHERE id=?", (msg_id,))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Telegram bot
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != AUTHORIZED_ID:
        log.warning(f"Mensaje rechazado de chat_id={update.effective_chat.id}")
        return

    text = update.message.text
    log.info(f"Mensaje recibido: {text[:60]}")

    try:
        async with httpx.AsyncClient(timeout=JARVIS_TIMEOUT) as client:
            resp = await client.post(JARVIS_URL, json={"message": text})
            resp.raise_for_status()
            data = resp.json()
            await update.message.reply_text(data["response"])
            log.info("Respuesta enviada directamente")

    except Exception as e:
        log.warning(f"PC no disponible ({e}) — encolando")
        enqueue(update.effective_chat.id, text)
        await update.message.reply_text(
            "⏳ Jarvis offline. Mensaje guardado — lo procesará cuando arranque."
        )


async def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("Bot Telegram iniciado")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        # Espera indefinida hasta cancelación
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()

# ---------------------------------------------------------------------------
# FastAPI — endpoints de cola para el PC
# ---------------------------------------------------------------------------

bot_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(api: FastAPI):
    global bot_task
    init_db()
    bot_task = asyncio.create_task(run_bot())
    yield
    if bot_task:
        bot_task.cancel()


api = FastAPI(lifespan=lifespan)


class AckRequest(BaseModel):
    id: int
    response: str = ""   # opcional — para logging futuro


@api.get("/queue/pending")
def queue_pending():
    """El PC llama esto al arrancar para obtener mensajes pendientes."""
    return get_pending()


@api.post("/queue/ack")
def queue_ack(req: AckRequest):
    """El PC confirma que procesó un mensaje."""
    mark_processed(req.id)
    log.info(f"ACK mensaje id={req.id}")
    return {"status": "ok"}


@api.get("/health")
def health():
    return {"status": "ok"}
