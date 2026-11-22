"""
alpha50/remoto.py -- acceso de Jarvis (PC) a Alpha50 cuando vive en Figaro.

Si settings.ALPHA50_URL esta configurado (p. ej. http://100.78.43.76:10050),
Alpha50 corre en Figaro (alpha50/servicio.py) y el PC NO debe tocar su copia
local de alpha50_cronologia.db: los mensajes "/alpha50 ...", el historial y el
repaso se piden por HTTP. Sin ALPHA50_URL todo sigue en local, como antes.
"""
import re
from typing import Optional

import requests

# Mismo criterio que scheduler._EXPLICITO: Alpha50 solo atiende lo que empieza
# por /alpha50 (o "alpha50"), asi que el resto ni se envia a Figaro.
_ES_ALPHA50 = re.compile(r"^\s*/?alpha50(?:@\w+)?\b", re.IGNORECASE)

TIMEOUT_S = 20


def _config() -> tuple[str, str]:
    try:
        from config.settings import settings
        return (getattr(settings, "ALPHA50_URL", "") or "").rstrip("/"), \
               getattr(settings, "ALPHA50_API_KEY", "") or ""
    except Exception:
        return "", ""


def activo() -> bool:
    """True si Alpha50 esta en Figaro (hay ALPHA50_URL)."""
    return bool(_config()[0])


def _get(ruta: str, params: dict) -> dict:
    url, clave = _config()
    try:
        r = requests.get(f"{url}{ruta}", params=params, timeout=TIMEOUT_S,
                         headers={"X-Alpha50-Key": clave})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": f"Alpha50 (Figaro) no responde: {e}"}


def mensaje(texto: str) -> Optional[str]:
    """Pasa un mensaje a Alpha50 en Figaro. None si no es para Alpha50."""
    if not _ES_ALPHA50.match(texto or ""):
        return None
    url, clave = _config()
    try:
        r = requests.post(f"{url}/mensaje", json={"texto": texto}, timeout=TIMEOUT_S,
                          headers={"X-Alpha50-Key": clave})
        r.raise_for_status()
        return r.json().get("respuesta")
    except Exception as e:
        return f"⚠️ Alpha50 (en Figaro) no responde ahora mismo: {e}"


def historial(fecha: str = "", dias: int = 14) -> dict:
    return _get("/historial", {"fecha": fecha, "dias": dias})


def repaso(dias: int = 7) -> dict:
    return _get("/repaso", {"dias": dias})
