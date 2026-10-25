"""Prueba de las estadisticas en vivo por modelo, las puntuaciones medidas (locales y de nube) y la mezcla de la recalibracion.
Ejecutar: python tests/test_modelos.py     (usa archivos temporales; no toca tus registros ni puntuaciones reales)
"""
import copy
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from core import llm_router as router, llm_stats, model_stats

checks = []
tmp = Path(tempfile.mkdtemp())


def check(name, ok):
    checks.append(ok)
    print(f"  [{'OK' if ok else 'FALLO'}] {name}")


def log(provider, model, n, ok=True, latency=0.5, error=""):
    with llm_stats.LOG_PATH.open("a", encoding="utf-8") as fh:
        for _ in range(n):
            fh.write(json.dumps({"kind": "call", "provider": provider, "model": model, "ok": ok, "latency": latency, "error": error, "ts": time.time()}) + "\n")


llm_stats.LOG_PATH = tmp / "llm_calls.jsonl"
llm_stats.LOG_PATH.write_text("")

print("Estadisticas en vivo")
log("groq", "bueno", 10)
log("groq", "falla", 5, ok=False, error="429")
log("groq", "falla", 5)
log("ollama", "lento", 6, latency=4.0)
log("groq", "poco", 2, ok=False, error="429")
model_stats._cache["at"] = 0
check("un modelo sano no se penaliza", model_stats.adjustment("groq", "bueno") == 0)
check("la mitad de fallos resta 10 puntos", abs(model_stats.adjustment("groq", "falla") + 10) < 0.01)
check("un modelo lento (mediana 4 s) resta por lentitud", model_stats.adjustment("ollama", "lento") < -5)
check("con pocas llamadas no se ajusta nada", model_stats.adjustment("groq", "poco") == 0)
check("el resumen cuenta llamadas y errores", model_stats.summary()[("groq", "falla")]["errores"] == {"429": 5})

print("Puntuaciones medidas")
local, cloud = tmp / "locales.json", tmp / "nube.json"
local.write_text(json.dumps({"modelos": {"qwen3:8b": 97}}))
cloud.write_text(json.dumps({"modelos": {"groq/openai/gpt-oss-20b": 93}}))
cfg = copy.deepcopy(router._PROVIDERS_CONFIG)
for m in cfg["groq"]["models"] + cfg["ollama"]["models"]:
    m.pop("measured_score", None)
    m.pop("role_priority", None)
router._apply_measured_scores(cfg, local, cloud)
find = lambda p, n: next(m for m in cfg[p]["models"] if m["name"] == n)
check("un local toma su puntuacion para herramientas", find("ollama", "qwen3:8b")["role_priority"]["tools"] == 97)
check("un modelo de nube toma la suya (clave proveedor/modelo)", find("groq", "openai/gpt-oss-20b")["role_priority"]["tools"] == 93)
check("el que no tiene puntuacion conserva su prioridad", "measured_score" not in find("groq", "openai/gpt-oss-120b"))

print("Recalibracion")
import calibrar_modelos as cal
path = tmp / "mezcla.json"
path.write_text(json.dumps({"modelos": {"a": 90.0}}))
merged = cal.merge(path, {"a": 70.0, "b": 80.0})
check("mezcla 70 % lo anterior y 30 % la muestra", merged["a"] == 84.0)
check("un modelo nuevo entra con su muestra", merged["b"] == 80.0)
check("la muestra de cada dia son casos distintos y sin repetir", len({c["prompt"] for c in cal.sample(json.loads((Path(__file__).resolve().parents[1] / "tests" / "tool_cases.json").read_text(encoding="utf-8")), 30)}) == 30)

print(f"\nRESULTADO: {sum(checks)}/{len(checks)} comprobaciones OK")
sys.exit(0 if all(checks) else 1)
