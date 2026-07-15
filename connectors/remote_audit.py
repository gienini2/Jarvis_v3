"""
connectors/remote_audit.py
Copia código de Fígaro al PC local y lanza el auditor.
Uso: audita job_agent en figaro
"""
import shlex
import subprocess
import shutil
import logging
from pathlib import Path
from config.settings import settings

log = logging.getLogger("jarvis.remote_audit")

# Rutas conocidas en Fígaro
FIGARO_PATHS = {
    "actes":      "/var/www/actes",
    "i-actes":    "/var/www/actes",
    "central":    "/var/www/central",
    "dashboard":  "/var/www/dashboard",
    "bitacola":   "/var/www/bitacola",
    "ingenieria": "/opt/ingenieria",
    "job_agent":  "/opt/job_agent",
    "job-agent":  "/opt/job_agent",
    "mando-api":  "/opt/mando-api",
    "mando":      "/opt/mando-api",
}

TMP_BASE = Path(r"C:\tmp\remote_audit")


def resolve_remote_path(project: str) -> str | None:
    """Resuelve nombre de proyecto a ruta en Fígaro."""
    return FIGARO_PATHS.get(project.lower().strip())


def fetch_and_audit(project: str) -> tuple[int, str]:
    remote_path = resolve_remote_path(project)
    if not remote_path:
        return -1, f"No conozco '{project}' en Fígaro. Disponibles: {', '.join(FIGARO_PATHS.keys())}"

    local_path = TMP_BASE / project
    TMP_BASE.mkdir(parents=True, exist_ok=True)
    if local_path.exists():
        shutil.rmtree(local_path)
    local_path.mkdir()

    # Obtener lista de archivos de código (sin node_modules, sin BD)
    quoted_path = shlex.quote(remote_path)
    find_cmd = (
        f"find {quoted_path} -type f "
        f"\\( -name '*.py' -o -name '*.js' -o -name '*.json' -o -name '*.md' -o -name '*.html' -o -name '*.css' \\) "
        f"! -path '*/node_modules/*' ! -path '*/__pycache__/*' ! -name 'package-lock.json'"
    )
    result = subprocess.run(
        ["ssh", "-i", settings.FIGARO_SSH_KEY, "-o", "StrictHostKeyChecking=no",
         f"root@{settings.FIGARO_HOST}", find_cmd],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return -1, f"Error listando archivos: {result.stderr}"

    files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    if not files:
        return -1, f"No encontré archivos de código en {remote_path}"

    # Copiar cada archivo manteniendo estructura
    local_path_resolved = local_path.resolve()
    copied_files = 0
    failed_files = []
    for remote_file in files:
        relative = remote_file[len(remote_path):].lstrip("/")
        local_file = local_path / relative
        # Rechazar path traversal (p.ej. ../../etc/passwd desde servidor comprometido)
        try:
            local_file.resolve().relative_to(local_path_resolved)
        except ValueError:
            log.warning(f"Path traversal bloqueado: {remote_file!r}")
            continue
        local_file.parent.mkdir(parents=True, exist_ok=True)
        copy_result = subprocess.run(
            ["scp", "-i", settings.FIGARO_SSH_KEY,
             "-o", "StrictHostKeyChecking=no",
             f"root@{settings.FIGARO_HOST}:{shlex.quote(remote_file)}",
             str(local_file)],
            capture_output=True, timeout=30
        )
        if copy_result.returncode != 0:
            failed_files.append(remote_file)
            log.warning("No se pudo copiar %s: %s", remote_file, copy_result.stderr[:300])
            continue
        copied_files += 1

    if failed_files:
        return -1, (
            f"No se copiaron {len(failed_files)}/{len(files)} archivos de {project}; "
            "la auditoria se cancelo para no analizar una copia incompleta."
        )

    try:
        from auditor.runner import start_audit_thread
        job_id = start_audit_thread(str(local_path))
        return job_id, f"Auditoría remota iniciada (job_id={job_id})\nProyecto: {project} ({copied_files} archivos)\nTe aviso cuando termine."
    except Exception as e:
        return -1, f"Código copiado pero error al auditar: {e}"
