"""Resumen de logs/llm_calls.jsonl.  Uso: python scripts/llm_stats_report.py [horas]"""
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import llm_stats


def peak_per_minute(calls: list[dict]) -> int:
    calls = sorted(calls, key=lambda c: c["ts"])
    best, start, total = 0, 0, 0
    for end, call in enumerate(calls):
        total += call["tokens_in"] + call["tokens_out"]
        while call["ts"] - calls[start]["ts"] > 60:
            total -= calls[start]["tokens_in"] + calls[start]["tokens_out"]
            start += 1
        best = max(best, total)
    return best


def main():
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 24
    events = llm_stats.load(time.time() - hours * 3600)
    calls = [e for e in events if e["kind"] == "call"]
    turns = [e for e in events if e["kind"] == "turn"]
    if not events:
        print(f"Sin datos en las ultimas {hours:g} h ({llm_stats.LOG_PATH})")
        return

    print(f"=== Llamadas a LLM (ultimas {hours:g} h) ===")
    by_model = defaultdict(list)
    for c in calls:
        by_model[(c["provider"], c["model"])].append(c)
    for (provider, model), group in sorted(by_model.items()):
        ok = [c for c in group if c["ok"]]
        errors = Counter(c["error"] for c in group if not c["ok"])
        avg_lat = sum(c["latency"] for c in ok) / len(ok) if ok else 0
        avg_in = sum(c["tokens_in"] for c in ok) / len(ok) if ok else 0
        print(f"{provider}/{model}: {len(group)} llamadas, {len(ok)} ok, "
              f"lat {avg_lat:.1f}s, in medio {avg_in:.0f} tok, errores {dict(errors) or '-'}")

    print("\n=== Pico de tokens en 60 s por modelo (limite Groq free: 8000 por modelo) ===")
    for (provider, model), group in sorted(by_model.items()):
        ok = [c for c in group if c["ok"]]
        print(f"{provider}/{model}: {peak_per_minute(ok)} tok/min")

    print("\n=== Turnos del agente ===")
    by_branch = defaultdict(list)
    for t in turns:
        by_branch[t["branch"] or "?"].append(t)
    for branch, group in sorted(by_branch.items()):
        rounds = sum(t["rounds"] for t in group) / len(group)
        lat = sum(t["latency"] for t in group) / len(group)
        pick = sum(t.get("pick_s", 0) for t in group) / len(group)
        tool = sum(t.get("tool_s", 0) for t in group) / len(group)
        print(f"rama {branch}: {len(group)} turnos, {rounds:.1f} rondas, {lat:.1f}s "
              f"(clasificar {pick:.1f}s, tools {tool:.1f}s)")
    routed = [t for t in turns if t.get("branch") == "dominios"]
    if routed:
        escaped = sum(1 for t in routed if t.get("escaped"))
        print(f"enrutado por temas: {len(routed)} turnos, escape (mal enrutados) {escaped}/{len(routed)}")
        by_domain = Counter(d for t in routed for d in t.get("domains", []))
        print("temas elegidos:", ", ".join(f"{d} x{c}" for d, c in by_domain.most_common()))
    used = Counter(name for t in turns for name in t["tools"])
    if used:
        print("tools usadas:", ", ".join(f"{n} x{c}" for n, c in used.most_common(10)))


if __name__ == "__main__":
    main()
