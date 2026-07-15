# -*- coding: utf-8 -*-
"""
core/mando_intents.py — Intents de lenguaje natural para el Centro de Mando.

Principio: máxima sencillez. Regex primero; si nada matchea devuelve None
y el flujo sigue hacia el LLM normal. Sin dependencias nuevas.

Uso en api/main.py (antes de llamar al LLM):

    from core.mando_intents import handle_mando
    reply = handle_mando(user_message)
    if reply is not None:
        return reply   # adaptar al formato de respuesta del /chat

Frases soportadas (ejemplos):
    añade tarea revisar edge del RSI al proyecto tingbot
    apunta tarea llamar al gestor en declaracion-renta con prioridad alta
    elimina la tarea vieja estrategia de tingbot
    borra tarea comprar material del proyecto opos-mataro
    cambia la tarea revisar edge de tingbot a prioridad alta
    renombra la tarea test de tingbot por backtest completo julio

El proyecto debe ser un ID de un solo token (tingbot, declaracion-renta,
opos-mataro…) o un alias que resuelva find_project_id().
"""
import os
import re
import difflib
import unicodedata

import requests

from connectors.mando_tasks import add_task, update_task, delete_task, find_project_id

MANDO_API = os.getenv("MANDO_API_URL", "").rstrip("/")

PRIORITY_MAP = {
    "alta": "high", "urgente": "high", "high": "high",
    "media": "mid", "normal": "mid", "mid": "mid",
    "baja": "low", "low": "low",
}

# ---------------------------------------------------------------- utilidades

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")

def _norm(s: str) -> str:
    return _strip_accents(s.lower().strip().strip("\"'"))

def _get_tasks(project_id: str):
    """GET /tareas — acepta dict {id: {...}} o lista [{id, tasks}]."""
    r = requests.get(f"{MANDO_API}/tareas", timeout=10)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        proj = data.get(project_id)
        if isinstance(proj, dict):
            return proj.get("tasks", [])
        return proj or []
    for p in data:
        if p.get("id") == project_id:
            return p.get("tasks", [])
    return []

def _find_idx(tasks, text):
    """Resuelve texto de tarea → índice. Substring primero, difflib después."""
    target = _norm(text)
    texts = [_norm(t.get("text", "")) for t in tasks]
    for i, t in enumerate(texts):
        if target in t or t in target:
            return i
    close = difflib.get_close_matches(target, texts, n=1, cutoff=0.55)
    if close:
        return texts.index(close[0])
    return None

def _resolve_project(name: str):
    return find_project_id(_norm(name))

# ------------------------------------------------------------------ patrones
# El proyecto es un token único; el texto de la tarea es codicioso y se queda
# con todo hasta el ÚLTIMO separador válido.

_PROJ = r"(?P<proj>[\wáéíóúñ\-]+)"

_ADD = re.compile(
    r"(?:añade(?:me)?|añadir|agrega(?:me)?|agregar|apunta(?:me)?|apuntar|crea|crear|mete|pon)\s+"
    r"(?:una\s+)?(?:nueva\s+)?tarea\s+(?P<text>.+)\s+"
    r"(?:al\s+proyecto|en\s+el\s+proyecto|al|en|a)\s+" + _PROJ +
    r"(?:\s+con\s+prioridad\s+(?P<prio>alta|urgente|media|normal|baja))?\s*$",
    re.IGNORECASE)

# _PRIO antes que _UPD: "cambia la tarea X de Y a prioridad alta"
_PRIO_RE = re.compile(
    r"(?:pon|cambia|marca|sube|baja)\s+(?:la\s+)?tarea\s+(?P<text>.+)\s+"
    r"(?:del\s+proyecto|del|de|en)\s+" + _PROJ +
    r"\s+(?:a|en|con)\s+prioridad\s+(?P<prio>alta|urgente|media|normal|baja)\s*$",
    re.IGNORECASE)

_UPD = re.compile(
    r"(?:modifica|cambia|edita|renombra)\s+(?:la\s+)?tarea\s+(?P<old>.+)\s+"
    r"(?:del\s+proyecto|del|de|en)\s+" + _PROJ +
    r"\s+(?:a|por)\s+(?P<new>.+?)\s*$",
    re.IGNORECASE)

_DEL = re.compile(
    r"(?:elimina(?:me)?|eliminar|borra(?:me)?|borrar|quita(?:me)?|quitar)\s+"
    r"(?:la\s+)?tarea\s+(?P<text>.+)\s+"
    r"(?:del\s+proyecto|del|de|en)\s+" + _PROJ + r"\s*$",
    re.IGNORECASE)

# ------------------------------------------------------------------ handlers

def handle_mando(message: str):
    """Devuelve respuesta str si el mensaje es un intent de mando, si no None."""
    msg = message.strip()
    try:
        m = _PRIO_RE.match(msg)
        if m:
            return _do_priority(m.group("text"), m.group("proj"), m.group("prio"))
        m = _UPD.match(msg)
        if m:
            return _do_update(m.group("old"), m.group("proj"), m.group("new"))
        m = _ADD.match(msg)
        if m:
            return _do_add(m.group("text"), m.group("proj"), m.group("prio"))
        m = _DEL.match(msg)
        if m:
            return _do_delete(m.group("text"), m.group("proj"))
        return None
    except requests.RequestException as e:
        return f"⚠️ No pude contactar con mando-api: {e}"
    except Exception as e:
        return f"⚠️ Error en intent de mando: {e}"

def _do_add(text, proj, prio):
    pid = _resolve_project(proj)
    if not pid:
        return f"⚠️ No encuentro el proyecto «{proj.strip()}» en el Centro de Mando."
    priority = PRIORITY_MAP.get(_norm(prio or ""), "mid")
    add_task(pid, text.strip(), priority=priority)
    return f"✅ Tarea añadida a {pid} ({priority}): {text.strip()}"

def _do_delete(text, proj):
    pid = _resolve_project(proj)
    if not pid:
        return f"⚠️ No encuentro el proyecto «{proj.strip()}»."
    tasks = _get_tasks(pid)
    idx = _find_idx(tasks, text)
    if idx is None:
        return f"⚠️ No encuentro la tarea «{text.strip()}» en {pid}."
    old = tasks[idx].get("text", "")
    delete_task(pid, idx)
    return f"🗑 Tarea eliminada de {pid}: {old}"

def _do_update(old, proj, new):
    pid = _resolve_project(proj)
    if not pid:
        return f"⚠️ No encuentro el proyecto «{proj.strip()}»."
    tasks = _get_tasks(pid)
    idx = _find_idx(tasks, old)
    if idx is None:
        return f"⚠️ No encuentro la tarea «{old.strip()}» en {pid}."
    update_task(pid, idx, text=new.strip())
    return f"✏️ Tarea de {pid} actualizada: {new.strip()}"

def _do_priority(text, proj, prio):
    pid = _resolve_project(proj)
    if not pid:
        return f"⚠️ No encuentro el proyecto «{proj.strip()}»."
    tasks = _get_tasks(pid)
    idx = _find_idx(tasks, text)
    if idx is None:
        return f"⚠️ No encuentro la tarea «{text.strip()}» en {pid}."
    priority = PRIORITY_MAP.get(_norm(prio), "mid")
    update_task(pid, idx, priority=priority)
    return f"🔁 Prioridad de «{tasks[idx].get('text','')}» en {pid} → {priority}"

# --------------------------------------------------------------- test rápido
# Solo parseo de regex, sin red:  .venv\Scripts\python.exe -m core.mando_intents

if __name__ == "__main__":
    casos = [
        ("añade tarea revisar edge del RSI al proyecto tingbot", _ADD),
        ("apunta tarea llamar al gestor en declaracion-renta con prioridad alta", _ADD),
        ("elimina la tarea vieja estrategia de tingbot", _DEL),
        ("cambia la tarea revisar edge de tingbot a prioridad alta", _PRIO_RE),
        ("renombra la tarea test de tingbot por backtest completo julio", _UPD),
        ("añade tarea comprar pienso para Lucky a personal", _ADD),
        ("mete tarea revisar señales de venta en horas bajas en tingbot con prioridad baja", _ADD),
        ("borra la tarea preparar temario de opos-mataro", _DEL),
        ("renombra la tarea mirar datos de enero de tingbot por consolidar datos Q1", _UPD),
    ]
    for frase, patron in casos:
        m = patron.match(frase)
        estado = "OK " if m else "FALLO"
        print(f"[{estado}] {frase}")
        if m:
            print("       ", {k: v for k, v in m.groupdict().items() if v})
