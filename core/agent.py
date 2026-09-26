"""
core/agent.py
Tool-calling agent. Provider selection lives in core/llm_router.py.
"""
import json
import logging

from core.llm_types import LLMRequest
from core import llm_router as router
from core.tools import TOOLS, call_tool

log = logging.getLogger("jarvis.agent")

MAX_TOOL_ROUNDS = 6   # margen para peticiones multi-paso (varios borrados/cambios encadenados)
MAX_TOOL_RESULT_CHARS = 12000   # red de seguridad; search_memory devuelve recuerdos enteros

# Prompt COMPACTO para el tool-calling. El SYSTEM_PROMPT largo de core/llm.py
# (~1000 tokens) + las 17 tools (~2700) hacian que cada peticion superara los
# 8000 tokens/min del tier gratis de Groq -> 413/429, caida al modelo local y
# tareas inventadas. Aqui va lo minimo: quien es, que use las tools y no invente,
# y cuidado con las acciones reales.
AGENT_SYSTEM_PROMPT = (
    "Eres Jarvis, asistente personal de Juan Pablo (Juanpa), local-first en su PC.\n"
    "REGLA #1, INQUEBRANTABLE: NO te inventes NADA. Todo dato concreto (tareas, correos, "
    "eventos, cifras, nombres, fechas, rutas) DEBE venir de una herramienta o del contexto "
    "de esta conversacion. Si no lo has obtenido de una tool, NO lo afirmes. Ante la duda, "
    "llama a la herramienta; si no devuelve nada o falla, dilo tal cual ('no encontre...', "
    "'no pude consultarlo') en vez de rellenar con algo que suene plausible. Vale mil veces "
    "mas un 'no lo se' que un dato inventado. Esto va por encima de sonar util o completo.\n"
    "Herramientas para datos reales: tareas del Centro de Mando, correos (Gmail), calendario, "
    "Drive, memoria de conversaciones pasadas, entrenos de Alpha50, escaneo de red, auditorias.\n"
    "MEMORIA: si te pide recordar/guardar algo 'en tu memoria', usa remember (NO add_task: el "
    "Centro de Mando es solo para tareas). Para recuperarlo, search_memory. Si te pide que "
    "responder a una pregunta de entrevista, busca con search_memory(source='entrevista') y "
    "basa la respuesta en sus experiencias reales guardadas ahi.\n"
    "Enviar correo/Telegram y editar codigo tienen efecto inmediato: reune todo lo necesario "
    "(destinatario, asunto, cuerpo; ruta e instruccion) antes de llamar; si falta un dato, "
    "preguntalo primero.\n"
    "Si habla de entrenar, eres su coach de Alpha50: usa query_alpha50_history para el plan y "
    "los dias hechos, y repaso_entrenos para las metricas reales de Garmin (km, FC, VO2max, "
    "fuerza). El plan manda; registra lo que hace de verdad y echale la bronca si no cumple, "
    "pero siempre con datos, sin inventar.\n"
    "ADJUNTOS: los archivos te llegan YA convertidos a texto, entre '[Archivo adjunto: nombre]' "
    "y '[Fin del archivo]'. Si es una imagen, ese texto es una DESCRIPCION hecha por un modelo de "
    "vision: usala como si hubieras visto la imagen y responde a partir de ella. NUNCA digas que "
    "no puedes ver ni analizar imagenes -- si hay descripcion, si puedes.\n"
    "Responde en castellano, directo y sin relleno; algun emoji esta bien."
)


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


def _recent_history() -> list[dict]:
    """Ultimos turnos de conversacion como mensajes role/content. El agente es
    el camino por defecto de todas las interfaces; sin esto, los follow-ups
    ('y la segunda?', 'cambiale la prioridad a esa') perdian todo el contexto."""
    try:
        from core.memory import get_recent_messages
        rows = get_recent_messages(limit=6)
    except Exception:
        return []
    return [
        {"role": role, "content": msg}
        for role, msg, _ts in rows
        if role in ("user", "assistant")
    ]


def run(user_prompt: str) -> str:
    """
    Loop de tool-calling. Devuelve la respuesta final en texto plano.
    """
    messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    messages.extend(_recent_history())
    # processor.py guarda el mensaje del usuario ANTES de invocar al agente, asi
    # que puede venir ya como ultimo item del historial -- evitar duplicarlo.
    if not (messages[-1]["role"] == "user" and messages[-1]["content"] == user_prompt):
        messages.append({"role": "user", "content": user_prompt})

    executed = []
    for round_n in range(MAX_TOOL_ROUNDS):
        message = router.chat_tools(LLMRequest(prompt=messages, tools=TOOLS))
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            return message.get("content", "") or "No obtuve respuesta del modelo."

        # Ollama no pone 'id' en sus tool_calls; Groq/NVIDIA si. Si una ronda la
        # resuelve Ollama y la siguiente cambia a un provider OpenAI-estricto, el
        # request petaba porque el mensaje 'tool' no referenciaba ningun
        # tool_call (id vacio) y varios ids vacios colisionaban. Fijamos un id
        # estable aqui y lo usamos igual en el assistant y en el resultado.
        for i, tc in enumerate(tool_calls):
            if not tc.get("id"):
                tc["id"] = f"call_{round_n}_{i}"

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
            executed.append(fn_name)
            content = json.dumps(result, ensure_ascii=False, default=str)
            if len(content) > MAX_TOOL_RESULT_CHARS:
                content = content[:MAX_TOOL_RESULT_CHARS] + " …(resultado truncado)"
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": content,
            })

    # Se agotaron las rondas con la ultima aun pidiendo tools: en vez de tirar
    # todo lo recogido, una llamada final para que el modelo redacte la
    # respuesta con los resultados que ya tiene en `messages`.
    try:
        final = router.chat_tools(LLMRequest(prompt=messages, tools=TOOLS))
        content = final.get("content")
        if content:
            return content
    except Exception as e:
        log.warning(f"[agent] llamada final de sintesis fallo: {e}")

    hechas = ", ".join(dict.fromkeys(executed))
    extra = f" Hasta aqui hice: {hechas}." if hechas else ""
    return (
        "La peticion necesitaba mas pasos de los que hago de una vez." + extra +
        " Dime si sigo, o pidelo mas concreto (p.ej. 'vacia el proyecto X de golpe')."
    )
