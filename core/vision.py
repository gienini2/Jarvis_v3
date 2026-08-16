"""
core/vision.py
Describe una imagen con el mejor modelo de vision disponible, POR EL ROUTER
(misma cascada que el texto: Groq -> NVIDIA -> gemma3 local). No habla con
ningun proveedor a mano: monta un LLMRequest con images y deja que
core/llm_router elija -- al detectar images, el router exige rol 'vision'.

Es la version de produccion de lo que se prototipo en
sandbox/attachment_extractors_sandbox.py.
"""
import base64
import logging
import re

from core import llm_router
from core.llm_types import LLMRequest

log = logging.getLogger("jarvis.vision")

PROMPT_DEFECTO = (
    "Responde SIEMPRE en espanol. Describe en detalle lo que se ve en la imagen. "
    "Si hay texto, transcribelo literalmente."
)


def describe(data: bytes, prompt: str = PROMPT_DEFECTO) -> str:
    """`data` = bytes de la imagen. Devuelve la descripcion del modelo de vision.
    Lanza si ningun modelo con vision responde (lo captura quien llame)."""
    b64 = base64.b64encode(data).decode()
    request = LLMRequest(prompt=prompt, intent="vision", images=[b64])
    response = llm_router.chat(request)
    log.info(f"[vision] descrita imagen ({len(data)} bytes) via {response.provider}/{response.model}")
    # Modelos "thinking" (qwen, etc.) anteponen <think>...</think>: fuera, que al
    # chat le llegue solo la descripcion.
    return re.sub(r"^\s*<think>.*?</think>\s*", "", response.text, flags=re.DOTALL).strip()
