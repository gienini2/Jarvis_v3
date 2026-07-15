"""
auditor/api_routes.py — /audit/start · /audit/{id}/status · /audit/{id}/report
Se registra en api/main.py con: app.include_router(audit_router)
"""

from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from auditor.db import init_db, get_job, get_phases, get_summaries
from auditor.runner import start_audit_thread
from auditor.allowed_paths import is_path_allowed, allowed_roots_str

audit_router = APIRouter(prefix="/audit", tags=["auditor"])

init_db()


# ─── SCHEMAS ─────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    path: str


# ─── RUTAS ───────────────────────────────────────────────────────────────────

@audit_router.post("/start")
def start(req: StartRequest):
    """Lanza una auditoría en background. Devuelve job_id."""
    if not Path(req.path).exists():
        raise HTTPException(400, f"Ruta no existe: {req.path}")
    if not is_path_allowed(req.path):
        raise HTTPException(
            403, f"Ruta no permitida. Proyectos conocidos: {allowed_roots_str()}"
        )
    job_id = start_audit_thread(req.path)
    return {"job_id": job_id, "status": "started"}


@audit_router.get("/{job_id}/status")
def status(job_id: int):
    """Estado del job + progreso de phases."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")

    phases = get_phases(job_id)
    total = len(phases)
    done  = sum(1 for p in phases if p["status"] == "done")
    error = sum(1 for p in phases if p["status"] == "error")

    return {
        "job_id":   job_id,
        "status":   job["status"],
        "repo":     job["repo_path"],
        "started":  job["started"],
        "finished": job["finished"],
        "progress": {"total": total, "done": done, "error": error},
        "error":    job["error"],
    }


@audit_router.get("/{job_id}/report")
def report(job_id: int):
    """Devuelve el EXECUTIVE_SUMMARY y los summaries por nivel."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    if job["status"] != "done":
        raise HTTPException(409, f"Job aún no terminado: {job['status']}")

    executive = get_summaries(job_id, level="executive")
    modules   = get_summaries(job_id, level="module")
    folders   = get_summaries(job_id, level="folder")

    return {
        "job_id":    job_id,
        "repo":      job["repo_path"],
        "executive": executive[0]["summary"] if executive else None,
        "modules":   [{"path": s["path"], "summary": s["summary"]} for s in modules],
        "folders":   [{"path": s["path"], "summary": s["summary"]} for s in folders],
    }
