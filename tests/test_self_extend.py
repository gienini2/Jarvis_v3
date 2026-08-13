"""
tests/test_self_extend.py
Prueba end-to-end CONTROLADA del bucle core/self_extend.py (ADR-0002).

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_self_extend.py

Qué es REAL aquí:
  - repos git temporales de verdad, con commits de verdad
  - git_revert() real ejecutándose sobre ellos
  - apply(): el orquestador entero, sin tocar
  - pip_install() con la whitelist real (paquetes vacíos)

Qué está guionizado (stub) y por qué:
  - restart_service()  -> no reiniciamos JarvisAPI en una prueba
  - wait_health()      -> devolvemos True/False a voluntad para forzar cada rama
  - _notify()          -> capturamos el texto en vez de mandarlo a Telegram
  - smoke_tool()       -> solo en el escenario C, para forzar un fallo de smoke
  (las 3 primeras se validaron sueltas contra el sistema vivo)
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Bootstrap: permite `python tests/test_self_extend.py` desde cualquier cwd sin
# depender de PYTHONPATH -- la raiz del repo (donde vive core/) va al path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.self_extend as se

PASS, FAIL = "\033[92mOK\033[0m", "\033[91mFALLA\033[0m"
_results = []


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _make_repo() -> Path:
    d = Path(tempfile.mkdtemp(prefix="se_e2e_"))
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "test@test")
    _git(d, "config", "user.name", "test")
    (d / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(d, "add", ".")
    _git(d, "commit", "-q", "-m", "base")
    return d


def _commit_change(repo: Path, contenido: str, msg: str) -> str:
    (repo / "mod.py").write_text(contenido, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", msg)
    return se.git_head(str(repo))


def _check(nombre, cond):
    _results.append(cond)
    print(f"  [{PASS if cond else FAIL}] {nombre}")


def _install_stubs(notifs, health_ok, smoke_result=None):
    se.restart_service = lambda: {"ok": True, "via": "stub"}
    se._notify = lambda text: notifs.append(text)
    se.wait_health = lambda timeout_s=90: health_ok
    if smoke_result is not None:
        se.smoke_tool = lambda name, args: smoke_result


# ---------------------------------------------------------------------------
# Escenario A: todo OK -> el commit se queda, aviso de éxito
# ---------------------------------------------------------------------------
def escenario_A():
    print("\nESCENARIO A — camino feliz (health OK, sin smoke):")
    repo = _make_repo()
    base = se.git_head(str(repo))
    commit = _commit_change(repo, "VALUE = 2\n", "cambio bueno")
    notifs = []
    _install_stubs(notifs, health_ok=True)

    plan = se.SelfExtendPlan(base_commit=base, commit=commit, packages=[],
                             smoke_tool="", label="cambio bueno", repo=str(repo))
    res = se.apply(plan)

    _check("apply devuelve ok=True", res.get("ok") is True)
    _check("el cambio SIGUE aplicado (VALUE=2)", "VALUE = 2" in (repo / "mod.py").read_text())
    _check("HEAD sigue en el commit del cambio (no hay revert)", se.git_head(str(repo)) == commit)
    _check("avisó éxito por Telegram", any("OK" in n or "✅" in n for n in notifs))
    shutil.rmtree(repo, ignore_errors=True)


# ---------------------------------------------------------------------------
# Escenario B: /health no vuelve -> auto-revert, aviso de fallo
# ---------------------------------------------------------------------------
def escenario_B():
    print("\nESCENARIO B — Jarvis no arranca tras el cambio (health FALLA):")
    repo = _make_repo()
    base = se.git_head(str(repo))
    commit = _commit_change(repo, "VALUE = 999  # rompe algo\n", "cambio que rompe")
    notifs = []
    _install_stubs(notifs, health_ok=False)   # <- health nunca vuelve

    plan = se.SelfExtendPlan(base_commit=base, commit=commit, packages=[],
                             smoke_tool="", label="cambio que rompe", repo=str(repo))
    res = se.apply(plan)

    _check("apply devuelve ok=False", res.get("ok") is False)
    _check("marcó reverted=True", res.get("reverted") is True)
    _check("el árbol volvió al estado bueno (VALUE=1)", "VALUE = 1" in (repo / "mod.py").read_text())
    _check("se creó un commit de revert (HEAD != commit malo)", se.git_head(str(repo)) != commit)
    log = _git(repo, "log", "--oneline").stdout
    _check("el log registra el 'Revert'", "Revert" in log)
    _check("avisó fallo + revertido por Telegram", any("revertido" in n.lower() for n in notifs))
    shutil.rmtree(repo, ignore_errors=True)


# ---------------------------------------------------------------------------
# Escenario C: health OK pero la capacidad nueva no funciona -> revert
# ---------------------------------------------------------------------------
def escenario_C():
    print("\nESCENARIO C — arranca pero el smoke test de la tool nueva FALLA:")
    repo = _make_repo()
    base = se.git_head(str(repo))
    commit = _commit_change(repo, "VALUE = 3\n", "tool nueva rota")
    notifs = []
    _install_stubs(notifs, health_ok=True,
                   smoke_result={"ok": False, "error": "la tool devolvió error: fecha inválida"})

    plan = se.SelfExtendPlan(base_commit=base, commit=commit, packages=[],
                             smoke_tool="crear_evento_pdf", smoke_args={"x": 1},
                             label="tool nueva rota", repo=str(repo))
    res = se.apply(plan)

    _check("apply devuelve ok=False", res.get("ok") is False)
    _check("marcó reverted=True", res.get("reverted") is True)
    _check("el árbol volvió al estado bueno (VALUE=1)", "VALUE = 1" in (repo / "mod.py").read_text())
    _check("avisó que revirtió por el smoke", any("smoke" in n.lower() and "revertido" in n.lower() for n in notifs))
    shutil.rmtree(repo, ignore_errors=True)


# ---------------------------------------------------------------------------
# Escenario D: paquete fuera de whitelist -> ni instala ni reinicia (pip real).
# Fallo ANTES de cambiar nada: no hay que revertir (reverted=None).
# ---------------------------------------------------------------------------
def escenario_D():
    print("\nESCENARIO D — dependencia no permitida (whitelist real, sin stub de pip):")
    repo = _make_repo()
    base = se.git_head(str(repo))
    commit = _commit_change(repo, "VALUE = 4\n", "pide paquete prohibido")
    notifs = []
    _install_stubs(notifs, health_ok=True)
    restart_llamado = {"n": 0}
    se.restart_service = lambda: (restart_llamado.__setitem__("n", restart_llamado["n"] + 1) or {"ok": True})

    plan = se.SelfExtendPlan(base_commit=base, commit=commit, packages=["requests"],
                             smoke_tool="", label="pide paquete prohibido", repo=str(repo))
    res = se.apply(plan)

    _check("apply devuelve ok=False", res.get("ok") is False)
    _check("NO llegó a reiniciar el servicio", restart_llamado["n"] == 0)
    _check("el motivo menciona la dependencia", "dependencia" in res.get("motivo", "").lower())
    _check("reverted=None (no había nada que revertir)", res.get("reverted") is None)
    _check("avisó 'no hizo falta revertir'", any("no hizo falta revertir" in n.lower() for n in notifs))
    shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    escenario_A()
    escenario_B()
    escenario_C()
    escenario_D()
    print("\n" + "=" * 50)
    total, ok = len(_results), sum(_results)
    print(f"RESULTADO: {ok}/{total} comprobaciones OK")
    raise SystemExit(0 if ok == total else 1)
