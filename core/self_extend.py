"""
core/self_extend.py
Bucle minimo de autoampliacion supervisada -- ADR-0002, prototipo (opcion B).

Cubre las 3 piezas que faltaban despues de edit_code (core/tools.py):

    1. pip_install    -> instalar dependencias (con whitelist)
    2. restart_service-> reiniciar JarvisAPI para cargar el codigo nuevo
    3. smoke_test     -> comprobar que Jarvis volvio vivo
                         + auto-revert del commit si no.

edit_code YA deja cada cambio como un commit de git reversible. Este modulo NO
genera codigo: opera sobre un commit ya hecho y lo pone en produccion de forma
segura, o lo deshace con `git revert`.

CRITICO -- por que hay un proceso externo:
El paso de reinicio MATA el proceso de JarvisAPI. Si el orquestador corriera
dentro del request del agente, moriria a mitad del bucle y nunca haria el
smoke test ni el revert. Por eso apply() se ejecuta en un proceso DETACHED
(launch_supervised lo lanza con python -m core.self_extend), que sobrevive al
reinicio del servicio y avisa por Telegram del resultado -- mismo patron async
que auditor y netscan.
"""
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import httpx

from config.settings import settings

log = logging.getLogger("jarvis.self_extend")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ALLOWED_PACKAGES_FILE = _REPO_ROOT / "config" / "allowed_packages.json"
_LOG_DIR = _REPO_ROOT / "logs"

HEALTH_TIMEOUT_S = 90          # margen para que FastAPI + Ollama arranquen tras el reinicio
HEALTH_POLL_S = 3


# ---------------------------------------------------------------------------
# Plan de cambio
# ---------------------------------------------------------------------------

@dataclass
class SelfExtendPlan:
    """Describe UN cambio ya commiteado que hay que poner en produccion.

    base_commit  : HEAD ANTES del cambio -- a donde volver si falla (git revert).
    commit       : el commit del cambio (normalmente el HEAD que dejo edit_code).
    packages     : dependencias pip a instalar (deben estar en la whitelist).
    smoke_tool   : (opcional) nombre de una tool de core/tools.py a ejecutar como
                   prueba real de la capacidad nueva. Si falla -> revert.
    smoke_args   : argumentos para esa tool.
    label        : texto corto para los avisos ("lector de PDF", etc.).
    """
    base_commit: str
    commit: str
    packages: list[str] = field(default_factory=list)
    smoke_tool: str = ""
    smoke_args: dict = field(default_factory=dict)
    label: str = "cambio"
    repo: str = str(_REPO_ROOT)


# ---------------------------------------------------------------------------
# Piezas -- cada una es independiente y testeable por separado
# ---------------------------------------------------------------------------

def _load_allowed_packages() -> set[str]:
    try:
        data = json.loads(_ALLOWED_PACKAGES_FILE.read_text(encoding="utf-8"))
        return {p.lower() for p in data.get("allowed", [])}
    except FileNotFoundError:
        return set()


def _package_name(spec: str) -> str:
    """'pypdf>=3.0' -> 'pypdf'. Solo el nombre, sin version ni extras, para
    cotejar con la whitelist."""
    for sep in ("==", ">=", "<=", "~=", ">", "<", "[", "!"):
        spec = spec.split(sep, 1)[0]
    return spec.strip().lower()


def is_package_allowed(spec: str) -> bool:
    return _package_name(spec) in _load_allowed_packages()


def pip_install(packages: list[str]) -> dict:
    """Instala en el MISMO venv que corre Jarvis (sys.executable). Rechaza
    cualquier paquete fuera de config/allowed_packages.json -- un LLM no debe
    poder instalar codigo arbitrario de terceros en el PC."""
    if not packages:
        return {"ok": True, "installed": [], "nota": "sin dependencias que instalar"}

    prohibidos = [p for p in packages if not is_package_allowed(p)]
    if prohibidos:
        return {
            "ok": False,
            "error": (
                f"Paquete(s) no permitido(s): {', '.join(prohibidos)}. "
                f"Anadelos a config/allowed_packages.json antes de instalarlos."
            ),
        }

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", *packages],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pip install tardo mas de 300s"}

    if result.returncode != 0:
        return {"ok": False, "error": "pip install fallo", "output": (result.stderr or "")[-1500:]}
    return {"ok": True, "installed": packages}


def restart_service() -> dict:
    """Reinicia el servicio JarvisAPI (NSSM = servicio Windows estandar). Como
    el orquestador corre DETACHED (fuera del arbol de proceso del servicio), este
    reinicio no lo mata a el, solo al servicio."""
    name = settings.JARVIS_SERVICE_NAME
    # Restart-Service funciona con servicios creados por NSSM (son servicios
    # Windows normales). nssm.exe queda como fallback por si el nombre no casa.
    attempts = [
        ["powershell", "-NoProfile", "-Command", f"Restart-Service -Name '{name}' -Force"],
        ["nssm", "restart", name],
    ]
    last = ""
    for cmd in attempts:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                return {"ok": True, "via": cmd[0]}
            last = (r.stderr or r.stdout or "").strip()
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            last = f"{cmd[0]} timeout"
    return {"ok": False, "error": f"no se pudo reiniciar '{name}': {last}"}


def wait_health(timeout_s: int = HEALTH_TIMEOUT_S) -> bool:
    """True si /health responde 200 dentro del plazo. Una tools.py rota impide
    que FastAPI arranque -> /health nunca vuelve -> esta funcion devuelve False
    -> se dispara el revert. Ese es el nucleo de la red de seguridad."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(settings.HEALTH_URL, timeout=5)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(HEALTH_POLL_S)
    return False


def smoke_tool(name: str, args: dict) -> dict:
    """Ejecuta una tool real como prueba de la capacidad nueva. Se importa
    core.tools DENTRO de la funcion a proposito: si el cambio rompio ese import,
    aqui salta la excepcion y el resultado marca ok=False -> revert."""
    if not name:
        return {"ok": True, "nota": "sin smoke_tool; solo se valido /health"}
    try:
        from core.tools import call_tool
        result = call_tool(name, args or {})
    except Exception as e:
        return {"ok": False, "error": f"la tool '{name}' reventó al ejecutarse: {e}"}
    if isinstance(result, dict) and result.get("error"):
        return {"ok": False, "error": f"la tool '{name}' devolvió error: {result['error']}"}
    return {"ok": True, "result": result}


def git_revert(repo: str, commit: str) -> dict:
    """Revierte el commit del cambio con un commit nuevo (reversible, no reescribe
    historia). Deja rastro en el log de git de que hubo un intento fallido."""
    try:
        r = subprocess.run(
            ["git", "-C", repo, "revert", "--no-edit", commit],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout or "").strip()}
        head = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return {"ok": True, "revert_commit": head}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def git_head(repo: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def _notify(text: str) -> None:
    try:
        from connectors.relay_client import send_telegram_message
        send_telegram_message(text)
    except Exception as e:
        log.warning(f"[self_extend] no se pudo avisar por Telegram: {e}")


# ---------------------------------------------------------------------------
# Orquestador -- encadena las piezas. Corre en el proceso DETACHED.
# ---------------------------------------------------------------------------

def apply(plan: SelfExtendPlan) -> dict:
    """Pone `plan.commit` en produccion: instala deps, reinicia, valida. Si algo
    falla, revierte y reinicia de nuevo para dejar Jarvis en el estado bueno
    anterior. Devuelve un dict con el desenlace y avisa por Telegram."""
    log.info(f"[self_extend] aplicando '{plan.label}' commit={plan.commit[:8]}")

    # 1. dependencias
    pip = pip_install(plan.packages)
    if not pip["ok"]:
        # Fallo ANTES de tocar nada: el codigo nuevo no llego a produccion, no
        # hay reinicio ni cambio de estado -> no hay nada que revertir.
        return _fail(plan, f"instalando dependencias: {pip['error']}", reverted=None)

    # 2. reinicio para cargar el codigo nuevo
    rs = restart_service()
    if not rs["ok"]:
        # No se pudo ni reiniciar: revertimos para no dejar codigo a medio cargar
        rev = git_revert(plan.repo, plan.commit)
        restart_service()
        return _fail(plan, f"reiniciando el servicio: {rs['error']}", reverted=rev.get("ok", False))

    # 3. validacion: vivo + la capacidad nueva funciona
    if not wait_health():
        rev = git_revert(plan.repo, plan.commit)
        restart_service()
        return _fail(
            plan,
            "Jarvis no volvio a responder /health tras el cambio (probable error de import).",
            reverted=rev.get("ok", False),
        )

    smoke = smoke_tool(plan.smoke_tool, plan.smoke_args)
    if not smoke["ok"]:
        rev = git_revert(plan.repo, plan.commit)
        restart_service()
        return _fail(plan, f"smoke test: {smoke['error']}", reverted=rev.get("ok", False))

    msg = f"✅ Autoampliacion OK — {plan.label}\ncommit {plan.commit[:8]} en produccion y validado."
    _notify(msg)
    log.info(f"[self_extend] {msg}")
    return {"ok": True, "commit": plan.commit, "label": plan.label}


def _fail(plan: SelfExtendPlan, motivo: str, reverted: bool | None) -> dict:
    """reverted es tri-estado: None = no hizo falta (fallo antes de cambiar nada);
    True = revertido con exito; False = se intento revertir y el revert fallo."""
    if reverted is None:
        estado = "no hizo falta revertir (no se llegó a cambiar nada)"
    elif reverted:
        estado = "revertido, Jarvis en el estado anterior"
    else:
        estado = "NO se pudo revertir — revisar a mano"
    msg = f"⚠️ Autoampliacion fallida — {plan.label}\nMotivo: {motivo}\nEstado: {estado}."
    _notify(msg)
    log.warning(f"[self_extend] {msg}")
    return {"ok": False, "label": plan.label, "motivo": motivo, "reverted": reverted}


# ---------------------------------------------------------------------------
# Lanzador -- lo que llama el agente. Devuelve enseguida; el bucle corre aparte.
# ---------------------------------------------------------------------------

def launch_supervised(plan: SelfExtendPlan) -> dict:
    """Escribe el plan a un JSON y lanza `python -m core.self_extend` como proceso
    DETACHED que sobrevive al reinicio del servicio. Devuelve al instante: el
    resultado real llega por Telegram cuando el bucle termina."""
    _LOG_DIR.mkdir(exist_ok=True)
    plan_file = _LOG_DIR / f"self_extend_{plan.commit[:8]}.json"
    plan_file.write_text(json.dumps(asdict(plan), ensure_ascii=False, indent=2), encoding="utf-8")
    out_log = open(_LOG_DIR / f"self_extend_{plan.commit[:8]}.log", "w", encoding="utf-8")

    # DETACHED_PROCESS + NEW_PROCESS_GROUP + BREAKAWAY_FROM_JOB: que NO muera
    # cuando NSSM pare JarvisAPI (NSSM mata el arbol de procesos del servicio;
    # BREAKAWAY lo saca de ese job object).
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            0x00000008   # DETACHED_PROCESS
            | 0x00000200  # CREATE_NEW_PROCESS_GROUP
            | 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
        )

    subprocess.Popen(
        [sys.executable, "-m", "core.self_extend", "--plan", str(plan_file)],
        cwd=str(_REPO_ROOT),
        stdout=out_log, stderr=subprocess.STDOUT,
        close_fds=True,
        creationflags=creationflags,
    )
    return {
        "ok": True,
        "status": "lanzado",
        "nota": (
            f"Aplicando '{plan.label}' en segundo plano: instalo deps, me reinicio y "
            f"me autovalido. Te aviso por Telegram cuando termine (o si tuve que revertir)."
        ),
    }


# ---------------------------------------------------------------------------
# Entry point del proceso detached
# ---------------------------------------------------------------------------

def _load_plan(path: str) -> SelfExtendPlan:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return SelfExtendPlan(**data)


def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Bucle de autoampliacion supervisada (ADR-0002)")
    parser.add_argument("--plan", required=True, help="Ruta al JSON del SelfExtendPlan")
    args = parser.parse_args(argv)

    plan = _load_plan(args.plan)
    # Gracia antes de tocar nada: dar tiempo a que el request del agente que nos
    # lanzo termine y responda al usuario ANTES del primer reinicio (que mataria
    # ese proceso). Solo aqui, en el entry point detached -- apply() directo (p.ej.
    # en tests) no se ralentiza.
    time.sleep(5)
    result = apply(plan)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
