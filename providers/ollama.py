import json
import time

import requests

from config.settings import settings
from core.llm_types import ProviderResult
from providers.base import BaseProvider, raise_with_body


class OllamaProvider(BaseProvider):
    name = "ollama"
    supports_tools = True
    supports_stream = True

    def chat(self, request):
        from core.llm import build_prompt

        started = time.monotonic()
        try:
            response = requests.post(
                settings.OLLAMA_URL,
                json={
                    "model": request.model,
                    "prompt": build_prompt(request.prompt, request.rag),
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
            return ProviderResult(
                self.name,
                request.model,
                True,
                time.monotonic() - started,
                response.json()["response"],
                None,
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

    def chat_tools(self, request):
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
            return ProviderResult(
                self.name,
                request.model,
                True,
                time.monotonic() - started,
                response.json()["message"],
                None,
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
