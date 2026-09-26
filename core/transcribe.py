"""
core/transcribe.py
Transcribe audio (notas de voz) a texto con Whisper en Groq.

Se usa desde core/attachments.py cuando llega un adjunto de audio, igual que
core/vision.py describe imagenes: el audio se convierte a texto ANTES de llegar
al LLM, asi el agente/chat lo trata como un mensaje de texto normal.

Groq sirve whisper-large-v3(-turbo) por el endpoint OpenAI-compatible
/audio/transcriptions. Modelo configurable en settings.GROQ_WHISPER_MODEL.
"""
import io
import logging

import requests

from config.settings import settings

log = logging.getLogger("jarvis.transcribe")

_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def transcribe(data: bytes, filename: str = "audio.ogg", language: str | None = "es") -> str:
    """Devuelve el texto transcrito. `language` fija el idioma (mejora la precision
    en audios cortos); None deja que Whisper lo autodetecte. Lanza si falla la API."""
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY no configurada; no puedo transcribir audio.")

    payload = {"model": settings.GROQ_WHISPER_MODEL, "response_format": "text"}
    if language:
        payload["language"] = language

    response = requests.post(
        _URL,
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        files={"file": (filename, io.BytesIO(data))},
        data=payload,
        timeout=(3.05, 60),
    )
    response.raise_for_status()
    # response_format=text -> el cuerpo es el texto plano transcrito.
    return response.text.strip()
