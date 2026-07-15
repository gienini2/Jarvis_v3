"""
alpha50/history_reader.py
Acceso de solo lectura a alpha50_cronologia.db para consumidores externos al
propio modulo Alpha50 (05/07/2026) -- en concreto, la tool query_alpha50_history
de core/tools.py, para que el agente de tool-calling pueda responder preguntas
sobre entrenamientos pasados en una conversacion general (Telegram, chat local),
no solo dentro del flujo especifico de alpha50_intent_handler().

Deliberadamente NO escribe nada -- solo SELECT. Si en el futuro se quiere que
esto alimente el RAG central (embeddings en PostgreSQL), sera un script de
ingesta aparte, no esto.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "alpha50_cronologia.db"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def get_historial(fecha: str = "", dias: int = 14) -> dict:
    """Devuelve el estado del programa Alpha50 y el historial de dias.

    - fecha (YYYY-MM-DD): si se da, devuelve solo ese dia (o vacio si no hay registro).
    - dias: si no se da fecha, cuantos dias recientes traer (por defecto 14).
    """
    if not DB_PATH.exists():
        return {
            "error": (
                f"No encuentro {DB_PATH} -- el modulo Alpha50 no ha generado "
                "historial todavia en este PC."
            )
        }

    con = _connect()
    try:
        programa_row = con.execute("SELECT * FROM estado_programa WHERE id=1").fetchone()
        programa = dict(programa_row) if programa_row else None

        if fecha:
            row = con.execute(
                "SELECT * FROM historial_dias WHERE fecha=?", (fecha,)
            ).fetchone()
            historial = [dict(row)] if row else []
        else:
            rows = con.execute(
                "SELECT * FROM historial_dias ORDER BY fecha DESC LIMIT ?",
                (max(1, min(dias, 90)),),  # tope de 90 para no devolver la tabla entera por error
            ).fetchall()
            historial = [dict(r) for r in rows]
    finally:
        con.close()

    return {"programa": programa, "historial": historial}
