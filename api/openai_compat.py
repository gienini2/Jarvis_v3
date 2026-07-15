import time, uuid, logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.processor import process
from core.rag import search_memories

log = logging.getLogger("jarvis.openai_compat")
router = APIRouter()


@router.post("/chat/completions")
async def openai_chat(request: Request):
    try:
        body = await request.json()
        log.debug(f"[compat] keys={list(body.keys())}")
        log.debug(f"[compat] body={str(body)[:800]}")
        log.debug(f"[compat] full body: {str(body)[:2000]}")

        messages = body.get("messages", [])
        log.debug(f"[compat] all message roles: {[m.get('role') for m in messages]}")

        user_msg = ""
        for m in reversed(messages):
            role = m.get("role", "")
            if role in ("user", "openclaw-control-ui"):
                content = m.get("content", "")
                # Si es string, tomar tal cual
                if isinstance(content, str):
                    user_msg = content.strip()
                # Si es lista, tomar el último elemento
                elif isinstance(content, list) and content:
                    last = content[-1]
                    if isinstance(last, str):
                        user_msg = last.strip()
                    elif isinstance(last, dict):
                        user_msg = last.get("text", "").strip()
                if user_msg:
                    log.debug(f"[compat] extracted: {user_msg[:100]}")
                    break

        if not user_msg:
            log.debug("[compat] no user message (OpenClaw initialization?), returning empty content")
            return JSONResponse(
                status_code=200,
                content={
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": body.get("model", "jarvis"),
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "stop"
                    }],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                },
                media_type="application/json; charset=utf-8"
            )

        try:
            response, intent = process(user_msg)
        except Exception as inner_err:
            log.error(f"[compat] process() failed: {inner_err}", exc_info=True)
            response = f"Procesamiento falló: {str(inner_err)}"

        return JSONResponse(
            status_code=200,
            content={
                "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body.get("model", "jarvis"),
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": response},
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            },
            media_type="application/json; charset=utf-8"
        )
    except Exception as e:
        error_msg = str(e)
        log.error(f"[compat] exception: {error_msg}", exc_info=True)
        return JSONResponse(
            status_code=200,
            content={
                "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "jarvis",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": error_msg},
                    "finish_reason": "error"
                }],
                "error": error_msg,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            },
            media_type="application/json; charset=utf-8"
        )


@router.get("/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": "jarvis", "object": "model", "created": 0, "owned_by": "local"}]
    }