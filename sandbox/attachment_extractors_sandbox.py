"""
sandbox/attachment_extractors_sandbox.py
BANCO DE PRUEBAS (no en produccion) para extraer texto de otros tipos de
adjunto: imagenes, docx, xlsx... Extiende la misma idea del registro de
core/attachments.py, pero aqui se puede romper sin tocar Jarvis.

Por que existe: el fix de PDF (core/attachments.py) resolvio el bug del churro
binario. El siguiente paso natural son las imagenes (una foto de un cartel, un
diagrama, un PDF escaneado). Hay DOS caminos y conviene tenerlos separados:

    OCR      -> "que TEXTO hay en la imagen" (escaneos, capturas, carteles).
               Local y barato con Tesseract. No entiende, solo transcribe.
    VISION   -> "que DICE/HAY en la imagen" (fotos, diagramas, manuscrito).
               Necesita un modelo multimodal. Aqui se pide por el ROUTER de
               Jarvis (find_models con {"vision": true}): baja por la misma
               cascada que el texto -> Groq/NVIDIA (Llama 4) y, sin internet,
               gemma3 en Ollama. Entiende, describe, resume.

Regla practica: prueba OCR primero; si sale poco o nada de texto, es una foto
"de verdad" -> vision.

Como promocionar un handler a produccion:
  1. Anadir su dependencia a config/allowed_packages.json (pytesseract, Pillow,
     python-docx, openpyxl...) para que self_extend pueda instalarla.
  2. Copiar la funcion a core/attachments.py y registrarla en _EXTRACTORS.
  3. La UI (web/chat.html) ya manda al /extract cualquier archivo no-texto,
     asi que no hay que tocar el front.

Uso:  python -m sandbox.attachment_extractors_sandbox <archivo> [--vision]
"""
import io
import sys

# El "resultado" imita el de core.attachments.extract_text: {name, kind, chars, text}


# ---------------------------------------------------------------------------
# 1) IMAGEN via OCR (Tesseract) -- texto impreso/escaneado
# ---------------------------------------------------------------------------

def image_ocr(data: bytes, lang: str = "spa+eng") -> str:
    """Transcribe el texto de una imagen. Requiere: pip install pytesseract Pillow
    y el binario de Tesseract instalado en el sistema (con el idioma 'spa')."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return "[OCR no disponible: falta 'pytesseract' y/o 'Pillow' (pip install), ademas del binario Tesseract.]"
    try:
        img = Image.open(io.BytesIO(data))
        text = pytesseract.image_to_string(img, lang=lang).strip()
        return text or "[OCR no encontro texto: probablemente sea una foto sin letras -> usar vision.]"
    except Exception as e:
        return f"[OCR fallo: {e}]"


# ---------------------------------------------------------------------------
# 2) IMAGEN via VISION -- fotos, diagramas, manuscrito
#    Reusa el ROUTER de Jarvis: pide un modelo con {"vision": true} y baja por
#    la MISMA cascada que el texto (Groq -> NVIDIA -> gemma3 local). El "coche"
#    (Jarvis) elige el "motor" mas potente disponible; no hardcodeamos ninguno.
# ---------------------------------------------------------------------------

_VISION_PROMPT = ("Responde SIEMPRE en espanol. Describe en detalle que se ve en "
                  "esta imagen. Si hay texto, transcribelo literalmente.")


def _vision_openai(url: str, key: str, model: str, b64: str, prompt: str) -> str:
    """Groq y NVIDIA hablan formato OpenAI: la imagen viaja como image_url data-URI."""
    import requests
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
            "max_tokens": 1024,
        },
        timeout=(3.05, 120),
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _vision_ollama(model: str, b64: str, prompt: str) -> str:
    """Ollama /api/generate acepta la imagen en el campo images (fallback local)."""
    import requests
    from config.settings import settings
    r = requests.post(
        settings.OLLAMA_URL,  # .../api/generate
        json={"model": model, "prompt": prompt, "images": [b64], "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


def image_vision(data: bytes, prompt: str = _VISION_PROMPT) -> str:
    """Elige el mejor modelo con vision:true via el router y baja en cascada si
    falla. Reusa la seleccion (prioridad + salud) de core/llm_router; la imagen
    se envia aparte porque LLMRequest todavia no la transporta en produccion."""
    import base64
    from config.settings import settings
    from core import llm_router

    b64 = base64.b64encode(data).decode()
    try:
        # role="vision": el router exige rol; asi no forzamos a estos modelos al
        # enrutado de texto general (solo entran cuando se pide vision).
        candidatos = llm_router.find_models({"vision": True, "role": "vision"})
    except Exception as e:
        return f"[Vision: no pude consultar el router: {e}]"
    if not candidatos:
        return "[Vision: ningun modelo con vision:true en providers.json.]"

    errores = []
    for c in candidatos:
        prov, model = c["provider"], c["model"]
        try:
            if prov == "groq":
                txt = _vision_openai("https://api.groq.com/openai/v1/chat/completions",
                                     settings.GROQ_API_KEY, model, b64, prompt)
            elif prov == "nvidia":
                txt = _vision_openai("https://integrate.api.nvidia.com/v1/chat/completions",
                                     settings.NVIDIA_API_KEY, model, b64, prompt)
            elif prov == "ollama":
                txt = _vision_ollama(model, b64, prompt)
            else:
                errores.append(f"{prov}: sin adaptador de vision en el sandbox")
                continue
            if txt:
                return f"[vision: {prov}/{model}]\n{txt}"
            errores.append(f"{prov}/{model}: respuesta vacia")
        except Exception as e:
            errores.append(f"{prov}/{model}: {e}")
    return "[Vision fallo en toda la cascada]\n" + "\n".join(errores)


def image_smart(data: bytes) -> str:
    """auto: intenta OCR (local, barato, CPU); si saca poco texto es una foto de
    verdad -> vision por el router. Estrategia a promocionar para .png/.jpg."""
    txt = image_ocr(data)
    letras = sum(c.isalnum() for c in txt)
    if txt.startswith("[") or letras < 20:
        return f"[OCR dio poco -> vision]\n{image_vision(data)}"
    return txt


# ---------------------------------------------------------------------------
# 3) Office: docx / xlsx
# ---------------------------------------------------------------------------

def from_docx(data: bytes) -> str:
    try:
        import docx  # pip install python-docx
    except ImportError:
        return "[docx no disponible: pip install python-docx]"
    d = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in d.paragraphs if p.text.strip())


def from_xlsx(data: bytes) -> str:
    try:
        import openpyxl  # pip install openpyxl
    except ImportError:
        return "[xlsx no disponible: pip install openpyxl]"
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"# Hoja: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            celdas = [str(c) for c in row if c is not None]
            if celdas:
                out.append("\t".join(celdas))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Registro del sandbox (mismo patron que core/attachments._EXTRACTORS)
# ---------------------------------------------------------------------------

SANDBOX_EXTRACTORS = {
    "png":  image_smart, "jpg": image_smart, "jpeg": image_smart,
    "webp": image_smart, "tiff": image_smart, "bmp": image_smart,
    "docx": from_docx,
    "xlsx": from_xlsx,
}


def extract(name: str, data: bytes, force_vision: bool = False) -> dict:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if force_vision and ext in ("png", "jpg", "jpeg", "webp", "tiff", "bmp"):
        text = image_vision(data)
    else:
        fn = SANDBOX_EXTRACTORS.get(ext)
        if not fn:
            return {"name": name, "kind": ext, "error": f"sandbox no cubre .{ext} todavia"}
        text = fn(data)
    return {"name": name, "kind": ext, "chars": len(text), "text": text}


# ---------------------------------------------------------------------------
# Demo / self-check
# ---------------------------------------------------------------------------

def _self_check() -> None:
    print("Dependencias opcionales detectadas:")
    for mod, para in [("pytesseract", "OCR"), ("PIL", "OCR"), ("httpx", "vision (Ollama)"),
                      ("docx", "docx"), ("openpyxl", "xlsx")]:
        try:
            __import__(mod); estado = "OK"
        except ImportError:
            estado = "FALTA"
        print(f"  [{estado:5}] {mod:12} ({para})")
    print("\nOCR necesita ademas el binario Tesseract instalado (y el idioma 'spa').")
    print("Vision usa el router (find_models vision:true): Groq/NVIDIA (Llama 4) y")
    print("gemma3 local de fallback -> ollama pull gemma3 para el modo sin internet.")
    try:
        from core import llm_router
        cands = llm_router.find_models({"vision": True, "role": "vision"}, ignore_health=True)
        print("\nModelos de vision configurados (orden de cascada, mayor score primero):")
        for c in cands:
            print(f"  {c['score']:>4}  {c['provider']}/{c['model']}")
    except Exception as e:
        print(f"\n[no pude consultar el router: {e}]")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force_vision = "--vision" in sys.argv
    if not args:
        _self_check()
        print("\nUso: python -m sandbox.attachment_extractors_sandbox <archivo> [--vision]")
        sys.exit(0)
    path = args[0]
    with open(path, "rb") as f:
        data = f.read()
    res = extract(path, data, force_vision=force_vision)
    print(f"name={res['name']} kind={res['kind']} chars={res.get('chars')}")
    print("-" * 60)
    print(res.get("text") or res.get("error"))
