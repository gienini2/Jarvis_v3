"""Prueba del tool-calling emulado (core/tool_emulation.py) y del proveedor Ollama (nativo vs emulado).
Ejecutar: python tests/test_emulacion.py     (simula las respuestas de Ollama: no carga ningun modelo)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from core import tool_emulation as te
from core.llm_types import LLMRequest
from providers import ollama as ollama_mod

checks = []


def check(name, ok):
    checks.append(ok)
    print(f"  [{'OK' if ok else 'FALLO'}] {name}")


TOOLS = [
    {"type": "function", "function": {"name": "add_task", "description": "Anade una tarea",
                                      "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "text": {"type": "string"}, "priority": {"type": "string"}},
                                                     "required": ["project", "text"]}}},
    {"type": "function", "function": {"name": "query_tasks", "description": "Lista tareas", "parameters": {"type": "object", "properties": {"project": {"type": "string"}}}}},
]

print("Interpretar la respuesta del modelo")
calls, text = te.parse_tool_calls('<tool_call>{"name": "query_tasks", "arguments": {"project": "web"}}</tool_call>')
check("etiqueta <tool_call> normal", calls == [{"function": {"name": "query_tasks", "arguments": {"project": "web"}}}] and text == "")
calls, _ = te.parse_tool_calls('<tool_call>{"name": "query_tasks", "arguments": {}}</tool_call>\n<tool_call>{"name": "add_task", "arguments": {"project": "p", "text": "t"}}</tool_call>')
check("varias llamadas, una por linea", [c["function"]["name"] for c in calls] == ["query_tasks", "add_task"])
calls, _ = te.parse_tool_calls('```json\n{"name": "query_tasks", "arguments": {"project": "x"}}\n```')
check("JSON en bloque de codigo, sin etiqueta", len(calls) == 1 and calls[0]["function"]["arguments"] == {"project": "x"})
calls, _ = te.parse_tool_calls('{"name": "add_task", "parameters": {"project": "a", "text": "b {con llaves}"}}')
check("JSON suelto con 'parameters' y llaves dentro de un texto", len(calls) == 1 and calls[0]["function"]["arguments"]["text"] == "b {con llaves}")
calls, _ = te.parse_tool_calls('<tool_call>{"name": "query_tasks", "arguments": "{\\"project\\": \\"z\\"}"}</tool_call>')
check("argumentos como cadena JSON", calls and calls[0]["function"]["arguments"] == {"project": "z"})
calls, text = te.parse_tool_calls("Claro, tienes 3 tareas: la del banco, la del dentista y la del seguro. Un ejemplo de JSON seria {\"a\": 1}.")
check("una respuesta normal con un JSON de ejemplo NO es una llamada", calls == [] and "tienes 3 tareas" in text)
calls, text = te.parse_tool_calls("<tool_call>{esto no es json}</tool_call>")
check("JSON roto dentro de la etiqueta: no inventa una llamada", calls == [])
calls, text = te.parse_tool_calls("")
check("respuesta vacia", calls == [] and text == "")

print("Convertir el historial")
prompt = te.tools_prompt(TOOLS)
check("la lista de herramientas marca los parametros obligatorios con *", "add_task(project*: string, text*: string, priority: string)" in prompt)
history = [
    {"role": "system", "content": "Eres Jarvis."},
    {"role": "user", "content": "añade tarea"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "add_task", "arguments": '{"project": "web", "text": "x"}'}}]},
    {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'},
]
plain = te.to_plain_messages(history, TOOLS)
check("el prompt de sistema recibe las herramientas", plain[0]["role"] == "system" and "Eres Jarvis." in plain[0]["content"] and "HERRAMIENTAS" in plain[0]["content"])
check("la llamada previa del asistente pasa a texto <tool_call>", "<tool_call>" in plain[2]["content"] and '"project": "web"' in plain[2]["content"])
check("el resultado de la herramienta pasa a un mensaje de usuario con su nombre", plain[3]["role"] == "user" and "[Resultado de add_task]" in plain[3]["content"])
check("no queda ningun rol 'tool' (los modelos sin plantilla no lo entienden)", all(m["role"] != "tool" for m in plain))
check("sin mensaje de sistema, se crea uno", te.to_plain_messages([{"role": "user", "content": "hola"}], TOOLS)[0]["role"] == "system")

print("Proveedor Ollama")


class Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.reason, self.text = data, status, "x", json.dumps(data)

    def json(self):
        return self._data


sent = []
state = {"caps": ["completion", "tools"], "content": "", "native_error": False}


def fake_post(url, json=None, **kw):
    if url.endswith("/api/show"):
        return Resp({"capabilities": state["caps"]})
    sent.append(json)
    if "tools" in json and state["native_error"]:
        return Resp({"error": "registry.ollama.ai/library/x does not support tools"}, 400)
    msg = {"role": "assistant", "content": state["content"]}
    if "tools" in json:
        msg["tool_calls"] = [{"function": {"name": "query_tasks", "arguments": {}}}]
    return Resp({"message": msg, "prompt_eval_count": 10, "eval_count": 5})


requests.post = fake_post
ollama_mod._TOOL_SUPPORT.clear()
provider = ollama_mod.OllamaProvider()
request = LLMRequest(prompt=[{"role": "system", "content": "S"}, {"role": "user", "content": "qué tareas tengo"}], tools=TOOLS, model="qwen-falso:7b")

result = provider.chat_tools(request)
check("modelo con herramientas nativas: se envian 'tools' y se devuelve su mensaje tal cual", result.success and "tools" in sent[-1] and result.response["tool_calls"][0]["function"]["name"] == "query_tasks")

state["caps"] = ["completion"]
state["content"] = '<tool_call>{"name": "add_task", "arguments": {"project": "w", "text": "t"}}</tool_call>'
sent.clear()
result = provider.chat_tools(LLMRequest(prompt=request.prompt, tools=TOOLS, model="dolphin-falso:8b"))
check("modelo sin herramientas: NO se envian 'tools' y se emula", result.success and "tools" not in sent[-1] and "HERRAMIENTAS" in sent[-1]["messages"][0]["content"])
check("la llamada emulada llega al agente en el formato nativo", result.response["tool_calls"] == [{"function": {"name": "add_task", "arguments": {"project": "w", "text": "t"}}}])

state["content"] = "Hola, soy Jarvis."
result = provider.chat_tools(LLMRequest(prompt=request.prompt, tools=TOOLS, model="dolphin-falso:8b"))
check("sin llamada, devuelve el texto sin 'tool_calls'", result.response["content"] == "Hola, soy Jarvis." and "tool_calls" not in result.response)

state["caps"] = ["completion", "tools"]
state["native_error"] = True
state["content"] = '<tool_call>{"name": "query_tasks", "arguments": {}}</tool_call>'
ollama_mod._TOOL_SUPPORT.clear()
sent.clear()
result = provider.chat_tools(LLMRequest(prompt=request.prompt, tools=TOOLS, model="nuevo-falso:8b"))
check("si Ollama dice 'does not support tools', pasa solo a la emulacion y lo recuerda",
      result.success and result.response["tool_calls"][0]["function"]["name"] == "query_tasks" and ollama_mod._TOOL_SUPPORT["nuevo-falso:8b"] is False)

check("un modelo marcado tool_mode=emulated se emula aunque Ollama diga que tiene tools", ollama_mod.OllamaProvider._supports_tools("mistral:7b") is False)

print("Orden de los modelos locales por puntuacion")
import copy
import tempfile
from core import llm_router as router

scores_file = Path(tempfile.mkdtemp()) / "puntuaciones.json"
scores_file.write_text(json.dumps({"modelos": {"dolphin3:8b": 91, "qwen2.5:7b": 62, "mistral:7b": 20}}), encoding="utf-8")
cfg = copy.deepcopy(router._PROVIDERS_CONFIG)
router._apply_measured_scores(cfg, scores_file)
models = {m["name"]: m for m in cfg["ollama"]["models"]}
req = {"role": "tools", "tools": True}
power = {n: router._power_score(cfg["ollama"], m, req) for n, m in models.items() if n in ("dolphin3:8b", "qwen2.5:7b", "mistral:7b")}
check("para herramientas manda la puntuacion medida: dolphin > qwen > mistral", power["dolphin3:8b"] > power["qwen2.5:7b"] > power["mistral:7b"])
check("un modelo poco fiable (<40) se descarta para herramientas", "poco fiable" in router._discard_reason("ollama", cfg["ollama"], models["mistral:7b"], req, ignore_health=True))
check("pero sigue valiendo para charla sin herramientas", router._discard_reason("ollama", cfg["ollama"], models["mistral:7b"], {"role": "general"}, ignore_health=True) == "")
check("un modelo sin puntuacion conserva su prioridad fija", "measured_score" not in models["gemma3:latest"])

print(f"\nRESULTADO: {sum(checks)}/{len(checks)} comprobaciones OK")
sys.exit(0 if all(checks) else 1)
