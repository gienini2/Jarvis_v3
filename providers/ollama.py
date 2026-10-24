import json
import time
from pathlib import Path

import requests

from config.settings import settings
from core import tool_emulation
from core.llm_types import ProviderResult
from providers.base import BaseProvider, raise_with_body, usage_from


_TOOL_SUPPORT: dict[str, bool] = {}
_PROVIDERS_JSON = Path(__file__).resolve().parents[1] / "config" / "providers.json"


def _forced_emulation() -> set[str]:
    """Modelos que dicen tener 'tools' pero no las llaman (p. ej. mistral:7b): providers.json -> "tool_mode": "emulated"."""
    models = json.loads(_PROVIDERS_JSON.read_text(encoding="utf-8"))["providers"].get("ollama", {}).get("models", [])
    return {m["name"] for m in models if m.get("tool_mode") == "emulated"}


class OllamaProvider(BaseProvider):
    name = "ollama"
    supports_tools = True
    supports_stream = True

    def chat(self, request):
        from core.llm import build_prompt

        started = time.monotonic()
        images = getattr(request, "images", None)
        payload = {
            "model": request.model,
            "prompt": request.prompt if images else build_prompt(request.prompt, request.rag),
            "stream": False,
            "options": {
                "num_gpu": 99,
                "num_ctx": settings.OLLAMA_NUM_CTX,
                "temperature": settings.LLM_TEMPERATURE,
            },
        }
        if images:
            payload["images"] = images  # gemma3 lee la imagen desde base64
        try:
            response = requests.post(
                settings.OLLAMA_URL,
                json=payload,
                timeout=settings.TIMEOUT,
            )
            raise_with_body(response)
            data = response.json()
            return ProviderResult(
                self.name,
                request.model,
                True,
                time.monotonic() - started,
                data["response"],
                None,
                usage_from(data),
            )
        except Exception as exc:
            return ProviderResult(self.name, request.model, False, time.monotonic() - started, None, exc)

    @staticmethod
    def _adapt_messages(messages):
        """Ollama /api/chat espera tool_calls.function.arguments como objeto,
        no como string JSON (formato OpenAI que devuelven Groq/NVIDIA).
        Si llega como string, Ollama responde 400 "Value looks like object,
        but can't find closing '}' symbol"."""
        adapted = []
        for msg in messages:
            if isinstance(msg, dict) and msg.get("tool_calls"):
                msg = dict(msg)
                calls = []
                for tc in msg["tool_calls"]:
                    fn = dict(tc.get("function", {}))
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            fn["arguments"] = json.loads(args or "{}")
                        except json.JSONDecodeError:
                            fn["arguments"] = {}
                    calls.append({**tc, "function": fn})
                msg["tool_calls"] = calls
            adapted.append(msg)
        return adapted

    @staticmethod
    def _supports_tools(model: str) -> bool:
        """Capacidad 'tools' del modelo segun Ollama (cacheada). Si no se puede saber, se intenta el camino nativo."""
        if model in _forced_emulation():
            return False
        if model not in _TOOL_SUPPORT:
            try:
                response = requests.post(settings.OLLAMA_URL.replace("/api/generate", "/api/show"), json={"model": model}, timeout=10)
                caps = response.json().get("capabilities") if response.status_code == 200 else None
            except Exception:
                return True
            if caps is None:
                return True
            _TOOL_SUPPORT[model] = "tools" in caps
        return _TOOL_SUPPORT[model]

    def chat_tools(self, request):
        if not self._supports_tools(request.model):
            return self._chat_emulated(request)
        result = self._chat_native(request)
        if not result.success and "does not support tools" in str(result.exception):
            _TOOL_SUPPORT[request.model] = False
            return self._chat_emulated(request)
        return result

    def _chat_emulated(self, request):
        """Modelos sin plantilla de herramientas (p. ej. dolphin3): tool-calling por prompt (core/tool_emulation.py)."""
        started = time.monotonic()
        chat_url = settings.OLLAMA_URL.replace("/api/generate", "/api/chat")
        try:
            response = requests.post(
                chat_url,
                json={
                    "model": request.model,
                    "messages": tool_emulation.to_plain_messages(request.prompt, request.tools),
                    "stream": False,
                    "options": {"num_gpu": 99, "num_ctx": settings.OLLAMA_NUM_CTX, "temperature": settings.LLM_TEMPERATURE},
                },
                timeout=settings.TIMEOUT,
            )
            raise_with_body(response)
            data = response.json()
            calls, text = tool_emulation.parse_tool_calls(data["message"].get("content", ""))
            message = {"role": "assistant", "content": text}
            if calls:
                message["tool_calls"] = calls
            return ProviderResult(self.name, request.model, True, time.monotonic() - started, message, None, usage_from(data))
        except Exception as exc:
            return ProviderResult(self.name, request.model, False, time.monotonic() - started, None, exc)

    def _chat_native(self, request):
        started = time.monotonic()
        chat_url = settings.OLLAMA_URL.replace("/api/generate", "/api/chat")
        try:
            response = requests.post(
                chat_url,
                json={
                    "model": request.model,
                    "messages": self._adapt_messages(request.prompt),
                    "tools": request.tools,
                    "stream": False,
                    "options": {
                        "num_gpu": 99,
                        "num_ctx": settings.OLLAMA_NUM_CTX,
                        "temperature": settings.LLM_TEMPERATURE,
                    },
                },
                timeout=settings.TIMEOUT,
            )
            raise_with_body(response)
            data = response.json()
            return ProviderResult(
                self.name,
                request.model,
                True,
                time.monotonic() - started,
                data["message"],
                None,
                usage_from(data),
            )
        except Exception as exc:
            return ProviderResult(self.name, request.model, False, time.monotonic() - started, None, exc)

    def health(self):
        response = requests.get(
            settings.OLLAMA_URL.replace("/api/generate", "/api/tags"),
            timeout=5,
        )
        raise_with_body(response)
        return True
