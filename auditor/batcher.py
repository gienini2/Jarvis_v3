"""
auditor/batcher.py — Lotes adaptativos: GET /api/show → context_length * 0.6
Agrupa archivos en lotes que caben en el contexto del modelo.
"""

import requests
from pathlib import Path

OLLAMA_BASE = "http://localhost:11434"
MODEL = "qwen2.5:7b"

# Estimación conservadora: 1 token ≈ 4 caracteres
CHARS_PER_TOKEN = 4

# Si Ollama no responde, fallback seguro
FALLBACK_CONTEXT = 32768


def get_model_context() -> int:
    """Consulta Ollama para saber el context_length real del modelo."""
    try:
        r = requests.post(f"{OLLAMA_BASE}/api/show", json={"name": MODEL}, timeout=5)
        data = r.json()
        # Ollama devuelve model_info con num_ctx o context_length
        ctx = (
            data.get("model_info", {}).get("llama.context_length")
            or data.get("parameters", {}).get("num_ctx")
            or FALLBACK_CONTEXT
        )
        return int(ctx)
    except Exception:
        return FALLBACK_CONTEXT


def read_file_safe(path: str) -> str:
    """Lee un archivo con fallback de encoding."""
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return Path(path).read_text(encoding=enc)
        except (UnicodeDecodeError, PermissionError):
            continue
    return f"[no se pudo leer: {path}]"


def make_batches(files: list[dict]) -> list[list[dict]]:
    """
    Divide la lista de archivos en lotes.
    Cada lote cabe en context_length * 0.6 tokens (60% = margen para prompt + respuesta).
    Cada archivo va con su contenido adjunto en el dict: file["content"].
    """
    ctx = get_model_context()
    max_chars = int(ctx * 0.6) * CHARS_PER_TOKEN

    # Leer contenidos y adjuntarlos
    enriched = []
    for f in files:
        content = read_file_safe(f["path"])
        enriched.append({**f, "content": content})

    batches = []
    current_batch = []
    current_chars = 0

    for f in enriched:
        size = len(f["content"])

        # Si un solo archivo supera el límite, va solo en su propio lote
        if size > max_chars:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            batches.append([f])
            continue

        if current_chars + size > max_chars:
            batches.append(current_batch)
            current_batch = [f]
            current_chars = size
        else:
            current_batch.append(f)
            current_chars += size

    if current_batch:
        batches.append(current_batch)

    return batches


def batch_prompt(batch: list[dict]) -> str:
    """
    Construye el prompt para un lote de archivos.
    Formato simple: bloque por archivo con separador claro.
    """
    parts = ["Analiza los siguientes archivos del repositorio Jarvis.\n"
             "Para cada archivo indica: propósito, problemas detectados (si los hay), "
             "dependencias clave. Sé conciso.\n"]

    for f in batch:
        parts.append(f"### {f['rel']}\n```\n{f['content']}\n```\n")

    return "\n".join(parts)
