"""
Enrutado semantico por temas: embedding del mensaje -> coseno contra las frases de
ejemplo de cada tema (config/domains.json); la puntuacion de un tema es la media de
sus 3 frases mas parecidas. Devuelve los temas ganadores, o None si no hay
confianza (el agente entonces usa el clasificador de siempre).
"""
import hashlib
import json
import logging
import re
from pathlib import Path

import numpy as np
import requests

from config.settings import settings
from core import rag
from core.tools import ESCALATE_TOOL, TOOLS

log = logging.getLogger("jarvis.domains")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "domains.json"
CACHE_PATH = ROOT / "data" / "domain_examples.npz"
EXTRA_PATH = ROOT / "data" / "domain_examples_massive.json"

# nomic-embed-text rinde mejor con el prefijo de tarea en ambos lados
PREFIX = "search_query: "
TOP_K = 3
MAX_ROUTED_CHARS = 500
SHORT_MESSAGE_WORDS = 6
_ATTACHMENT_BLOCK = re.compile(r"\[Archivo adjunto:.*?\[Fin del archivo\]", re.DOTALL)

_config: dict | None = None
_examples: dict[str, np.ndarray] | None = None


def _load_config() -> dict:
    global _config
    if _config is None:
        _config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        try:
            extra = json.loads(EXTRA_PATH.read_text(encoding="utf-8"))
            for name, phrases in extra.items():
                if name in _config["domains"]:
                    _config["domains"][name]["examples"] = _config["domains"][name]["examples"] + phrases
        except FileNotFoundError:
            pass
        known = {t["function"]["name"] for t in TOOLS}
        for name, domain in _config["domains"].items():
            unknown = [t for t in domain["tools"] if t not in known]
            if unknown:
                log.warning(f"[domains] {name}: tools inexistentes {unknown}")
                domain["tools"] = [t for t in domain["tools"] if t in known]
    return _config


def _unit(vec) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    return arr / norm if norm else arr


def _embed_many(texts: list[str]) -> list[list[float]]:
    response = requests.post(
        settings.OLLAMA_EMBED_URL,
        json={"model": rag.EMBED_MODEL, "input": texts, "keep_alive": "1h"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["embeddings"]


def _examples_hash(config: dict) -> str:
    examples = {name: d["examples"] for name, d in config["domains"].items()}
    payload = json.dumps([PREFIX, examples], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode()).hexdigest()


def _load_examples() -> dict[str, np.ndarray] | None:
    global _examples
    if _examples is not None:
        return _examples
    config = _load_config()
    digest = _examples_hash(config)
    try:
        with np.load(CACHE_PATH, allow_pickle=False) as cached:
            if str(cached["hash"]) == digest:
                _examples = {name: cached[name] for name in config["domains"]}
                return _examples
    except (FileNotFoundError, KeyError, ValueError, OSError):
        pass
    try:
        computed = {
            name: np.array([_unit(v) for v in _embed_many([PREFIX + e for e in domain["examples"]])])
            for name, domain in config["domains"].items()
        }
    except Exception as e:
        log.warning(f"[domains] no pude calcular los embeddings de ejemplo: {e}")
        return None
    CACHE_PATH.parent.mkdir(exist_ok=True)
    np.savez_compressed(CACHE_PATH, hash=np.array(digest), **computed)
    _examples = computed
    return _examples


def _routing_text(message: str, previous_user: str) -> str:
    text = _ATTACHMENT_BLOCK.sub(" ", message).strip()
    if text and len(text.split()) < SHORT_MESSAGE_WORDS and previous_user:
        text = f"{previous_user} {text}"
    return text[:MAX_ROUTED_CHARS]


def apply_hints(text: str, domain_scores: dict[str, float], boost: float | None = None) -> dict[str, float]:
    """Empujon a los temas cuyas palabras clave aparecen en el texto."""
    config = _load_config()
    amount = config["hint_boost"] if boost is None else boost
    boosted = dict(domain_scores)
    for name, domain in config["domains"].items():
        pattern = domain.get("hints")
        if pattern and re.search(pattern, text, re.IGNORECASE):
            boosted[name] += amount
    return boosted


def scores(message: str, previous_user: str = "", hints: bool = True) -> dict[str, float] | None:
    text = _routing_text(message, previous_user)
    examples = _load_examples()
    if not text or not examples:
        return None
    try:
        query = _unit(_embed_many([PREFIX + text])[0])
    except Exception as e:
        log.warning(f"[domains] embedding del mensaje fallo: {e}")
        return None
    raw = {
        name: float(np.sort(vectors @ query)[::-1][:TOP_K].mean())
        for name, vectors in examples.items()
    }
    return apply_hints(text, raw) if hints else raw


def pick(domain_scores: dict[str, float]) -> list[str] | None:
    config = _load_config()
    ranked = sorted(domain_scores.items(), key=lambda kv: kv[1], reverse=True)
    best_name, best = ranked[0]
    if best < config["min_score"]:
        return None
    chosen = [best_name]
    for name, score in ranked[1:config["max_domains"]]:
        if score >= best - config["margin"]:
            chosen.append(name)
    return chosen


_CLOSING = re.compile(
    r"^\W*(muchas |mil |muchisimas |muchísimas )?(gracias|adi[oó]s|hasta luego|hasta pronto|buenas noches|nos vemos)[\W]*(jarvis)?\W*$",
    re.IGNORECASE,
)


def route(message: str, previous_user: str = "") -> tuple[list[str], float] | None:
    if _CLOSING.match(message):
        return ["charla"], 1.0
    domain_scores = scores(message, previous_user)
    if not domain_scores:
        return None
    chosen = pick(domain_scores)
    return (chosen, max(domain_scores.values())) if chosen else None


def tools_for(domains: list[str]) -> list:
    config = _load_config()
    wanted = []
    for name in domains:
        for tool in config["domains"][name]["tools"]:
            if tool not in wanted:
                wanted.append(tool)
    return [t for t in TOOLS if t["function"]["name"] in wanted] + [ESCALATE_TOOL]


def system_prompt(domains: list[str], message: str) -> str:
    config = _load_config()
    parts = [config["base"]]
    for name in domains:
        fragment = config["domains"][name]["prompt"]
        if fragment and fragment not in parts:
            parts.append(fragment)
    if "[Archivo adjunto:" in message:
        parts.append(config["attachments"])
    return "\n".join(parts)
