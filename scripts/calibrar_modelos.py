"""Recalibracion periodica: mide una MUESTRA de los casos de herramientas en cada modelo en uso y mezcla el resultado con la puntuacion anterior
(70 % lo que ya sabiamos, 30 % la muestra nueva), para que el orden del router siga a como se portan los modelos de verdad.
La muestra rota cada dia, asi en unos dias se recorren los 90 casos. Pensado para ejecutarse de noche (tarea programada).
Uso: python scripts/calibrar_modelos.py [--casos 30] [--solo-locales | --solo-nube]
Escribe config/puntuaciones_locales.json y config/puntuaciones_nube.json y anade una linea a data/calibracion_historial.jsonl."""
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_modelos_locales as base
from config.settings import settings
from core.privacy import LOCAL_PROVIDERS

KEYS = {"groq": "GROQ_API_KEY", "nvidia": "NVIDIA_API_KEY", "cerebras": "CEREBRAS_API_KEY", "kimi": "KIMI_API_KEY"}
KEEP = 0.7


def sample(cases: list[dict], n: int) -> list[dict]:
    offset = date.today().toordinal() * 7
    return [cases[(offset + i * (len(cases) // n)) % len(cases)] for i in range(n)]


def merge(path: Path, fresh: dict) -> dict:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"modelos": {}}
    for model, score in fresh.items():
        old = data["modelos"].get(model)
        data["modelos"][model] = round(KEEP * old + (1 - KEEP) * score, 1) if old is not None else score
    data["fecha"] = datetime.now().strftime("%Y%m%d")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data["modelos"]


def main():
    argv = sys.argv[1:]
    n = int(argv[argv.index("--casos") + 1]) if "--casos" in argv else 30
    cases = sample(json.loads((ROOT / "tests" / "tool_cases.json").read_text(encoding="utf-8")), n)
    cfg = json.loads((ROOT / "config" / "providers.json").read_text(encoding="utf-8"))["providers"]
    fresh_local, fresh_cloud, history = {}, {}, []
    for provider, pconf in cfg.items():
        local = provider in LOCAL_PROVIDERS
        if not pconf.get("enabled") or (local and "--solo-nube" in argv) or (not local and "--solo-locales" in argv):
            continue
        if not local and not getattr(settings, KEYS.get(provider, ""), ""):
            continue
        for model in pconf.get("models", []):
            if "tools" not in model.get("roles", []):
                continue
            name = model["name"]
            print(f"=== {provider}/{name} ({len(cases)} casos)", flush=True)
            try:
                result = base.evaluate(name, cases, 1, None if local else provider)
            except Exception as e:
                print(f"  fallo: {e}")
                continue
            score = result["resumen"]["puntuacion"]
            (fresh_local if local else fresh_cloud)[name if local else f"{provider}/{name}"] = score
            history.append({"fecha": datetime.now().isoformat(timespec="seconds"), "modelo": f"{provider}/{name}", "muestra": score,
                            "latencia_s": result["resumen"]["latencia_mediana_s"]})
            print(f"  muestra {score}", flush=True)
            if local:
                base.requests.post(f"{base.OLLAMA}/api/generate", json={"model": name, "keep_alive": 0}, timeout=60)
    if fresh_local:
        merge(ROOT / "config" / "puntuaciones_locales.json", fresh_local)
    if fresh_cloud:
        merge(ROOT / "config" / "puntuaciones_nube.json", fresh_cloud)
    with (ROOT / "data" / "calibracion_historial.jsonl").open("a", encoding="utf-8") as fh:
        for h in history:
            fh.write(json.dumps(h, ensure_ascii=False) + "\n")
    print(f"Calibrados {len(history)} modelos.")


if __name__ == "__main__":
    main()
