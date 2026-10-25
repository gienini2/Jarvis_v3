"""Estadisticas EN VIVO por modelo (ultimas 24 h) a partir de logs/llm_calls.jsonl: llamadas, fallos, latencia.
El router las usa para ajustar la puntuacion de cada modelo segun como se esta portando de verdad."""
import json
import statistics
import time

from core import llm_stats

WINDOW_S = 24 * 3600
MIN_CALLS = 5          # con menos llamadas no se ajusta nada (poca muestra)
FAIL_PENALTY = 20.0    # puntos que resta un 100 % de fallos
SLOW_AFTER_S = 1.0     # a partir de esta mediana se penaliza la lentitud
SLOW_PENALTY = 2.0     # puntos por segundo de mas
SLOW_CAP = 10.0
_cache = {"at": 0.0, "data": {}}


def summary(window_s: float = WINDOW_S, fresh: bool = False) -> dict:
    """{(proveedor, modelo): {llamadas, ok, fallos, errores, mediana_s, p90_s, tokens_in, tokens_out}} de la ventana."""
    if not fresh and time.monotonic() - _cache["at"] < 60 and window_s == WINDOW_S:
        return _cache["data"]
    since = time.time() - window_s
    groups: dict = {}
    for event in llm_stats.load(since):
        if event.get("kind") == "call":
            groups.setdefault((event["provider"], event["model"]), []).append(event)
    data = {}
    for key, calls in groups.items():
        ok = [c for c in calls if c.get("ok")]
        latencies = sorted(c["latency"] for c in ok if c.get("latency"))
        errors: dict = {}
        for c in calls:
            if not c.get("ok"):
                errors[c.get("error") or "?"] = errors.get(c.get("error") or "?", 0) + 1
        data[key] = {"llamadas": len(calls), "ok": len(ok), "fallos": len(calls) - len(ok), "errores": errors,
                     "mediana_s": statistics.median(latencies) if latencies else None,
                     "p90_s": latencies[int(0.9 * (len(latencies) - 1))] if latencies else None,
                     "tokens_in": sum(c.get("tokens_in", 0) for c in calls), "tokens_out": sum(c.get("tokens_out", 0) for c in calls)}
    if window_s == WINDOW_S:
        _cache.update(at=time.monotonic(), data=data)
    return data


def adjustment(provider: str, model: str) -> float:
    """Puntos (<= 0) que se restan por fallos y lentitud recientes de ESTE modelo."""
    stat = summary().get((provider, model))
    if not stat or stat["llamadas"] < MIN_CALLS:
        return 0.0
    adj = -FAIL_PENALTY * stat["fallos"] / stat["llamadas"]
    if stat["mediana_s"] and stat["mediana_s"] > SLOW_AFTER_S:
        adj -= min((stat["mediana_s"] - SLOW_AFTER_S) * SLOW_PENALTY, SLOW_CAP)
    return adj
