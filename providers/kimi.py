import time

import requests

from config.settings import settings
from core.llm_types import ProviderResult
from providers.base import BaseProvider, raise_with_body


class KimiProvider(BaseProvider):
    """Moonshot / Kimi (API compatible con OpenAI). Contexto grande y limites
    generosos -> buen fallback cuando la peticion no cabe en el free de Groq."""

    name = "kimi"
    supports_tools = True

    def _headers(self):
        return {
            "Authorization": f"Bearer {settings.KIMI_API_KEY}",
            "Content-Type": "application/json",
        }

    def chat(self, request):
        from core.llm import build_prompt

        started = time.monotonic()
        try:
            response = requests.post(
                settings.KIMI_API_URL,
                headers=self._headers(),
                json={
                    "model": request.model,
                    "messages": [{"role": "user", "content": build_prompt(request.prompt, request.rag)}],
                    "temperature": settings.LLM_TEMPERATURE,
                    "max_tokens": settings.LLM_MAX_TOKENS,
                },
                timeout=(3.05, 60),   # mas lento que Groq; es el fallback de peticiones grandes
            )
            raise_with_body(response)
            text = response.json()["choices"][0]["message"]["content"]
            return ProviderResult(self.name, request.model, True, time.monotonic() - started, text, None)
        except Exception as exc:
            return ProviderResult(self.name, request.model, False, time.monotonic() - started, None, exc)

    def chat_tools(self, request):
        started = time.monotonic()
        payload = {
            "model": request.model,
            "messages": request.prompt,
            "tools": request.tools,
            "tool_choice": "auto",
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
        }
        try:
            response = requests.post(
                settings.KIMI_API_URL,
                headers=self._headers(),
                json=payload,
                timeout=(3.05, 60),
            )
            raise_with_body(response)
            message = response.json()["choices"][0]["message"]
            return ProviderResult(self.name, request.model, True, time.monotonic() - started, message, None)
        except requests.RequestException as exc:
            return ProviderResult(self.name, request.model, False, time.monotonic() - started, None, exc)

    def health(self):
        if not settings.KIMI_API_KEY:
            return False
        response = requests.get(
            settings.KIMI_API_URL.replace("/chat/completions", "/models"),
            headers=self._headers(),
            timeout=10,
        )
        raise_with_body(response)
        return True
