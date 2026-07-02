"""
core/agent.py
Fase 1 del tool-calling (ver docs/adr/0001-tool-calling-architecture.md).

El LLM decide que herramienta llamar en vez de un clasificador de reglas
(core/intent.py). Motor de decision: NVIDIA NIM (llama-3.3-70b-instruct)
primero, qwen2.5 local (Ollama) si NVIDIA falla o no hay internet -- decision
explicita de Juan Pablo, independiente del orden Groq->NVIDIA->Ollama que usa
core/llm.py para el chat general sin herramientas.

Este modulo es NUEVO y NO esta enchufado todavia a api/main.py / core/processor.py.
Es Fase 1 (solo herramientas de lectura, core/tools.py) pensado para probarse en
paralelo antes de decidir si sustituye o convive con el flujo actual basado en
intents. Ver Action Items del ADR.
"""
import json
import logging
import time
import requests

from config.settings import settings
from core.tools import TOOLS, call_tool
from core.llm import SYSTEM_PROMPT

log = logging.getLogger("jarvis.agent")

MAX_TOOL_ROUNDS = 4


def _raise_with_body(r: requests.Response):
    """requests.raise_for_status() no incluye el cuerpo de la respuesta en el
    mensaje de error -- sin esto es imposible saber POR QUE Ollama/NVIDIA
    rechazaron el request (ej: 400 Bad Request no dice que campo esta mal)."""
    if r.status_code >= 400:
        raise requests.HTTPError(f"{r.status_code} {r.reason} -- body: {r.text[:1000]}", response=r)


def _nvidia_chat(messages: list[dict], tools: list[dict]) -> dict:
    headers = {
        "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.NVIDIA_MODEL_GENERAL,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": settings.LLM_TEMPERATURE,
        "max_tokens": settings.LLM_MAX_TOKENS,
    }
    last_err = None
    for attempt in range(2):  # 1 reintento -- 503 en el tier gratis de NIM suele ser transitorio
        try:
            r = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=90,
            )
            if r.status_code == 503 and attempt == 0:
                log.warning("NVIDIA 503 (servicio saturado, no es problema de API key) -- reintentando en 3s")
                time.sleep(3)
                continue
            _raise_with_body(r)
            return r.json()["choices"][0]["message"]
        except requests.RequestException as e:
            last_err = e
    raise last_err


def _ollama_chat(messages: list[dict], tools: list[dict]) -> dict:
    """
    Fallback offline. qwen2.5:7b soporta 'tools' via /api/chat de Ollama (formato
    tipo OpenAI), pero al ser un modelo de 7B sin fine-tuning especifico de tools
    falla mas formando argumentos JSON validos que llama-3.3-70b -- tratar sus
    tool_calls con mas cautela. Medir tasa de fallo real (Action Item del ADR)
    antes de confiar en este camino sin supervision.
    """
    chat_url = settings.OLLAMA_URL.replace("/api/generate", "/api/chat")
    r = requests.post(
        chat_url,
        json={
            "model": settings.MODEL,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {
                "num_gpu": 99,
                "num_ctx": settings.OLLAMA_NUM_CTX,
                "temperature": settings.LLM_TEMPERATURE,
            },
        },
        timeout=settings.TIMEOUT,
    )
    _raise_with_body(r)
    return r.json()["message"]


def _call_llm(messages: list[dict], tools: list[dict]) -> dict:
    if settings.NVIDIA_API_KEY:
        try:
            return _nvidia_chat(messages, tools)
        except Exception as e:
            log.warning(f"NVIDIA fallo en tool-calling: {e} -- usando qwen2.5 local")
    return _ollama_chat(messages, tools)


def run(user_prompt: str) -> str:
    """
    Loop de tool-calling. Devuelve la respuesta final en texto plano.
    Fase 1: todas las TOOLS son de solo lectura -- ningun tool_call puede
    modificar el Centro de Mando, Google, ni el codigo de Jarvis.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    for round_n in range(MAX_TOOL_ROUNDS):
        message = _call_llm(messages, TOOLS)
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            return message.get("content", "") or "No obtuve respuesta del modelo."

        messages.append(message)

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            raw_args = tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            log.info(f"[agent] ronda={round_n} tool={fn_name} args={args}")
            result = call_tool(fn_name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", fn_name),
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

    return "Me quede sin vueltas resolviendo esto -- demasiadas herramientas encadenadas. Prueba a pedirlo mas concreto."
