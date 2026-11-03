import json
import threading
import time
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "llm_calls.jsonl"
_lock = threading.Lock()


def _append(event: dict):
    try:
        event["ts"] = round(time.time(), 1)
        line = json.dumps(event, ensure_ascii=False)
        with _lock, LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _error_code(exception) -> str:
    if exception is None:
        return ""
    head = str(exception).split(" ", 1)[0]
    return head if head.isdigit() else type(exception).__name__


def record_call(result, role: str, n_tools: int):
    usage = result.usage or {}
    _append({
        "kind": "call",
        "provider": result.provider,
        "model": result.model,
        "role": role,
        "ok": result.success,
        "latency": round(result.latency, 2),
        "tokens_in": usage.get("in", 0),
        "tokens_out": usage.get("out", 0),
        "n_tools": n_tools,
        "error": _error_code(result.exception),
    })


def record_turn(turn: dict, latency: float):
    _append({"kind": "turn", **turn, "latency": round(latency, 2)})


def load(since: float = 0.0) -> list[dict]:
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("ts", 0) >= since:
            events.append(event)
    return events
