"""
core/attachments.py
Extrae texto de un adjunto ANTES de que llegue al LLM.

Nace de un bug real: la UI web hacia readAsText() a cualquier archivo, asi que
un PDF entraba como bytes binarios (%PDF-..., streams PostScript) dentro del
prompt. El modelo, en vez de leer el contenido, respondia describiendo la
estructura de un PDF. Aqui convertimos los bytes en texto limpio.

Diseno: un registro por extension. Anadir un tipo = anadir una funcion y una
entrada en _EXTRACTORS. Los tipos "de imagen o asi" se estan prototipando en
sandbox/attachment_extractors_sandbox.py antes de promocionarlos aqui.
"""
import io
import logging

log = logging.getLogger("jarvis.attachments")

# Tope de texto que devolvemos: protege el contexto del LLM de un adjunto enorme.
MAX_CHARS = 200_000


class UnsupportedAttachment(Exception):
    """Tipo no soportado, o soportado pero sin texto extraible (p.ej. PDF escaneado)."""


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def extract_text(name: str, data: bytes) -> dict:
    """`name` da el tipo por su extension; `data` son los bytes crudos.
    Devuelve {name, kind, chars, text} o lanza UnsupportedAttachment."""
    ext = _ext(name)
    fn = _EXTRACTORS.get(ext)
    if not fn:
        raise UnsupportedAttachment(
            f"'{name}': tipo .{ext or '?'} no soportado todavia. "
            f"Soportados: {', '.join(sorted(set(_EXTRACTORS)))}."
        )
    text = (fn(data) or "")[:MAX_CHARS]
    return {"name": name, "kind": ext, "chars": len(text), "text": text}


# --- extractores por tipo ---------------------------------------------------

def _from_text(data: bytes) -> str:
    # utf-8 con reemplazo: nunca peta por un byte suelto raro.
    return data.decode("utf-8", errors="replace")


def _from_pdf(data: bytes) -> str:
    import pdfplumber  # en la whitelist de allowed_packages.json
    partes = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            partes.append(page.extract_text() or "")
    text = "\n".join(partes).strip()
    if not text:
        # Sin capa de texto (PDF escaneado, solo imagenes). Mejor avisar claro
        # que devolver "" y que el LLM se invente el contenido.
        raise UnsupportedAttachment(
            "El PDF no tiene texto extraible (parece escaneado). Haria falta OCR."
        )
    return text


_TEXT_EXTS = (
    "txt", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "log",
    "py", "js", "ts", "html", "css", "sql", "sh", "ini", "toml", "xml",
)

_EXTRACTORS = {ext: _from_text for ext in _TEXT_EXTS}
_EXTRACTORS["pdf"] = _from_pdf
