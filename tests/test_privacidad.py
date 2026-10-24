"""Prueba de la privacidad: modo privado y contenido privado solo al modelo local y sin guardarse.
Ejecutar: python tests/test_privacidad.py
Usa proveedores FALSOS (no llama a ninguna API), una herramienta privada inventada y una bandera temporal
(no toca tu modo privado real).
"""
import json
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import agent, llm_router as router, privacy
from core.llm_types import LLMRequest, ProviderResult

SECRET = "CONTENIDO-SECRETO-DEL-CHAT"
checks = []
privacy.FLAG = Path(tempfile.mkdtemp()) / "modo_privado.flag"


def check(name, ok):
    checks.append(ok)
    print(f"  [{'OK' if ok else 'FALLO'}] {name}")


class Fake:
    def __init__(self, name, script):
        self.name, self.script, self.seen = name, list(script), []

    def chat_tools(self, request):
        self.seen.append(json.dumps(request.prompt, ensure_ascii=False))
        step = self.script.pop(0) if self.script else {"content": f"respuesta de {self.name}"}
        return ProviderResult(self.name, request.model, True, 0.1, step, None, {"in": 1, "out": 1})

    chat = chat_tools


def tool_call(name):
    return {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": "{}"}}]}


def setup(groq_script=(), ollama_script=()):
    groq, ollama = Fake("groq", groq_script), Fake("ollama", ollama_script)
    router.PROVIDERS.update({"groq": groq, "ollama": ollama, "nvidia": Fake("nvidia", [])})
    agent._recent_history = lambda: []
    agent._pick = lambda prompt, prev, turn: (agent.TOOLS, agent.AGENT_SYSTEM_PROMPT)
    agent.call_tool = lambda name, args: {"_privado": True, "texto": SECRET} if name == "leer_chat_falso" else {"ok": True}
    if not any(t["function"]["name"] == "leer_chat_falso" for t in agent.TOOLS):
        agent.TOOLS.append({"type": "function", "function": {"name": "leer_chat_falso", "description": "x", "parameters": {"type": "object", "properties": {}}}})
    privacy.reset()
    return groq, ollama


print("Router")
cloud = router._discard_reason("groq", {"enabled": True}, {"roles": ["tools"], "tools": True}, {"role": "tools", "tools": True, "local_only": True})
local = router._discard_reason("ollama", {"enabled": True}, {"roles": ["tools"], "tools": True}, {"role": "tools", "tools": True, "local_only": True})
check("local_only descarta a la nube y deja a Ollama", cloud != "" and local == "")
privacy.force_local(True)
check("el modo forzado entra solo en los requisitos de TODA llamada", router._requirements_from_request(LLMRequest(prompt="x")).get("local_only") is True)
privacy.reset()
check("sin forzar, no se exige local", not router._requirements_from_request(LLMRequest(prompt="x")).get("local_only"))

print("Herramienta privada")
groq, ollama = setup([tool_call("leer_chat_falso")], [{"content": "resumen local"}])
answer = agent.run("resume mi chat")
check("el resto del turno lo responde el modelo local", answer == "resumen local")
check("la nube NO vio nunca el contenido privado", all(SECRET not in s for s in groq.seen))
check("el modelo local SI recibio el contenido", any(SECRET in s for s in ollama.seen))
check("el turno queda marcado como privado y luego se limpia", privacy.pop_private() is True and privacy.pop_private() is False)

groq, ollama = setup([{"content": "hola desde la nube"}])
check("un turno normal sigue usando la nube", agent.run("hola") == "hola desde la nube" and ollama.seen == [] and not privacy.is_private_turn())

groq, ollama = setup([tool_call("leer_chat_falso"), {"content": "NO DEBERIA LLEGAR"}])
ollama.chat_tools = lambda request: ProviderResult("ollama", request.model, False, 0.1, None, RuntimeError("ollama caido"), None)
try:
    agent.run("resume mi chat")
    raised = False
except Exception:
    raised = True
check("con Ollama caido falla y NO se reintenta en la nube", raised and all(SECRET not in s for s in groq.seen))

print("Modo privado (procesador)")
import core.processor as proc
sys.modules["alpha50.scheduler"] = types.SimpleNamespace(alpha50_intent_handler=lambda m: None)
saved, stored, logged = [], [], []
proc._save_message_safely = lambda role, msg: saved.append((role, msg))
proc._log_intent = lambda message, *a, **k: logged.append(message)
proc.store_memory_chunks = lambda *a, **k: stored.append(a)
import core.code_mode as cm
cm.code_intent_handler = lambda m: None

text, kind = proc.process("modo privado")
check("'modo privado' lo activa y lo confirma", "Modo privado activado" in text and privacy.mode_on() and kind == "privacidad")
check("'/privado?' informa del estado", "ACTIVADO" in proc.process("/privado?")[0])
groq, ollama = setup()
saved.clear(); stored.clear(); logged.clear()
response, kind = proc.process("cuéntame un secreto de prueba")
time.sleep(.3)
check("con el modo activo la nube NO se llama y responde el local", groq.seen == [] and ollama.seen != [] and "respuesta de ollama" in response)
check("la respuesta lleva el candado", response.startswith("[🔒"))
check("no se guarda el mensaje ni la respuesta (solo marcadores)", saved == [("user", privacy.PLACEHOLDER_USER), ("assistant", privacy.PLACEHOLDER)])
check("no se guarda en la memoria (RAG) ni en el registro de intents con el texto", stored == [] and all(m == privacy.PLACEHOLDER_USER for m in logged))
text, _ = proc.process("modo normal")
check("'modo normal' lo desactiva", "desactivado" in text and not privacy.mode_on())

print("Un solo mensaje privado")
for prefix in ("/privado ", "privado: "):
    groq, ollama = setup()
    saved.clear()
    response, _ = proc.process(prefix + "pregunta delicada")
    check(f"'{prefix.strip()}' aplica solo a ese mensaje (local, sin guardar)", groq.seen == [] and ollama.seen != [] and not privacy.mode_on() and ("assistant", privacy.PLACEHOLDER) in saved)
groq, ollama = setup()
saved.clear(); stored.clear()
response, _ = proc.process("pregunta normal despues")
time.sleep(.3)
check("el siguiente mensaje vuelve a ser normal (nube, se guarda)", groq.seen != [] and not response.startswith("[🔒") and len(stored) == 1 and ("assistant", "respuesta de groq") in saved)

print("Voz y confirmaciones")
from core import transcribe as tr
privacy.set_mode(True)
try:
    tr.transcribe(b"x")
    blocked = False
except RuntimeError as e:
    blocked = "Modo privado" in str(e)
privacy.set_mode(False)
check("la transcripcion de voz (Groq) se bloquea en modo privado", blocked)

print(f"\nRESULTADO: {sum(checks)}/{len(checks)} comprobaciones OK")
privacy.set_mode(False)
sys.exit(0 if all(checks) else 1)
