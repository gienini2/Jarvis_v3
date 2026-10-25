"""Puntua modelos locales de Ollama en llamadas a herramientas (tool-calling) con los casos de tests/tool_cases.json.

NO ejecuta ninguna herramienta: solo mira que herramienta pediria cada modelo, con las MISMAS herramientas y prompt de
sistema que le daria Jarvis segun el tema del caso (core/domains.py); los modelos sin herramientas nativas se miden con la emulacion (core/tool_emulation.py). Usa solo frases inventadas.
Uso:
  python scripts/eval_modelos_locales.py --modelos qwen2.5:7b,mistral:7b [--reps 3] [--limite 20] [--pull] [--descargar] [--aplicar] [--proveedor groq|nvidia]
Puntuacion = 100 * (0.50*herramienta + 0.20*argumentos + 0.10*(1-alucinaciones) + 0.10*consistencia + 0.10*velocidad)
  velocidad = 1 - mediana_de_latencia/10 s (acotada a 0..1). Resultados en data/eval_modelos_FECHA.json y .md
"""
import json
import re
import statistics
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import domains

OLLAMA = "http://127.0.0.1:11434"
ROOT = Path(__file__).resolve().parents[1]
SPANISH = {"el", "la", "de", "que", "y", "en", "un", "una", "es", "por", "con", "para", "no", "los", "las", "te", "lo", "se", "me", "tu", "si"}
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def capabilities(model: str) -> list[str]:
    r = requests.post(f"{OLLAMA}/api/show", json={"model": model}, timeout=30)
    return r.json().get("capabilities", []) if r.status_code == 200 else []


def installed() -> set[str]:
    return {m["name"] for m in requests.get(f"{OLLAMA}/api/tags", timeout=10).json()["models"]}


def pull(model: str):
    print(f"  descargando {model} ...", flush=True)
    last = -10
    with requests.post(f"{OLLAMA}/api/pull", json={"model": model, "stream": True}, stream=True, timeout=None) as r:
        for line in r.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            if data.get("total") and data.get("completed"):
                pct = int(100 * data["completed"] / data["total"])
                if pct >= last + 10:
                    last = pct
                    print(f"    {pct}%", flush=True)
            if data.get("error"):
                raise RuntimeError(data["error"])


TOKEN_BUDGET_PER_MIN = 6000   # Groq gratis: 8000 tokens/min por modelo; dejamos margen
RETRY_IN = re.compile(r"try again in ([0-9.]+)(m?s)", re.I)


def ask_cloud(provider: str, model: str, case: dict):
    """Mismo caso y mismas herramientas, pero contra un proveedor de nube; pausa para no pasar del limite gratuito."""
    from core.llm_types import LLMRequest
    from providers.registry import PROVIDERS
    domain = case["dominio"]
    offered = domains.tools_for([domain])
    messages = [{"role": "system", "content": domains.system_prompt([domain], case["prompt"])}, {"role": "user", "content": case["prompt"]}]
    for attempt in range(4):
        res = PROVIDERS[provider].chat_tools(LLMRequest(prompt=messages, tools=offered, model=model))
        if res.success:
            used = (res.usage or {}).get("in", 1500) + (res.usage or {}).get("out", 100)
            time.sleep(used / TOKEN_BUDGET_PER_MIN * 60 if provider == "groq" else 1.5)
            return {"message": res.response, "wall": res.latency, "eval_count": (res.usage or {}).get("out", 0),
                    "eval_s": res.latency, "prompt_tokens": (res.usage or {}).get("in", 0)}, offered
        wait = RETRY_IN.search(str(res.exception))
        if "429" not in str(res.exception) and not wait:
            return {"error": str(res.exception)[:200], "wall": res.latency}, offered
        seconds = (float(wait.group(1)) / (1000 if wait.group(2).lower() == "ms" else 1)) if wait else 20
        time.sleep(seconds + 2)
    return {"error": "429 sin recuperar tras 4 intentos", "wall": 0}, offered


def ask(model: str, case: dict, thinking: bool, emulated: bool = False, provider: str | None = None):
    if provider:
        return ask_cloud(provider, model, case)
    domain = case["dominio"]
    offered = domains.tools_for([domain])
    system = domains.system_prompt([domain], case["prompt"])
    if emulated:   # mismo camino que usa Jarvis con modelos sin herramientas nativas (core/tool_emulation.py)
        from core.llm_types import LLMRequest
        from providers.ollama import OllamaProvider
        messages = [{"role": "system", "content": system}, {"role": "user", "content": case["prompt"]}]
        res = OllamaProvider().chat_tools(LLMRequest(prompt=messages, tools=offered, model=model))
        if not res.success:
            return {"error": str(res.exception)[:200], "wall": res.latency}, offered
        out = (res.usage or {}).get("out", 0)
        return {"message": res.response, "wall": res.latency, "eval_count": out, "eval_s": res.latency, "prompt_tokens": (res.usage or {}).get("in", 0)}, offered
    body = {"model": model, "stream": False, "keep_alive": "20m", "tools": offered,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": case["prompt"]}],
            "options": {"temperature": 0.2, "num_ctx": 4096, "num_gpu": 99}}
    if thinking:
        body["think"] = False
    started = time.monotonic()
    r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=600)
    wall = time.monotonic() - started
    if r.status_code != 200:
        return {"error": r.text[:200], "wall": wall}, offered
    data = r.json()
    return {"message": data["message"], "wall": wall, "eval_count": data.get("eval_count", 0),
            "eval_s": data.get("eval_duration", 0) / 1e9, "prompt_tokens": data.get("prompt_eval_count", 0)}, offered


def check_args(call, schema, expected_substrings) -> bool:
    args = call["function"].get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return False
    if not isinstance(args, dict):
        return False
    params = schema["parameters"]
    for name in params.get("required", []):
        value = args.get(name)
        if value in (None, "", [], {}):
            return False
    for name, value in args.items():
        spec = params.get("properties", {}).get(name)
        expected = TYPES.get((spec or {}).get("type", "string"))
        if spec and expected and not isinstance(value, expected):
            return False
    return all(sub.lower() in norm(args.get(p, "")) or norm(sub) in norm(args.get(p, "")) for p, sub in (expected_substrings or {}).items())


def score_case(case, result, offered):
    if "error" in result:
        return {"ok_tool": False, "error": result["error"], "names": []}
    message = result["message"]
    calls = message.get("tool_calls") or []
    names = [c["function"]["name"] for c in calls]
    schemas = {t["function"]["name"]: t["function"] for t in offered}
    expected, escape_ok = case["esperado"], case.get("acepta_escape", False)
    if expected:
        ok_tool = bool(names) and names[0] in expected
    else:
        ok_tool = not names or (escape_ok and all(n == "usar_herramientas" for n in names))
    out = {"ok_tool": ok_tool, "names": names, "halluc": any(n not in schemas for n in names),
           "args": calls[0]["function"].get("arguments") if calls else None}
    if expected and ok_tool:
        out["args_ok"] = check_args(calls[0], schemas[names[0]], case.get("args"))
    if not expected:
        words = norm(message.get("content", "")).split()
        out["spanish"] = bool(words) and sum(w in SPANISH for w in words) / len(words) >= .08
    return out


def evaluate(model: str, cases: list[dict], reps: int, provider: str | None = None):
    if provider:
        caps, emulated, thinking = [], False, False
    else:
        caps = capabilities(model)
        from providers.ollama import OllamaProvider
        emulated = not OllamaProvider._supports_tools(model)
        thinking = "thinking" in caps
        ask(model, cases[0], thinking, emulated)   # calentamiento (carga el modelo): no puntua
    per_case, lat, tps = [], [], []
    t0 = time.monotonic()
    for i, case in enumerate(cases, 1):
        runs = []
        for _ in range(reps):
            result, offered = ask(model, case, thinking, emulated, provider)
            sc = score_case(case, result, offered)
            runs.append(sc)
            if "wall" in result and "error" not in result:
                lat.append(result["wall"])
                if result["eval_s"] > 0:
                    tps.append(result["eval_count"] / result["eval_s"])
        per_case.append({"prompt": case["prompt"], "dominio": case["dominio"], "esperado": case["esperado"], "runs": runs})
        if i % 10 == 0:
            print(f"    {i}/{len(cases)} casos ({int(time.monotonic() - t0)} s)", flush=True)
    flat = [r for c in per_case for r in c["runs"]]
    with_tool = [r for c in per_case if c["esperado"] for r in c["runs"]]
    chat = [r for c in per_case if not c["esperado"] for r in c["runs"]]
    arg_runs = [r for r in with_tool if "args_ok" in r]
    consistent = [len({tuple(r["names"][:1]) for r in c["runs"]}) == 1 for c in per_case]
    mine = {}
    if not provider:
        ps = requests.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", [])
        mine = next((m for m in ps if m["name"] == model), {})
    summary = {
        "herramienta": sum(r["ok_tool"] for r in flat) / len(flat),
        "herramienta_con_tool": sum(r["ok_tool"] for r in with_tool) / max(1, len(with_tool)),
        "charla_sin_tool": (sum(r["ok_tool"] for r in chat) / len(chat)) if chat else None,
        "argumentos": sum(r["args_ok"] for r in arg_runs) / max(1, len(arg_runs)),
        "alucinaciones": sum(r.get("halluc", False) for r in flat) / len(flat),
        "consistencia": sum(consistent) / len(consistent),
        "espanol_charla": (sum(r.get("spanish", False) for r in chat) / len(chat)) if chat else None,
        "latencia_mediana_s": statistics.median(lat) if lat else None,
        "tokens_por_s": statistics.median(tps) if tps else None,
        "gpu_pct": round(100 * mine.get("size_vram", 0) / mine["size"]) if mine.get("size") else None,
        "errores": sum("error" in r for r in flat),
    }
    speed = min(1, max(0, 1 - (summary["latencia_mediana_s"] or 10) / 10))
    summary["puntuacion"] = round(100 * (.5 * summary["herramienta"] + .2 * summary["argumentos"] + .1 * (1 - summary["alucinaciones"])
                                         + .1 * summary["consistencia"] + .1 * speed), 1)
    summary["emulado"] = emulated
    return {"modelo": f"{provider}/{model}" if provider else model, "proveedor": provider, "resumen": summary, "casos": per_case, "capacidades": caps}


def main():
    argv = sys.argv[1:]
    opt = lambda name, default=None: argv[argv.index(name) + 1] if name in argv else default
    models = [m for m in (opt("--modelos") or "qwen2.5:7b").split(",") if m]
    reps, limit = int(opt("--reps", 1)), opt("--limite")
    cases = json.loads(Path(opt("--casos", ROOT / "tests" / "tool_cases.json")).read_text(encoding="utf-8"))
    if limit:
        cases = cases[:int(limit)]
    provider = opt("--proveedor")
    results = []
    for model in models:
        print(f"\n=== {model} ({len(cases)} casos x {reps} repeticiones)", flush=True)
        try:
            if provider:
                results.append(evaluate(model, cases, reps, provider))
            elif model not in installed():
                if "--pull" not in argv:
                    print("  no esta instalado (usa --pull para descargarlo)")
                    continue
                pull(model)
            if not provider:
                results.append(evaluate(model, cases, reps))
        except Exception as e:
            print(f"  fallo: {e}")
            results.append({"modelo": model, "fallo": str(e)})
        if "--descargar" in argv and not provider:
            requests.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)
        last = results[-1]
        if "resumen" in last:
            s = last["resumen"]
            print(f"  {'[emulado] ' if s['emulado'] else ''}puntuacion {s['puntuacion']} | herramienta {s['herramienta']:.0%} | args {s['argumentos']:.0%} | alucina {s['alucinaciones']:.0%} | "
                  f"mediana {s['latencia_mediana_s'] or 0:.1f}s | {s['tokens_por_s'] or 0:.0f} tok/s | GPU {s['gpu_pct']}%", flush=True)
        elif last.get("sin_soporte"):
            print(f"  SIN soporte de herramientas en Ollama (capacidades: {last['capacidades']})")
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = ROOT / "data" / f"eval_modelos_{stamp}.json"
    out.write_text(json.dumps({"fecha": stamp, "reps": reps, "casos": len(cases), "resultados": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    if "--aplicar" in argv and not provider:
        path = ROOT / "config" / "puntuaciones_locales.json"
        known = json.loads(path.read_text(encoding="utf-8")).get("modelos", {}) if path.exists() else {}
        known.update({r["modelo"]: r["resumen"]["puntuacion"] for r in results if "resumen" in r})
        path.write_text(json.dumps({"fecha": stamp, "modelos": known}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Puntuaciones aplicadas al router: {path.name}")
    rows = sorted((r for r in results if "resumen" in r), key=lambda r: -r["resumen"]["puntuacion"])
    md = ["| Modelo | Puntuación | Herramienta | Con tool | Charla sin tool | Args válidos | Inventa | Consistencia | Mediana | tok/s | GPU |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s = r["resumen"]
        md.append(f"| {r['modelo']}{' (emulado)' if s['emulado'] else ''} | **{s['puntuacion']}** | {s['herramienta']:.0%} | {s['herramienta_con_tool']:.0%} | {('n/d' if s['charla_sin_tool'] is None else format(s['charla_sin_tool'], '.0%'))} | {s['argumentos']:.0%} | "
                  f"{s['alucinaciones']:.0%} | {s['consistencia']:.0%} | {s['latencia_mediana_s'] or 0:.1f}s | {s['tokens_por_s'] or 0:.0f} | {s['gpu_pct']}% |")
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n" + "\n".join(md) + f"\n\nGuardado en {out.name} (+ .md)")


if __name__ == "__main__":
    main()
