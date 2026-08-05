"""
alpha50/garmin_actividades.py
Seguimiento de entrenos con Garmin -- piezas 1 (ingesta) y 3 (repaso).

- sincronizar_actividades(dias): baja las actividades recientes de Garmin y las
  guarda en alpha50_cronologia.db, dedup por activityId. Guarda el JSON CRUDO
  entero (Garmin da decenas de metricas -> asi no perdemos ninguna) + columnas
  parseadas para consultar rapido. Para fuerza baja tambien las series/reps.
  Pensada para correr cada manana desde el scheduler (ya tiene sesion valida ->
  sin logins extra ni 429).
- repaso(dias): estadisticas y tendencia (fuerza y carrera) del periodo vs el
  anterior. Cadencia recomendada: semanal (7 dias).
"""
import os
import json
import sqlite3
from datetime import date, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alpha50_cronologia.db")


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = _con()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS garmin_actividades (
            activity_id   INTEGER PRIMARY KEY,      -- Garmin activityId (dedup)
            fecha         TEXT NOT NULL,            -- YYYY-MM-DD
            inicio        TEXT,                     -- startTimeLocal completo
            tipo          TEXT,                     -- typeKey: running/strength_training/cycling...
            nombre        TEXT,
            duracion_s    REAL,
            distancia_m   REAL,
            fc_media      INTEGER,
            fc_max        INTEGER,
            calorias      INTEGER,
            vo2max        REAL,
            te_aerobico   REAL,                     -- aerobic training effect
            te_anaerobico REAL,
            raw_json      TEXT NOT NULL,            -- resumen completo (future-proof)
            ingerido_en   TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS garmin_sets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL,
            orden       INTEGER,
            tipo_set    TEXT,                       -- ACTIVE / REST
            ejercicio   TEXT,
            reps        INTEGER,
            peso        REAL,
            duracion_s  REAL
        );
    """)
    con.commit()
    con.close()


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _i(x):
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _guardar_actividad(con, a: dict):
    inicio = a.get("startTimeLocal") or ""
    con.execute("""
        INSERT OR REPLACE INTO garmin_actividades
            (activity_id, fecha, inicio, tipo, nombre, duracion_s, distancia_m,
             fc_media, fc_max, calorias, vo2max, te_aerobico, te_anaerobico, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        a.get("activityId"),
        inicio[:10] if inicio else date.today().isoformat(),
        inicio,
        (a.get("activityType") or {}).get("typeKey"),
        a.get("activityName"),
        _f(a.get("duration")),
        _f(a.get("distance")),
        _i(a.get("averageHR")),
        _i(a.get("maxHR")),
        _i(a.get("calories")),
        _f(a.get("vO2MaxValue")),
        _f(a.get("aerobicTrainingEffect")),
        _f(a.get("anaerobicTrainingEffect")),
        json.dumps(a, ensure_ascii=False),
    ))


def _guardar_sets(con, aid: int, data: dict):
    con.execute("DELETE FROM garmin_sets WHERE activity_id=?", (aid,))
    for i, st in enumerate((data or {}).get("exerciseSets") or []):
        exs = st.get("exercises") or []
        nombre = ", ".join((e.get("name") or e.get("category") or "?") for e in exs) or None
        con.execute("""
            INSERT INTO garmin_sets (activity_id, orden, tipo_set, ejercicio, reps, peso, duracion_s)
            VALUES (?,?,?,?,?,?,?)
        """, (aid, i + 1, st.get("setType"), nombre,
              _i(st.get("repetitionCount")), _f(st.get("weight")), _f(st.get("duration"))))


def sincronizar_actividades(dias: int = 14, client=None) -> dict:
    """Baja y guarda las actividades de los ultimos `dias`. `client` inyectable
    para test; en produccion reutiliza la sesion Garmin de agente_metrica."""
    init_db()
    if client is None:
        try:
            from alpha50.agente_metrica import _get_garmin_client   # contexto API (raiz en path)
        except ImportError:
            from agente_metrica import _get_garmin_client            # contexto scheduler (alpha50 en path)
        client = _get_garmin_client()

    hoy = date.today()
    desde = (hoy - timedelta(days=dias)).isoformat()
    try:
        acts = client.get_activities_by_date(desde, hoy.isoformat())
    except Exception:
        acts = client.get_activities(0, 30)

    con = _con()
    guardadas = 0
    for a in acts:
        if not a.get("activityId"):
            continue
        _guardar_actividad(con, a)
        tipo = ((a.get("activityType") or {}).get("typeKey") or "").lower()
        if "strength" in tipo:
            try:
                _guardar_sets(con, a["activityId"], client.get_activity_exercise_sets(a["activityId"]))
            except Exception:
                pass  # el resumen ya esta guardado; el detalle es opcional
        guardadas += 1
    con.commit()
    con.close()
    return {"ok": True, "recibidas": len(acts), "guardadas": guardadas, "desde": desde}


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _stats_periodo(con, ini: str, fin: str) -> dict:
    rows = con.execute(
        "SELECT * FROM garmin_actividades WHERE fecha >= ? AND fecha <= ?", (ini, fin)
    ).fetchall()
    corr = [r for r in rows if "running" in (r["tipo"] or "")]
    fuerza = [r for r in rows if "strength" in (r["tipo"] or "")]

    reps_tot = 0
    volumen = 0.0
    for r in fuerza:
        for s in con.execute(
            "SELECT reps, peso FROM garmin_sets WHERE activity_id=? AND tipo_set='ACTIVE'",
            (r["activity_id"],)
        ):
            reps_tot += s["reps"] or 0
            volumen += (s["reps"] or 0) * (s["peso"] or 0)

    return {
        "corr_sesiones":   len(corr),
        "corr_km":         round(sum((r["distancia_m"] or 0) for r in corr) / 1000, 1),
        "corr_fc_media":   _avg([r["fc_media"] for r in corr]),
        "corr_vo2max":     max([r["vo2max"] for r in corr if r["vo2max"]], default=None),
        "corr_te_aerobico": _avg([r["te_aerobico"] for r in corr]),
        "fuerza_sesiones": len(fuerza),
        "fuerza_reps":     reps_tot,
        "fuerza_volumen_kg": round(volumen, 0),
    }


def repaso(dias: int = 7) -> dict:
    """Estadisticas del periodo actual vs el anterior (misma duracion) para ver
    tendencia. Cadencia recomendada: semanal."""
    init_db()
    con = _con()
    hoy = date.today()
    actual = _stats_periodo(con, (hoy - timedelta(days=dias)).isoformat(), hoy.isoformat())
    previo = _stats_periodo(con,
                            (hoy - timedelta(days=2 * dias)).isoformat(),
                            (hoy - timedelta(days=dias + 1)).isoformat())
    con.close()
    return {
        "dias": dias,
        "periodo": f"{(hoy - timedelta(days=dias)).isoformat()} → {hoy.isoformat()}",
        "actual": actual,
        "anterior": previo,
    }
