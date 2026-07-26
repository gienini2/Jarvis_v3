"""
auditor/runner.py — Background thread: scan → batch → LLM → SQLite
Uso: python -m auditor.runner --path <ruta>
"""
import os
import threading
import argparse
from datetime import datetime

from auditor.db import (
    init_db, create_job, update_job,
    add_phase, update_phase, get_phases,
)
from auditor.scanner import scan, SKIP_DIRS
from auditor.batcher import make_batches, batch_prompt
from auditor.synthesizer import run_synthesis
from core.llm import generate
from connectors.relay_client import send_telegram_message

# Carpetas worktree / Claude Code — excluir de auditoría
SKIP_DIRS.update({".claude", "worktrees"})

os.environ["PYTHONUTF8"] = "1"


# ─── CORE ────────────────────────────────────────────────────────────────────

def run_audit(job_id: int, repo_path: str):
    """Ejecuta la auditoría completa. Llamado en un thread."""
    try:
        update_job(job_id, "running")
        print(f"[auditor] job={job_id} path={repo_path} start={datetime.now():%H:%M:%S}")

        # 1. Escanear repo
        files = scan(repo_path)
        print(f"[auditor] {len(files)} archivos detectados")

        # 2. Registrar una phase por archivo en SQLite
        phase_map = {}  # rel_path → phase_id
        for f in files:
            pid = add_phase(job_id, f["rel"])
            phase_map[f["rel"]] = pid

        # 3. Crear lotes adaptativos
        batches = make_batches(files)
        print(f"[auditor] {len(batches)} lotes")

        # 4. Procesar cada lote
        failed_batches = 0
        for i, batch in enumerate(batches, 1):
            relpaths = [f["rel"] for f in batch]
            print(f"[auditor] lote {i}/{len(batches)}: {relpaths}")

            prompt = batch_prompt(batch)
            try:
                result = generate(prompt, intent="audit")
                first = True
                for f in batch:
                    pid = phase_map[f["rel"]]
                    if first:
                        update_phase(pid, "done", result, 0)
                        first = False
                    else:
                        update_phase(pid, "done")
            except Exception as e:
                failed_batches += 1
                for f in batch:
                    update_phase(phase_map[f["rel"]], "error", str(e))
                print(f"[auditor] error lote {i}: {e}")

        # Solo se aborta si fallaron TODOS los lotes (no hay nada que sintetizar).
        # Si fallaron algunos, se genera informe PARCIAL con los que si salieron
        # (synthesize_files ya ignora las fases en error) -- clave en repos grandes,
        # donde algun lote petara por rate-limit pero el resto es util.
        if failed_batches == len(batches):
            detail = f"Todos los lotes ({failed_batches}) fallaron; sin informe."
            update_job(job_id, "error", detail)
            print(f"[auditor] job={job_id} ERROR {datetime.now():%H:%M:%S} -> {detail}")
            send_telegram_message(f"⚠️ Auditoría de {repo_path} FALLÓ: {detail}")
            return

        # 5. Síntesis bottom-up → EXECUTIVE_SUMMARY.md (parcial si fallaron algunos)
        print(f"[auditor] job={job_id} síntesis")
        report_path = run_synthesis(job_id, repo_path)

        if failed_batches:
            nota = f"informe PARCIAL: fallaron {failed_batches}/{len(batches)} lotes (rate-limit u otros)"
            update_job(job_id, "done", nota)
            send_telegram_message(f"ℹ️ Auditoría de {repo_path}: {nota}. Informe generado con el resto.")
        else:
            update_job(job_id, "done")
        print(f"[auditor] job={job_id} DONE {datetime.now():%H:%M:%S} → {report_path}")

    except Exception as e:
        update_job(job_id, "error", str(e))
        print(f"[auditor] job={job_id} ERROR: {e}")
        send_telegram_message(f"⚠️ Auditoría de {repo_path} FALLÓ: {e}")


def start_audit_thread(repo_path: str) -> int:
    """
    Crea el job en SQLite y lanza el thread.
    Devuelve job_id para que la API pueda hacer polling.
    """
    init_db()
    job_id = create_job(repo_path)
    t = threading.Thread(target=run_audit, args=(job_id, repo_path), daemon=True)
    t.start()
    return job_id


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auditor Jarvis")
    parser.add_argument("--path", required=True, help="Ruta del repo a auditar")
    args = parser.parse_args()

    init_db()
    job_id = create_job(args.path)
    print(f"[auditor] job_id={job_id}")
    run_audit(job_id, args.path)  # síncrono desde CLI
