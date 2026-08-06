"""
Alpha50 · Agente Cronología
Ubicación: C:\\Users\\Usuario\\jarvis\\alpha50\\agente_cronologia.py

Responsabilidades:
- Saber en qué semana y día del plan está JP
- Conocer el tipo de día (cardio / musculacion / descanso)
- Registrar si un entreno fue completado, parcial o saltado
- Si una semana tiene algún día saltado → repetir la semana completa
- Avanzar el calendario día a día automáticamente
"""

import sqlite3
import os
from datetime import date, timedelta
from typing import Optional

# ── CONFIGURACIÓN ────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "alpha50_cronologia.db")

# Calendario semanal por defecto (0=lunes): L/X/S cardio, M/V muscu, J/D descanso.
SEMANA_ALPHA50 = {
    0: {"dia_plan": 1, "nombre": "Lunes",    "tipo": "cardio"},
    1: {"dia_plan": 2, "nombre": "Martes",   "tipo": "musculacion"},
    2: {"dia_plan": 3, "nombre": "Miércoles","tipo": "cardio"},
    3: {"dia_plan": 4, "nombre": "Jueves",   "tipo": "descanso"},
    4: {"dia_plan": 5, "nombre": "Viernes",  "tipo": "musculacion"},
    5: {"dia_plan": 6, "nombre": "Sábado",   "tipo": "cardio"},
    6: {"dia_plan": 7, "nombre": "Domingo",  "tipo": "descanso"},
}

# PrePrincipiante tiene otra estructura: L/M/V/S cardio, X muscu, J/D descanso.
CALENDARIO_PREPRINCIPIANTE = {
    0: {"dia_plan": 1, "nombre": "Lunes",    "tipo": "cardio"},
    1: {"dia_plan": 2, "nombre": "Martes",   "tipo": "cardio"},
    2: {"dia_plan": 3, "nombre": "Miércoles","tipo": "musculacion"},
    3: {"dia_plan": 4, "nombre": "Jueves",   "tipo": "descanso"},
    4: {"dia_plan": 5, "nombre": "Viernes",  "tipo": "cardio"},
    5: {"dia_plan": 6, "nombre": "Sábado",   "tipo": "cardio"},
    6: {"dia_plan": 7, "nombre": "Domingo",  "tipo": "descanso"},
}

# Avanzado: L/V musculación, M/S HIIT, X anaeróbico (escaladores), J/D descanso.
CALENDARIO_AVANZADO = {
    0: {"dia_plan": 1, "nombre": "Lunes",    "tipo": "musculacion"},
    1: {"dia_plan": 2, "nombre": "Martes",   "tipo": "hiit"},
    2: {"dia_plan": 3, "nombre": "Miércoles","tipo": "anaerobico"},
    3: {"dia_plan": 4, "nombre": "Jueves",   "tipo": "descanso"},
    4: {"dia_plan": 5, "nombre": "Viernes",  "tipo": "musculacion"},
    5: {"dia_plan": 6, "nombre": "Sábado",   "tipo": "hiit"},
    6: {"dia_plan": 7, "nombre": "Domingo",  "tipo": "descanso"},
}

# Calendario por nivel (los que no estén aquí usan SEMANA_ALPHA50).
CALENDARIO_NIVEL = {
    "PrePrincipiante": CALENDARIO_PREPRINCIPIANTE,
    "Avanzado":        CALENDARIO_AVANZADO,
}


def _calendario(nivel: str) -> dict:
    return CALENDARIO_NIVEL.get(nivel, SEMANA_ALPHA50)


ESTADOS_VALIDOS = ("completado", "parcial", "saltado", "descanso", "otro")
# 'otro' = entrenó ese día, pero NO lo que tocaba (p.ej. correr en día de fuerza).
# Queda constancia de que se movió, pero no completa el día del plan (la semana no
# avanza por 'otro' -> el plan sigue siendo el estándar, y toca bronca).

# Orden de progresión de niveles. Al completar la última semana de un nivel sin
# días saltados, el programa avanza automáticamente al siguiente.
NIVELES_ORDEN = ["PrePrincipiante", "Principiante", "Intermedio", "Avanzado", "Bestia", "Gladiador"]

# Nº de semanas por nivel (los que no estén aquí → 12).
SEMANAS_NIVEL = {"PrePrincipiante": 8}


def _semanas_de(nivel: str) -> int:
    return SEMANAS_NIVEL.get(nivel, 12)


def _siguiente_nivel(nivel: str) -> Optional[str]:
    """Devuelve el nivel siguiente en la progresión, o None si es el último."""
    try:
        i = NIVELES_ORDEN.index(nivel)
    except ValueError:
        return None
    return NIVELES_ORDEN[i + 1] if i + 1 < len(NIVELES_ORDEN) else None

# ── INIT BD ──────────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS estado_programa (
            id              INTEGER PRIMARY KEY CHECK (id = 1),
            nivel           TEXT    NOT NULL DEFAULT 'Intermedio',
            semana_plan     INTEGER NOT NULL DEFAULT 1,
            fecha_inicio    TEXT    NOT NULL,   -- ISO: YYYY-MM-DD inicio semana actual
            semanas_totales INTEGER NOT NULL DEFAULT 12
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS historial_dias (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha           TEXT    NOT NULL UNIQUE,  -- ISO: YYYY-MM-DD
            nivel           TEXT,                      -- Principiante/Intermedio/...
            semana_plan     INTEGER NOT NULL,
            dia_plan        INTEGER NOT NULL,          -- 1-7
            nombre_dia      TEXT    NOT NULL,
            tipo            TEXT    NOT NULL,          -- cardio/musculacion/descanso
            opcion_cardio   TEXT,                      -- carrera/bici/hiit (solo cardio)
            estado          TEXT,                      -- completado/parcial/saltado/descanso
            completado_hasta TEXT,                     -- ej: "3 de 4 series" / "20 min de 40"
            fc_media        INTEGER,
            sensacion       INTEGER,                   -- 1-5
            notas           TEXT,
            registrado_en   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    # Migración: añadir 'nivel' si la tabla ya existía sin esa columna
    cols = [r[1] for r in con.execute("PRAGMA table_info(historial_dias)").fetchall()]
    if "nivel" not in cols:
        con.execute("ALTER TABLE historial_dias ADD COLUMN nivel TEXT")
    con.commit()
    con.close()


# ── ARRANQUE INICIAL ─────────────────────────────────────────────────────────
def iniciar_programa(nivel: str = "PrePrincipiante", semana_inicio: int = 1,
                     fecha_inicio: date = None) -> dict:
    """
    Llama esto una sola vez para arrancar el programa.
    fecha_inicio debe ser un LUNES.
    """
    if fecha_inicio is None:
        fecha_inicio = date.today()
        # Ajustar al lunes de esta semana
        fecha_inicio -= timedelta(days=fecha_inicio.weekday())

    con = sqlite3.connect(DB_PATH)
    con.execute("""
        INSERT OR REPLACE INTO estado_programa (id, nivel, semana_plan, fecha_inicio, semanas_totales)
        VALUES (1, ?, ?, ?, ?)
    """, (nivel, semana_inicio, fecha_inicio.isoformat(), _semanas_de(nivel)))
    con.commit()
    con.close()

    return {
        "ok": True,
        "mensaje": f"Programa iniciado: {nivel} · Semana {semana_inicio} · desde {fecha_inicio}",
        "nivel": nivel,
        "semana_plan": semana_inicio,
        "fecha_inicio": fecha_inicio.isoformat(),
    }


def cambiar_nivel(nivel: str, semana_inicio: int = 1,
                  fecha_inicio: date = None) -> dict:
    """
    Cambia el nivel actual del programa (p. ej. empezar en Principiante).
    Reinicia la semana y ancla el inicio al lunes de esta semana.
    """
    if nivel not in NIVELES_ORDEN:
        return {"error": f"Nivel inválido. Usa uno de: {NIVELES_ORDEN}"}
    return iniciar_programa(nivel, semana_inicio, fecha_inicio)


# ── ESTADO HOY ───────────────────────────────────────────────────────────────
def get_estado_hoy(hoy: date = None) -> dict:
    """
    Devuelve qué toca hoy según el plan.
    Tiene en cuenta si la semana anterior tuvo días saltados (→ repite semana).
    """
    if hoy is None:
        hoy = date.today()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    programa = con.execute("SELECT * FROM estado_programa WHERE id=1").fetchone()
    if not programa:
        con.close()
        return {"error": "Programa no iniciado. Llama a iniciar_programa() primero."}

    # Calcular semana_plan real (con posibles repeticiones)
    semana_plan = _calcular_semana_real(con, programa, hoy)

    # Día de la semana (0=lunes) según el calendario del nivel actual
    dow = hoy.weekday()
    meta = _calendario(programa["nivel"])[dow]

    # ¿Ya hay registro de hoy?
    registro = con.execute(
        "SELECT * FROM historial_dias WHERE fecha=?", (hoy.isoformat(),)
    ).fetchone()

    con.close()

    resultado = {
        "fecha": hoy.isoformat(),
        "nivel": programa["nivel"],
        "semana_plan": semana_plan,
        "dia_plan": meta["dia_plan"],
        "nombre_dia": meta["nombre"],
        "tipo": meta["tipo"],
        "ya_registrado": registro is not None,
    }
    if registro:
        resultado["estado"] = registro["estado"]
        resultado["opcion_cardio"] = registro["opcion_cardio"]

    return resultado


# ── REGISTRAR DÍA ────────────────────────────────────────────────────────────
def registrar_dia(estado: str, opcion_cardio: str = None,
                  completado_hasta: str = None, fc_media: int = None,
                  sensacion: int = None, notas: str = None,
                  hoy: date = None) -> dict:
    """
    Registra el resultado del día de hoy.

    estado: 'completado' | 'parcial' | 'saltado' | 'descanso'
    opcion_cardio: 'carrera' | 'bici' | 'hiit'  (solo días cardio)
    completado_hasta: texto libre si fue parcial  ej: "20 min de 40"
    fc_media: frecuencia cardíaca media del entreno
    sensacion: 1-5
    notas: texto libre
    """
    if estado not in ESTADOS_VALIDOS:
        return {"error": f"Estado inválido. Usa: {ESTADOS_VALIDOS}"}

    if hoy is None:
        hoy = date.today()

    estado_hoy = get_estado_hoy(hoy)
    if "error" in estado_hoy:
        return estado_hoy

    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("""
            INSERT OR REPLACE INTO historial_dias
                (fecha, nivel, semana_plan, dia_plan, nombre_dia, tipo,
                 opcion_cardio, estado, completado_hasta, fc_media, sensacion, notas)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            hoy.isoformat(),
            estado_hoy["nivel"],
            estado_hoy["semana_plan"],
            estado_hoy["dia_plan"],
            estado_hoy["nombre_dia"],
            estado_hoy["tipo"],
            opcion_cardio,
            estado,
            completado_hasta,
            fc_media,
            sensacion,
            notas,
        ))
        con.commit()

        # ¿Hay que avanzar de semana o de nivel?
        avance = _evaluar_avance_semana(con, estado_hoy["nivel"],
                                        estado_hoy["semana_plan"], hoy)

    finally:
        con.close()

    return {
        "ok": True,
        "fecha": hoy.isoformat(),
        "semana_plan": estado_hoy["semana_plan"],
        "dia": estado_hoy["nombre_dia"],
        "estado": estado,
        "avance": avance,
    }


# ── RESUMEN DE SEMANA ────────────────────────────────────────────────────────
def get_resumen_semana(semana_plan: int = None) -> dict:
    """
    Devuelve el resumen de una semana: días completados, parciales, saltados.
    Si semana_plan es None → semana actual.
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    programa = con.execute("SELECT * FROM estado_programa WHERE id=1").fetchone()
    if not programa:
        con.close()
        return {"error": "Programa no iniciado."}
    nivel = programa["nivel"]
    if semana_plan is None:
        semana_plan = _calcular_semana_real(con, programa, date.today())

    dias = con.execute(
        "SELECT * FROM historial_dias WHERE semana_plan=? ORDER BY dia_plan",
        (semana_plan,)
    ).fetchall()
    completa = _semana_completa(con, nivel, semana_plan)
    con.close()

    completados = sum(1 for d in dias if d["estado"] == "completado")
    parciales   = sum(1 for d in dias if d["estado"] == "parcial")
    saltados    = sum(1 for d in dias if d["estado"] == "saltado")

    return {
        "semana_plan": semana_plan,
        "dias_registrados": len(dias),
        "completados": completados,
        "parciales": parciales,
        "saltados": saltados,
        "se_repetira_semana": not completa,
        "detalle": [dict(d) for d in dias],
    }


# ── HELPERS INTERNOS ─────────────────────────────────────────────────────────
# Estados que cuentan como "entreno hecho" ese dia (fue, aunque fuera a medias).
HECHO = ("completado", "parcial")


def _semana_completa(con, nivel: str, semana: int) -> bool:
    """True solo si TODOS los dias de entreno de la semana tienen entreno hecho
    (completado o parcial). Un dia de entreno SIN registrar cuenta como NO hecho.

    Este es el fix del bug: antes se miraba solo el estado 'saltado', asi que si
    JP no entrenaba y no anotaba nada, no habia fila 'saltado' y la semana
    avanzaba igual. Ahora, si falta el entreno de cualquier dia de entreno, la
    semana NO se da por hecha y se repite."""
    dias_entreno = [m["dia_plan"] for m in _calendario(nivel).values() if m["tipo"] != "descanso"]
    for dp in dias_entreno:
        row = con.execute(
            "SELECT estado FROM historial_dias WHERE nivel=? AND semana_plan=? AND dia_plan=?",
            (nivel, semana, dp),
        ).fetchone()
        if not row or row[0] not in HECHO:
            return False
    return True


def _calcular_semana_real(con, programa, hoy: date) -> int:
    """
    Calcula la semana de plan real teniendo en cuenta repeticiones.
    Lógica: por cada semana completada con algún día saltado → no avanza semana_plan.
    """
    fecha_inicio = date.fromisoformat(programa["fecha_inicio"])
    dias_transcurridos = (hoy - fecha_inicio).days
    semanas_calendario = dias_transcurridos // 7

    semana_real = programa["semana_plan"]
    semanas_extra = 0

    # Contar cuántas semanas (del nivel actual) NO se completaron -> no avanzan.
    # Incluye la semana en curso: mientras falten entrenos, no pasa de semana.
    for s in range(1, semana_real + semanas_calendario):
        if not _semana_completa(con, programa["nivel"], s):
            semanas_extra += 1

    semana_real = min(
        programa["semana_plan"] + semanas_calendario - semanas_extra,
        _semanas_de(programa["nivel"])
    )
    return max(1, semana_real)


def _evaluar_avance_semana(con, nivel: str, semana_actual: int, hoy: date) -> dict:
    """
    Comprueba (los domingos) si la semana debe avanzar, repetirse, o si el nivel
    está completo y hay que pasar al siguiente nivel de la progresión.
    """
    if hoy.weekday() != 6:  # No es domingo
        return {"accion": "ninguna"}

    if not _semana_completa(con, nivel, semana_actual):
        return {
            "accion": "repetir_semana",
            "motivo": "semana incompleta -- falta el entreno de algun dia",
            "semana_siguiente": semana_actual,
        }

    total = _semanas_de(nivel)   # nº de semanas de ESTE nivel (8 pre, 12 resto)

    siguiente = semana_actual + 1
    if siguiente <= total:
        con.execute("UPDATE estado_programa SET semana_plan=? WHERE id=1", (siguiente,))
        con.commit()
        return {"accion": "avanzar_semana", "semana_siguiente": siguiente}

    # Nivel completado → pasar al siguiente nivel de la progresión
    nuevo = _siguiente_nivel(nivel)
    if nuevo:
        lunes = hoy + timedelta(days=1)   # hoy es domingo → el próximo lunes
        con.execute(
            "UPDATE estado_programa SET nivel=?, semana_plan=1, fecha_inicio=?, semanas_totales=? WHERE id=1",
            (nuevo, lunes.isoformat(), _semanas_de(nuevo))
        )
        con.commit()
        return {
            "accion": "avanzar_nivel",
            "nivel_anterior": nivel,
            "nivel_nuevo": nuevo,
            "semana_siguiente": 1,
        }

    return {"accion": "programa_completado", "nivel": nivel}


# ── CLI / TEST ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json, sys

    init_db()

    cmd = sys.argv[1] if len(sys.argv) > 1 else "estado"

    if cmd == "init":
        # python agente_cronologia.py init [semana] [YYYY-MM-DD]
        sem = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        fecha = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else None
        print(json.dumps(iniciar_programa(semana_inicio=sem, fecha_inicio=fecha),
                         ensure_ascii=False, indent=2))

    elif cmd == "estado":
        print(json.dumps(get_estado_hoy(), ensure_ascii=False, indent=2))

    elif cmd == "registrar":
        # python agente_cronologia.py registrar completado [carrera] [sensacion]
        estado_arg    = sys.argv[2] if len(sys.argv) > 2 else "completado"
        opcion_arg    = sys.argv[3] if len(sys.argv) > 3 else None
        sensacion_arg = int(sys.argv[4]) if len(sys.argv) > 4 else None
        print(json.dumps(
            registrar_dia(estado_arg, opcion_cardio=opcion_arg, sensacion=sensacion_arg),
            ensure_ascii=False, indent=2
        ))

    elif cmd == "resumen":
        sem = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(json.dumps(get_resumen_semana(sem), ensure_ascii=False, indent=2))

    elif cmd == "nivel":
        # python agente_cronologia.py nivel Principiante [semana]
        niv = sys.argv[2] if len(sys.argv) > 2 else "Principiante"
        sem = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        print(json.dumps(cambiar_nivel(niv, sem), ensure_ascii=False, indent=2))

    else:
        print(f"Comandos: init | estado | registrar | resumen | nivel <Nivel> [semana]")
