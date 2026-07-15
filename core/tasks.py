from core.db import get_connection
from core.dashboard import load_data, get_estado, post_estado

_STATUS_FROM_EMOJI = {
    "✅": "done",
    "⏳": "waiting",
    "📅": "scheduled",
    "🔧": "in_progress",
    "❓": "undefined",
    "⬜": "pending",
    "🆕": "pending",
}


def _infer_status(text: str) -> str:
    for emoji, status in _STATUS_FROM_EMOJI.items():
        if text.startswith(emoji):
            return status
    return "pending"


def sync_tasks_from_json() -> int:
    """
    Espeja el estado remoto (mando-api en Figaro) a la tabla local `tasks`.
    Como mando_key es "{project_id}_{idx}" (indice de array, no un ID estable),
    borrar/reordenar tareas en remoto deja huerfanos en local si solo hacemos
    upsert -- por eso al final borramos cualquier mando_key que ya no exista
    en el pull actual.
    """
    data = load_data()
    conn = get_connection()
    cur = conn.cursor()
    count = 0
    seen_keys = []

    for project in data:
        project_id = project["id"]
        project_title = project["title"]
        for idx, task in enumerate(project["tasks"]):
            mando_key = f"{project_id}_{idx}"
            seen_keys.append(mando_key)
            title = task["text"]
            priority = task["priority"]
            status = _infer_status(title)

            cur.execute(
                """
                INSERT INTO tasks (mando_key, title, status, priority, project, project_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (mando_key) DO UPDATE SET
                    title      = EXCLUDED.title,
                    priority   = EXCLUDED.priority,
                    project    = EXCLUDED.project,
                    project_id = EXCLUDED.project_id,
                    updated_at = NOW()
                """,
                (mando_key, title, status, priority, project_title, project_id),
            )
            count += 1

    if seen_keys:
        cur.execute("DELETE FROM tasks WHERE NOT (mando_key = ANY(%s))", (seen_keys,))
    else:
        cur.execute("DELETE FROM tasks")

    conn.commit()
    cur.close()
    conn.close()
    return count


def find_tasks_by_keyword(keyword: str, exclude_done: bool = True) -> list:
    conn = get_connection()
    cur = conn.cursor()
    query = """
        SELECT id, mando_key, title, status, priority, project, project_id
        FROM tasks
        WHERE LOWER(title) LIKE LOWER(%s)
        {status_filter}
        ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'mid' THEN 1 ELSE 2 END
        LIMIT 10
    """.format(status_filter="AND status != 'done'" if exclude_done else "")
    cur.execute(query, (f"%{keyword}%",))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def find_tasks_by_project(project_id: str, exclude_done: bool = True) -> list:
    conn = get_connection()
    cur = conn.cursor()
    query = """
        SELECT id, mando_key, title, status, priority, project, project_id
        FROM tasks
        WHERE project_id = %s
        {status_filter}
        ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'mid' THEN 1 ELSE 2 END
    """.format(status_filter="AND status != 'done'" if exclude_done else "")
    cur.execute(query, (project_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def resolve_task_ref(task_ref: str) -> list:
    """Find pending tasks matching a reference (code, keyword, or project)."""
    return find_tasks_by_keyword(task_ref, exclude_done=True)


def complete_task(mando_key: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tasks SET status = 'done', updated_at = NOW() WHERE mando_key = %s",
        (mando_key,),
    )
    updated = cur.rowcount > 0
    conn.commit()
    cur.close()
    conn.close()

    if updated:
        _push_estado_to_mando(mando_key, True)

    return updated


def _push_estado_to_mando(mando_key: str, done: bool):
    """GET current estado, flip the key, POST back."""
    estado = get_estado()
    estado[mando_key] = done
    post_estado(estado)


def add_task_context(mando_key: str, type_: str, content: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tasks WHERE mando_key = %s", (mando_key,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return False
    cur.execute(
        "INSERT INTO task_context (task_id, type, content) VALUES (%s, %s, %s)",
        (row[0], type_, content),
    )
    conn.commit()
    cur.close()
    conn.close()
    return True


def get_task_context(mando_key: str) -> list:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT tc.type, tc.content, tc.created_at
        FROM task_context tc
        JOIN tasks t ON t.id = tc.task_id
        WHERE t.mando_key = %s
        ORDER BY tc.created_at DESC
        LIMIT 10
        """,
        (mando_key,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"type": r[0], "content": r[1], "created_at": str(r[2])} for r in rows]


def get_task_contexts_bulk(mando_keys: list[str]) -> dict[str, list[dict]]:
    """Una sola query para obtener contextos de múltiples tareas."""
    if not mando_keys:
        return {}
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.mando_key, tc.type, tc.content
        FROM task_context tc
        JOIN tasks t ON t.id = tc.task_id
        WHERE t.mando_key = ANY(%s)
        ORDER BY t.mando_key, tc.created_at DESC
        """,
        (mando_keys,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result: dict[str, list[dict]] = {}
    for key, type_, content in rows:
        result.setdefault(key, []).append({"type": type_, "content": content})
    return result


def _row_to_dict(r) -> dict:
    return {
        "id": r[0],
        "mando_key": r[1],
        "title": r[2],
        "status": r[3],
        "priority": r[4],
        "project": r[5],
        "project_id": r[6],
    }
