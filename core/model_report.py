"""Informe de modelos en dos grupos (locales / nube): lo medido en las evaluaciones + lo que pasa de verdad en las ultimas 24 h."""
import json
from pathlib import Path

from core import model_stats
from core.privacy import LOCAL_PROVIDERS

ROOT = Path(__file__).resolve().parents[1]
CATS = ["instrucciones", "razonamiento", "honestidad", "robustez", "contexto", "voz"]


def _key(name: str) -> str:
    return name.removesuffix(":latest")


def _evals(pattern: str) -> dict:
    """Ultimo resultado de cada modelo entre todos los archivos de evaluacion (los mas recientes pisan a los viejos)."""
    latest = {}
    for path in sorted((ROOT / "data").glob(pattern)):
        for r in json.loads(path.read_text(encoding="utf-8")).get("resultados", []):
            if r.get("modelo") and ("categorias" in r or "resumen" in r):
                latest[_key(r["modelo"])] = r
    return latest


def build() -> dict:
    cfg = json.loads((ROOT / "config" / "providers.json").read_text(encoding="utf-8"))["providers"]
    tools, broad, live = _evals("eval_modelos_*.json"), _evals("eval_amplia_*.json"), model_stats.summary()
    rows = {}

    def row(provider: str, model: str, state: str):
        key = _key(model if provider in LOCAL_PROVIDERS else f"{provider}/{model}")
        t, b, l = tools.get(key), broad.get(key), live.get((provider, model))
        rows[(provider, model)] = {
            "modelo": model, "proveedor": provider, "grupo": "Locales" if provider in LOCAL_PROVIDERS else "Nube", "estado": state,
            "herramientas": t["resumen"]["puntuacion"] if t else None,
            "global": b["global"] if b else None, "uso_herramientas": b["uso_herramientas"] if b else None, "uso_charla": b["uso_charla"] if b else None,
            "categorias": b["categorias"] if b else None,
            "mediana_eval_s": (b or {}).get("latencia_mediana_s") or ((t or {}).get("resumen") or {}).get("latencia_mediana_s"),
            "llamadas_24h": l["llamadas"] if l else 0, "fallos_24h": l["fallos"] if l else 0, "errores_24h": l["errores"] if l else {},
            "mediana_real_s": l["mediana_s"] if l else None}

    for provider, pconf in cfg.items():
        for m in pconf.get("models", []):
            state = "en la cascada" if pconf.get("enabled") else "proveedor desactivado"
            row(provider, m["name"], state)
    for key, r in {**tools, **broad}.items():
        provider = r.get("proveedor") or "ollama"
        model = key.split("/", 1)[1] if r.get("proveedor") else key
        if not any(p == provider and _key(m) == _key(model) for p, m in rows):
            row(provider, model, "solo evaluado")
    return {"filas": sorted(rows.values(), key=lambda r: (r["grupo"], -(r["global"] or r["herramientas"] or 0)))}


def markdown(report: dict) -> str:
    out = []
    for group in ("Locales", "Nube"):
        out += [f"## {group}", "", "| Modelo | Estado | Global | Herram. | Uso herr. | Uso charla | " + " | ".join(c[:5] for c in CATS) +
                " | Lat. eval | Lat. real 24h | Llam. 24h | Fallos |", "|---" * (len(CATS) + 10) + "|"]
        for r in (x for x in report["filas"] if x["grupo"] == group):
            f = lambda v, d=1: "–" if v is None else f"{v:.{d}f}"
            cats = r["categorias"] or {}
            out.append(f"| {r['proveedor']}/{r['modelo']} | {r['estado']} | {f(r['global'])} | {f(r['herramientas'])} | {f(r['uso_herramientas'])} | {f(r['uso_charla'])} | " +
                       " | ".join("–" if c not in cats else f"{cats[c]:.0%}" for c in CATS) +
                       f" | {f(r['mediana_eval_s'])}s | {f(r['mediana_real_s'])}s | {r['llamadas_24h']} | {r['fallos_24h']} |")
        out.append("")
    return "\n".join(out)
