"""
auditor/allowed_paths.py
Whitelist de rutas locales auditables. start_audit (tool del agente y endpoint
/audit/start) acepta una ruta absoluta arbitraria propuesta por el LLM -- sin
esta comprobacion, un prompt-injection o un endpoint sin proteger podria hacer
que Jarvis lea y mande a APIs cloud (Groq/NVIDIA) cualquier carpeta del disco.

Fuente de verdad: config/repo_aliases.json (los proyectos reales que Juan
Pablo audita) + la carpeta temporal donde remote_audit.py copia codigo de
Figaro.
"""
import json
from pathlib import Path

_ALIASES_FILE = Path(__file__).resolve().parent.parent / "config" / "repo_aliases.json"
_EXTRA_ROOTS = [r"C:\tmp\remote_audit"]


def _load_allowed_roots() -> list[Path]:
    roots = []
    try:
        data = json.loads(_ALIASES_FILE.read_text(encoding="utf-8"))
        roots.extend(data.values())
    except FileNotFoundError:
        pass
    roots.extend(_EXTRA_ROOTS)
    return [Path(r).resolve() for r in roots]


def is_path_allowed(path: str) -> bool:
    """True si `path` esta dentro de un repo conocido (config/repo_aliases.json)
    o de la carpeta temporal de auditorias remotas."""
    try:
        candidate = Path(path).resolve()
    except (OSError, ValueError):
        return False
    for root in _load_allowed_roots():
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def allowed_roots_str() -> str:
    return ", ".join(str(r) for r in _load_allowed_roots())
