"""
core/agent.py
Tool-calling agent. Provider selection lives in core/llm_router.py.
"""
import json
import logging

from core.llm import SYSTEM_PROMPT
from core.llm_types import LLMRequest
from core import llm_router as router
from core.tools import TOOLS, call_tool

log = logging.getLogger("jarvis.agent")

MAX_TOOL_ROUNDS = 4


def _clean_assistant_message(message: dict) -> dict:
    """Deja solo los campos estandar antes de reenviar el historial.
    Groq (gpt-oss) devuelve un campo 'reasoning' que llama-3.3 rechaza con 400
    ("messages[N].reasoning is not supported") y que Ollama tampoco entiende.
    Como el router puede cambiar de proveedor entre rondas, el historial debe
    ser siempre el minimo comun: role, content y tool_calls normalizados."""
    clean = {"role": "assistant", "content": message.get("content") or ""}
    tool_calls = message.get("tool_calls")
    if tool_calls:
        clean["tool_calls"] = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"].get("arguments") or "{}",
                },
            }
            for tc in tool_calls
        ]
    return clean


def run(user_prompt: str) -> str:
    """
    Loop de tool-calling. Devuelve la respuesta final en texto plano.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    for round_n in range(MAX_TOOL_ROUNDS):
        message = router.chat_tools(LLMRequest(prompt=messages, tools=TOOLS))
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            return message.get("content", "") or "No obtuve respuesta del modelo."

        messages.append(_clean_assistant_message(message))

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
