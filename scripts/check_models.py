"""
scripts/check_models.py

Comprueba que todos los modelos declarados en config/providers.json (y los de
config/settings.py que usa aider) siguen EXISTIENDO en la API de cada proveedor.

Pensado para cazar retiradas de modelos ANTES de que rompan Jarvis en caliente
-- como la de Groq `llama-3.3-70b-versatile` (decomisionado el 2026-08-16), que
dejo scripts/aider_review.ps1 apuntando a un modelo muerto.

Uso:
    python scripts/check_models.py

Salida: por proveedor, cada modelo marcado OK / FALTA / (sin comprobar).
Exit code 1 si falta algun modelo -> util para un cron semanal o CI.

Recomendado: correrlo tras cada correo "model is being decommissioned" de Groq
(developer@groq.co) y, de forma preventiva, una vez por semana.
"""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import settings  # noqa: E402

PROVIDERS_JSON = Path(__file__).resolve().parents[1] / "config" / "providers.json"

# Endpoint /models OpenAI-compatible por proveedor y clave necesaria. Ollama va
# aparte porque usa /api/tags con otro formato.
CATALOG = {
    "groq": ("https://api.groq.com/openai/v1/models", settings.GROQ_API_KEY),
    "nvidia": ("https://integrate.api.nvidia.com/v1/models", settings.NVIDIA_API_KEY),
    "kimi": (settings.KIMI_API_URL.replace("/chat/completions", "/models"), settings.KIMI_API_KEY),
}


def _openai_catalog(url: str, api_key: str) -> set[str]:
    resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
    resp.raise_for_status()
    return {m["id"] for m in resp.json().get("data", [])}


def _ollama_catalog() -> set[str]:
    url = settings.OLLAMA_URL.replace("/api/generate", "/api/tags")
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return {m["name"] for m in resp.json().get("models", [])}


def _fetch(provider: str) -> tuple[set[str] | None, str]:
    """Devuelve (catalogo, nota). catalogo=None si no se pudo comprobar."""
    try:
        if provider == "ollama":
            return _ollama_catalog(), ""
        if provider in CATALOG:
            url, key = CATALOG[provider]
            if not key:
                return None, "sin API key en .env"
            return _openai_catalog(url, key), ""
        return None, "proveedor sin comprobacion en vivo"
    except Exception as exc:  # noqa: BLE001
        return None, f"error al consultar: {exc}"


def main() -> int:
    config = json.loads(PROVIDERS_JSON.read_text(encoding="utf-8"))
    missing = 0

    for provider, pconf in config["providers"].items():
        enabled = pconf.get("enabled", False)
        catalog, note = _fetch(provider)
        header = f"\n== {provider} =="
        if not enabled:
            header += " (deshabilitado)"
        print(header)

        for model in pconf.get("models", []):
            name = model["name"]
            if catalog is None:
                print(f"  ?  {name}  ({note})")
            elif name in catalog:
                print(f"  OK {name}")
            else:
                print(f"  FALTA {name}  <-- ya no existe en {provider}")
                missing += 1

    # Modelos que NO estan en providers.json pero se usan directamente (aider).
    print("\n== settings (aider / referencias directas) ==")
    groq_catalog, _ = _fetch("groq")
    for label, value in (("GROQ_MODEL_GENERAL", settings.GROQ_MODEL_GENERAL),
                         ("GROQ_MODEL_CODE", settings.GROQ_MODEL_CODE)):
        if groq_catalog is None:
            print(f"  ?  {label}={value}")
        elif value in groq_catalog:
            print(f"  OK {label}={value}")
        else:
            print(f"  FALTA {label}={value}  <-- ya no existe en groq")
            missing += 1

    if missing:
        print(f"\n{missing} modelo(s) configurado(s) ya no existen. Revisar y actualizar.")
        return 1
    print("\nTodos los modelos comprobables siguen disponibles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
