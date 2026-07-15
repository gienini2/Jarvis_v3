"""
auditor/synthesizer.py — Bottom-up: archivo → carpeta → módulo → EXECUTIVE_SUMMARY.md
Lee los resultados de audit_phases y construye summaries por nivel.
"""

import requests
from pathlib import Path

from auditor.db import (
    get_phases, add_summary, get_summaries,
)
from auditor.scanner import group_by_folder, tree
from core.llm import generate
from config.settings import settings


# ─── LLM ────────────────────────────────────────────────────────────────────

def _ask(prompt: str) -> str:
    return generate(prompt, intent="audit").strip()


def _notify_telegram(job_id: int):
    """Avisa a la API local para que mande el informe a Telegram."""
    try:
        headers = {"X-Jarvis-Key": settings.JARVIS_API_KEY} if settings.JARVIS_API_KEY else {}
        response = requests.post(
            f"http://127.0.0.1:3000/audit/{job_id}/notify",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
    except Exception as e:
        print(f"[synthesizer] notify falló (no crítico): {e}")


# ─── NIVELES ─────────────────────────────────────────────────────────────────

def synthesize_files(job_id: int):
    phases = get_phases(job_id)
    for p in phases:
        if p["status"] == "done" and p["result"]:
            add_summary(job_id, "file", p["file_path"], p["result"])


def synthesize_folders(job_id: int, repo_path: str):
    file_summaries = get_summaries(job_id, level="file")
    if not file_summaries:
        return

    groups: dict[str, list[str]] = {}
    for s in file_summaries:
        folder = str(Path(s["path"]).parent)
        if folder == ".":
            folder = ""
        groups.setdefault(folder, []).append(s["summary"])

    for folder, summaries in groups.items():
        label = folder or "(raíz)"
        block = "\n---\n".join(summaries)
        prompt = (
            f"Estos son los análisis individuales de los archivos en la carpeta '{label}'.\n"
            f"Haz un resumen cohesionado de la carpeta: qué hace, patrones detectados, "
            f"problemas relevantes. Máximo 200 palabras.\n\n{block}"
        )
        result = _ask(prompt)
        add_summary(job_id, "folder", label, result)


def synthesize_modules(job_id: int):
    folder_summaries = get_summaries(job_id, level="folder")
    if not folder_summaries:
        return

    groups: dict[str, list[str]] = {}
    for s in folder_summaries:
        module = s["path"].split("/")[0].split("\\")[0] or "(raíz)"
        groups.setdefault(module, []).append(s["summary"])

    for module, summaries in groups.items():
        block = "\n---\n".join(summaries)
        prompt = (
            f"Estos son los resúmenes de las carpetas del módulo '{module}'.\n"
            f"Sintetiza el módulo: responsabilidad principal, interdependencias, "
            f"riesgos o deuda técnica. Máximo 150 palabras.\n\n{block}"
        )
        result = _ask(prompt)
        add_summary(job_id, "module", module, result)


def synthesize_executive(job_id: int, repo_path: str) -> str:
    module_summaries = get_summaries(job_id, level="module")
    if not module_summaries:
        return ""

    repo_tree = tree(repo_path)
    block = "\n---\n".join(f"**{s['path']}**\n{s['summary']}" for s in module_summaries)

    prompt = (
        f"Eres un arquitecto de software senior. Analiza este repositorio.\n\n"
        f"Árbol del proyecto:\n```\n{repo_tree}\n```\n\n"
        f"Resúmenes por módulo:\n{block}\n\n"
        f"Escribe un EXECUTIVE SUMMARY en markdown con estas secciones:\n"
        f"## Propósito del proyecto\n"
        f"## Módulos principales\n"
        f"## Hallazgos críticos\n"
        f"## Recomendaciones\n"
        f"Sé directo y técnico. Sin relleno."
    )
    result = _ask(prompt)

    add_summary(job_id, "executive", repo_path, result)

    out_path = Path(repo_path) / "EXECUTIVE_SUMMARY.md"
    out_path.write_text(result, encoding="utf-8")
    print(f"[synthesizer] EXECUTIVE_SUMMARY.md → {out_path}")

    return str(out_path)


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def run_synthesis(job_id: int, repo_path: str) -> str:
    print(f"[synthesizer] job={job_id} nivel=file")
    synthesize_files(job_id)

    print(f"[synthesizer] job={job_id} nivel=folder")
    synthesize_folders(job_id, repo_path)

    print(f"[synthesizer] job={job_id} nivel=module")
    synthesize_modules(job_id)

    print(f"[synthesizer] job={job_id} nivel=executive")
    out = synthesize_executive(job_id, repo_path)

    _notify_telegram(job_id)

    return out
