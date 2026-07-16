import asyncio
import contextlib
import os
import logging
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.processor import process
from core.tasks import find_tasks_by_project, find_tasks_by_keyword, sync_tasks_from_json, add_task_context
from core.dashboard import get_pending_tasks
from connectors.relay_client import drain_queue
from auditor.api_routes import audit_router
from auditor.db import get_job, get_summaries
from config.settings import settings
from core.db import get_connection
from core.rag import search_memories
from api.openai_compat import router as openai_router
from netscan.api_routes import router as netscan_router

os.environ["PYTHONUTF8"] = "1"
log = logging.getLogger("jarvis")

_RELAY_POLL_INTERVAL = 60



async def _poll_relay():
    while True:
        await asyncio.sleep(_RELAY_POLL_INTERVAL)
        try:
            n = await asyncio.to_thread(drain_queue)
            if n:
                log.info(f"Relay poll: {n} mensajes drenados")
        except Exception as e:
            log.debug(f"Relay poll: {e}")


@asynccontextmanager
async def lifespan(app):
    # El drain puede implicar llamadas LLM lentas. Arrancar la API primero es
    # esencial tras encender/reanudar el portatil: /health y /chat no deben
    # esperar a que se vacie la cola de Telegram.
    startup_drain = asyncio.create_task(asyncio.to_thread(drain_queue))
    task = asyncio.create_task(_poll_relay())
    yield
    for background_task in (startup_drain, task):
        background_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await background_task


app = FastAPI(lifespan=lifespan)

# Rutas que no requieren clave -- liveness check y la pagina de la UI web (solo
# sirve HTML/JS estatico; /history y /chat que llama la UI SI exigen la clave).
_PUBLIC_PATHS = {"/health", "/", "/ui"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Exige el header X-Jarvis-Key en todas las rutas salvo /health.

    Si JARVIS_API_KEY no esta configurada en .env, no se bloquea nada (para no
    romper un entorno de desarrollo recien clonado) pero se deja un warning en
    el log al arrancar -- ver mas abajo.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS or not settings.JARVIS_API_KEY:
            return await call_next(request)
        if request.headers.get("x-jarvis-key") != settings.JARVIS_API_KEY:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
        return await call_next(request)

app.include_router(netscan_router)

app.add_middleware(ApiKeyMiddleware)

if not settings.JARVIS_API_KEY:
    log.warning(
        "JARVIS_API_KEY no configurada -- la API esta ABIERTA sin autenticacion. "
        "Define JARVIS_API_KEY en .env para protegerla."
    )

app.include_router(openai_router, prefix="/v1")

class ChatRequest(BaseModel):
    message: str


class ContextRequest(BaseModel):
    mando_key: str
    type: str
    content: str


class AprendeRequest(BaseModel):
    message: str
    intent: str


@app.get("/health")
def health():
    return {"status": "ok"}


# --- UI web (rama feature/web-chat-ui) -------------------------------------
from pathlib import Path
_UI_PATH = Path(__file__).resolve().parent.parent / "web" / "chat.html"


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def ui_page():
    """Chat web local: historial + Enter/Shift+Enter + adjuntos. Accesible desde
    el movil por la IP Tailscale del PC (http://<tailscale-ip>:3000/ui)."""
    return HTMLResponse(_UI_PATH.read_text(encoding="utf-8"))


@app.get("/history")
def history(limit: int = Query(30)):
    """Ultimos turnos de conversacion para pintar el scrollback de la UI."""
    from core.memory import get_recent_messages
    rows = get_recent_messages(limit=limit)
    return [{"role": r[0], "message": r[1], "time": str(r[2])} for r in rows]


@app.post("/audit/{job_id}/notify")
async def audit_notify(job_id: int):
    job = get_job(job_id)
    if not job:
        return {"error": "job not found"}
    summaries = get_summaries(job_id, level="executive")
    text = summaries[0]["summary"] if summaries else "Auditoría completada sin resumen."
    if len(text) > 3800:
        text = text[:3800] + "\n\n…_(resumen truncado, ver EXECUTIVE_SUMMARY.md)_"
    message = f"✅ Auditoría completada — job_id={job_id}\n{job['repo_path']}\n\n{text}"
    try:
        headers = {"X-Relay-Key": settings.RELAY_API_KEY} if settings.RELAY_API_KEY else {}
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{settings.RELAY_URL}/notify", json={"message": message}, headers=headers)
    except Exception as e:
        log.warning(f"[notify] no se pudo mandar a Telegram: {e}")
    return {"status": "notified"}


@app.post("/chat")
def chat(req: ChatRequest):
    # Alpha50 ya se resuelve dentro de process() (core/processor.py), común a
    # todas las interfaces. No hace falta llamar al handler aquí también.
    response, intent_type = process(req.message)
    return JSONResponse(
        content={"response": response, "intent": intent_type},
        media_type="application/json; charset=utf-8",
    )


@app.post("/chat/agent")
def chat_agent(req: ChatRequest):
    """
    Ruta ALTERNATIVA de tool-calling (ADR-0001, Fase 1+2). No reemplaza /chat --
    convive con el flujo de intents de siempre para poder comparar antes de decidir
    si sustituye al clasificador de core/intent.py. Usa NVIDIA (llama-3.3-70b-instruct)
    como motor de decision, con fallback a qwen2.5 local si no hay internet.
    """
    from core.mando_intents import handle_mando
    reply = handle_mando(req.message)
    if reply is not None:
        return reply   # adapta al formato de respuesta actual del endpoint
    from core.agent import run
    try:
        response = run(req.message)
    except Exception as e:
        log.error(f"[chat_agent] fallo: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )
    return JSONResponse(
        content={"response": response, "intent": "agent"},
        media_type="application/json; charset=utf-8",
    )


@app.post("/aprende")
def aprende(req: AprendeRequest):
    """Guarda un par (mensaje, intent) confirmado por el usuario para reentrenamiento."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO intents (message, intent_type, confirmed) VALUES (%s, %s, true)",
            (req.message, req.intent)
        )
        conn.commit()
    finally:
        conn.close()
    log.info(f"[aprende] guardado: '{req.message[:60]}' → {req.intent}")
    return {"status": "ok", "message": req.message, "intent": req.intent}


@app.get("/tasks")
def get_tasks(
    project: str = Query(None),
    keyword: str = Query(None),
    status: str = Query(None),
):
    if project:
        return find_tasks_by_project(project, exclude_done=(status != "all"))
    if keyword:
        return find_tasks_by_keyword(keyword, exclude_done=(status != "all"))
    return get_pending_tasks(limit=30)


@app.post("/tasks/sync")
def tasks_sync():
    n = sync_tasks_from_json()
    return {"synced": n}


@app.post("/tasks/context")
def tasks_add_context(req: ContextRequest):
    ok = add_task_context(req.mando_key, req.type, req.content)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "task not found"})
    return {"status": "ok"}
