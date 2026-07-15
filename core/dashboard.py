import logging
import requests

from connectors.mando_tasks import list_projects

log = logging.getLogger("jarvis.dashboard")

ESTADO_URL = "https://figaro-server.taild7b9e6.ts.net/mando-api/estado"

# Cache en memoria: evita pegarle a Figaro en cada mensaje.
_CACHE_TTL = 30  # segundos
_cache: dict = {"data": None, "ts": 0}


def load_data() -> list:
    """
    Fuente unica de verdad: mando-api en Figaro (via connectors/mando_tasks.list_projects()).
    Antes leia un dashboard-data.json local que quedaba desincronizado del real
    (el que vive en /var/www/dashboard/ en Figaro) y que ademas nunca se comiteaba a git
    -- si se borraba o se olvidaba copiar, Jarvis se quedaba sin tareas. Con esto ya no
    depende de ningun archivo local.
    """
    import time
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    try:
        data = list_projects()
        _cache["data"] = data
        _cache["ts"] = now
        return data
    except Exception as e:
        # Actualiza ts aunque falle -- si no, con Figaro caido esto reintenta
        # (y relogea el warning) en CADA mensaje del chat en vez de una vez
        # cada _CACHE_TTL segundos.
        _cache["ts"] = now
        if _cache["data"] is not None:
            return _cache["data"]  # servir cache vieja antes que fallar del todo
        log.warning(f"No se pudo obtener el Centro de Mando de Figaro: {e}")
        return []


def get_estado() -> dict:
    try:
        res = requests.get(ESTADO_URL, timeout=5)
        res.raise_for_status()
        return res.json()
    except Exception:
        return {}


def post_estado(estado: dict) -> bool:
    try:
        res = requests.post(
            ESTADO_URL,
            json=estado,
            timeout=5,
            headers={"Content-Type": "application/json"},
        )
        return res.ok
    except Exception:
        return False


def get_dashboard() -> list:
    data = load_data()
    estado = get_estado()
    for project in data:
        for i, task in enumerate(project["tasks"]):
            key = f'{project["id"]}_{i}'
            task["done"] = estado.get(key, False)
    return data


def get_pending_tasks(limit: int = 15) -> list:
    dashboard = get_dashboard()
    pendientes = []
    for project in dashboard:
        for task in project["tasks"]:
            if not task.get("done"):
                pendientes.append({
                    "project": project["title"],
                    "project_id": project["id"],
                    "text": task["text"],
                    "priority": task["priority"],
                })
    prioridad = {"high": 0, "mid": 1, "low": 2}
    pendientes.sort(key=lambda x: prioridad.get(x["priority"], 99))
    return pendientes[:limit]
