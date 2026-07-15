"""
auditor/db.py — SQLite: audit_jobs · audit_phases · audit_summaries
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "auditor.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS audit_jobs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_path TEXT    NOT NULL,
                status    TEXT    NOT NULL DEFAULT 'pending',  -- pending · running · done · error
                started   TEXT,
                finished  TEXT,
                error     TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_phases (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id    INTEGER NOT NULL REFERENCES audit_jobs(id),
                file_path TEXT    NOT NULL,
                status    TEXT    NOT NULL DEFAULT 'pending',  -- pending · done · error
                result    TEXT,   -- respuesta cruda del LLM
                tokens    INTEGER
            );

            CREATE TABLE IF NOT EXISTS audit_summaries (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id    INTEGER NOT NULL REFERENCES audit_jobs(id),
                level     TEXT    NOT NULL,  -- file · folder · module · executive
                path      TEXT    NOT NULL,
                summary   TEXT    NOT NULL,
                created   TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)


def create_job(repo_path: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO audit_jobs (repo_path, status, started) VALUES (?, 'pending', datetime('now'))",
            (repo_path,)
        )
        return cur.lastrowid


def update_job(job_id: int, status: str, error: str = None):
    with get_conn() as conn:
        if status == "done" or status == "error":
            conn.execute(
                "UPDATE audit_jobs SET status=?, finished=datetime('now'), error=? WHERE id=?",
                (status, error, job_id)
            )
        else:
            conn.execute(
                "UPDATE audit_jobs SET status=? WHERE id=?",
                (status, job_id)
            )


def add_phase(job_id: int, file_path: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO audit_phases (job_id, file_path) VALUES (?, ?)",
            (job_id, file_path)
        )
        return cur.lastrowid


def update_phase(phase_id: int, status: str, result: str = None, tokens: int = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE audit_phases SET status=?, result=?, tokens=? WHERE id=?",
            (status, result, tokens, phase_id)
        )


def add_summary(job_id: int, level: str, path: str, summary: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_summaries (job_id, level, path, summary) VALUES (?, ?, ?, ?)",
            (job_id, level, path, summary)
        )


def get_job(job_id: int) -> sqlite3.Row:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM audit_jobs WHERE id=?", (job_id,)).fetchone()


def get_phases(job_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM audit_phases WHERE job_id=? ORDER BY id",
            (job_id,)
        ).fetchall()


def get_summaries(job_id: int, level: str = None) -> list:
    with get_conn() as conn:
        if level:
            return conn.execute(
                "SELECT * FROM audit_summaries WHERE job_id=? AND level=? ORDER BY id",
                (job_id, level)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM audit_summaries WHERE job_id=? ORDER BY id",
            (job_id,)
        ).fetchall()
