"""Tool-calling por prompt para modelos que NO lo traen en su plantilla de Ollama (p. ej. dolphin3:8b).

Se describe la lista de herramientas en el prompt de sistema y se pide una linea
<tool_call>{"name": ..., "arguments": {...}}</tool_call> por llamada. La respuesta se traduce al mismo formato que
devuelve un modelo nativo (message con tool_calls), asi el agente no nota la diferencia.
"""
import json
import re

INSTRUCTIONS = (
    "Puedes usar herramientas. Para usar una, responde SOLO con una linea por herramienta, con este formato exacto y sin texto antes ni despues:\n"
    '<tool_call>{"name": "nombre_herramienta", "arguments": {"parametro": "valor"}}</tool_call>\n'
    "Usa solo herramientas de la lista y rellena los parametros obligatorios (marcados con *). "
    "Si no necesitas ninguna herramienta, responde normalmente en español.\nHERRAMIENTAS:\n"
)
_TAG = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def tools_prompt(tools: list) -> str:
    lines = []
    for tool in tools or []:
        fn = tool["function"]
        props = fn.get("parameters", {}).get("properties", {})
        required = set(fn.get("parameters", {}).get("required", []))
        params = ", ".join(f"{name}{'*' if name in required else ''}: {spec.get('type', 'string')}" for name, spec in props.items())
        lines.append(f"- {fn['name']}({params}): {fn.get('description', '')[:220]}")
    return INSTRUCTIONS + "\n".join(lines)


def _call_text(call: dict) -> str:
    fn = call.get("function", {})
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            args = {}
    return "<tool_call>" + json.dumps({"name": fn.get("name"), "arguments": args or {}}, ensure_ascii=False) + "</tool_call>"


def to_plain_messages(messages: list, tools: list) -> list:
    """Convierte el historial con tool_calls / role=tool a mensajes de texto que cualquier modelo entiende."""
    names_by_id = {}
    out = []
    injected = False
    for msg in messages:
        role = msg.get("role")
        if role == "system" and not injected:
            out.append({"role": "system", "content": (msg.get("content") or "") + "\n\n" + tools_prompt(tools)})
            injected = True
        elif role == "assistant" and msg.get("tool_calls"):
            for call in msg["tool_calls"]:
                names_by_id[call.get("id", "")] = call.get("function", {}).get("name", "herramienta")
            text = "\n".join(_call_text(c) for c in msg["tool_calls"])
            out.append({"role": "assistant", "content": ((msg.get("content") or "") + "\n" + text).strip()})
        elif role == "tool":
            name = names_by_id.get(msg.get("tool_call_id", ""), "herramienta")
            out.append({"role": "user", "content": f"[Resultado de {name}]\n{msg.get('content', '')}\n"
                                                    "Usa este resultado para responder al usuario (o llama otra herramienta si te falta algo)."})
        else:
            out.append({"role": role, "content": msg.get("content") or ""})
    if not injected:
        out.insert(0, {"role": "system", "content": tools_prompt(tools)})
    return out


def _as_call(obj) -> dict | None:
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or (obj.get("function") if isinstance(obj.get("function"), str) else None) or obj.get("tool")
    args = obj.get("arguments", obj.get("parameters", obj.get("args", {})))
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            return None
    if not isinstance(name, str) or not name or not isinstance(args, dict):
        return None
    return {"function": {"name": name, "arguments": args}}


def _first_json_object(text: str):
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\" and not esc)
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1]), start, i + 1
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None, -1, -1


def parse_tool_calls(content: str) -> tuple[list[dict], str]:
    """Devuelve (tool_calls, texto restante). Admite <tool_call>…</tool_call>, JSON suelto y JSON en bloque de codigo."""
    content = content or ""
    calls = []
    for raw in _TAG.findall(content):
        obj, _, _ = _first_json_object(raw)
        call = _as_call(obj)
        if call:
            calls.append(call)
    if calls:
        return calls, _TAG.sub("", content).strip()
    stripped = _FENCE.sub("", content.strip())
    obj, start, end = _first_json_object(stripped)
    call = _as_call(obj)
    if call and len(stripped[:start].strip()) + len(stripped[end:].strip()) < 20:
        return [call], ""
    return [], content.strip()
