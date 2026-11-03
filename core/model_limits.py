"""Limitaciones medidas de cada modelo local, para mostrarlas en la UI (salen de la ultima evaluacion de scripts/eval_modelos_locales.py)."""
import json
from pathlib import Path

from core.llm_router import _backend_label

DATA = Path(__file__).resolve().parents[1] / "data"
WEAK_FROM = 0.25   # un tema con mas de este porcentaje de fallos se cuenta como punto debil


def limits() -> dict[str, dict]:
    files = sorted(DATA.glob("eval_modelos_*.json"))
    latest: dict[str, dict] = {}
    for path in files:
        for result in json.loads(path.read_text(encoding="utf-8")).get("resultados", []):
            if "resumen" in result and not result.get("proveedor"):
                latest[result["modelo"]] = result
    out = {}
    for model, result in latest.items():
        s = result["resumen"]
        bad, total = {}, {}
        for case in result["casos"]:
            for run in case["runs"]:
                total[case["dominio"]] = total.get(case["dominio"], 0) + 1
                bad[case["dominio"]] = bad.get(case["dominio"], 0) + (not run["ok_tool"])
        weak = sorted((d for d in total if bad[d] / total[d] > WEAK_FROM), key=lambda d: -bad[d] / total[d])
        lines = [f"Puntuacion {s['puntuacion']:.0f}/100",
                 f"Elige bien la herramienta: {s['herramienta']:.0%}; argumentos validos: {s['argumentos']:.0%}",
                 f"Se inventa herramientas: {s['alucinaciones']:.0%}; tarda de mediana {s['latencia_mediana_s']:.1f} s"]
        if s.get("emulado"):
            lines.append("Herramientas emuladas por prompt (sin plantilla nativa)")
        if weak:
            lines.append("Flojea en: " + ", ".join(weak))
        out[_backend_label("ollama", model)] = {"modelo": model, "puntuacion": s["puntuacion"], "limitaciones": "\n".join(lines)}
    return out
