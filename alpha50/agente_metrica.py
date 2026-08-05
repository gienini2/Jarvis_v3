"""
Alpha50 · Agente Métricas
Ubicación: C:\\Users\\Usuario\\jarvis\\alpha50\\agente_metrica.py

Responsabilidades:
- Conectar a Garmin Connect y descargar métricas del día anterior/noche
- Calcular índice de disposición (0-100)
- Guardar historial de métricas en SQLite
- Fase 0: admite entrada manual si Garmin no está disponible
- Fase 1: automático cada mañana vía Garmin Connect API

Instalación dependencia:
    pip install garminconnect
"""

import os
import json
import time
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

# ── CONFIGURACIÓN ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
DB_PATH  = os.path.join(BASE_DIR, "alpha50_cronologia.db")

# Credenciales Garmin — añadir al .env de Jarvis
GARMIN_EMAIL    = os.environ.get("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "")
# El scheduler hace load_dotenv (env), pero desde la API principal el .env solo
# vive en settings (Pydantic). Fallback a settings para que Garmin funcione en ambos.
if not GARMIN_EMAIL or not GARMIN_PASSWORD:
    try:
        from config.settings import settings
        GARMIN_EMAIL    = GARMIN_EMAIL or getattr(settings, "GARMIN_EMAIL", "")
        GARMIN_PASSWORD = GARMIN_PASSWORD or getattr(settings, "GARMIN_PASSWORD", "")
    except Exception:
        pass

# Persistencia de sesión Garmin (tokens OAuth). Reutilizar la sesión evita el
# login en cada arranque, que es la causa real del bloqueo 429 (rate limit).
GARMIN_TOKENSTORE = os.environ.get(
    "GARMIN_TOKENSTORE", os.path.join(BASE_DIR, ".garmin_session")
)

# Reintentos con backoff ante 429 / fallos transitorios
GARMIN_MAX_RETRIES   = int(os.environ.get("GARMIN_MAX_RETRIES", "3"))
GARMIN_BACKOFF_BASE  = int(os.environ.get("GARMIN_BACKOFF_BASE", "20"))  # segundos: 20, 40, 80...

# Antigüedad máxima (días) de una lectura cacheada para usarla como fallback
GARMIN_CACHE_MAX_DIAS = int(os.environ.get("GARMIN_CACHE_MAX_DIAS", "3"))

# Pesos para el índice de disposición (deben sumar 100)
PESOS = {
    "body_battery":     35,   # Energía disponible al despertar
    "calidad_sueno":    25,   # Score sueño (horas + fases)
    "hrv":              20,   # Variabilidad cardíaca nocturna
    "fc_reposo":        10,   # FC reposo vs media personal
    "estres_ayer":      10,   # Estrés acumulado día anterior
}

# Umbrales para semáforo
UMBRALES = {
    "verde":   75,   # Entreno completo
    "amarillo":50,   # Entreno reducido (-20% series/tiempo)
    "naranja": 30,   # Solo movilidad/cardio muy suave
    # < 30         → descanso activo
}


# ── INIT BD ──────────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS metricas_diarias (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha           TEXT    NOT NULL UNIQUE,
            -- Garmin / manual
            body_battery    INTEGER,          -- 0-100
            horas_sueno     REAL,             -- horas totales
            sueno_profundo  INTEGER,          -- minutos
            sueno_rem       INTEGER,          -- minutos
            sueno_score     INTEGER,          -- 0-100 si Garmin lo da
            hrv_valor       INTEGER,          -- ms
            hrv_status      TEXT,             -- balanced/unbalanced/low/poor
            fc_reposo       INTEGER,          -- ppm
            estres_promedio INTEGER,          -- 0-100
            pasos           INTEGER,
            spo2_nocturno   INTEGER,          -- % saturación O2
            calorias_activas INTEGER,
            -- Calculado
            indice_disposicion INTEGER,       -- 0-100
            semaforo        TEXT,             -- verde/amarillo/naranja/rojo
            -- Peso semanal (solo lunes)
            peso_kg         REAL,
            -- Fuente del dato
            fuente          TEXT DEFAULT 'garmin',  -- garmin / manual
            registrado_en   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.commit()
    con.close()


# ── CONEXIÓN GARMIN ───────────────────────────────────────────────────────────
def _es_rate_limit(e: Exception) -> bool:
    """Detecta si la excepción es un 429 / Too Many Requests."""
    nombre = type(e).__name__.lower()
    txt    = str(e).lower()
    return ("toomanyrequests" in nombre or "429" in txt
            or "too many requests" in txt or "rate limit" in txt)


def _login_garmin():
    """
    Un intento de login. Reutiliza la sesión guardada (tokenstore) si existe;
    solo hace login completo con email/password cuando no hay sesión válida.
    Esto evita autenticar en cada arranque → previene el bloqueo 429.
    """
    from garminconnect import Garmin

    # 1. Intentar reanudar sesión guardada (no consume cuota de login)
    if os.path.isdir(GARMIN_TOKENSTORE) and os.listdir(GARMIN_TOKENSTORE):
        try:
            client = Garmin()
            client.login(GARMIN_TOKENSTORE)
            return client
        except Exception:
            pass  # sesión caducada/corrupta → login completo abajo

    # 2. Login completo con credenciales y persistir tokens para la próxima
    if not (GARMIN_EMAIL and GARMIN_PASSWORD):
        raise RuntimeError("Faltan GARMIN_EMAIL / GARMIN_PASSWORD en el .env")

    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()
    try:
        os.makedirs(GARMIN_TOKENSTORE, exist_ok=True)
        client.garth.dump(GARMIN_TOKENSTORE)
    except Exception:
        pass  # si no se puede guardar, seguimos igualmente
    return client


def _get_garmin_client():
    """
    Devuelve un cliente Garmin autenticado, con reintentos y backoff
    exponencial ante 429 / fallos transitorios.
    """
    try:
        import garminconnect  # noqa: F401
    except ImportError:
        raise RuntimeError("Instala garminconnect: pip install garminconnect")

    ultimo_error = None
    for intento in range(GARMIN_MAX_RETRIES):
        try:
            return _login_garmin()
        except Exception as e:
            ultimo_error = e
            if _es_rate_limit(e) and intento < GARMIN_MAX_RETRIES - 1:
                espera = GARMIN_BACKOFF_BASE * (2 ** intento)
                time.sleep(espera)
                continue
            break

    raise RuntimeError(f"Error conectando a Garmin: {ultimo_error}")


# ── CAMPOS DEL ÍNDICE Y DATOS FALTANTES ───────────────────────────────────────
# (nombre corto legible, etiqueta de pregunta, ejemplo) por cada métrica clave.
CAMPO_ETIQUETA = {
    "body_battery": ("Body Battery", "Body Battery al despertar (0-100)",     "80"),
    "sueno":        ("sueño",        "Puntuación de sueño (0-100)",           "80"),
    "hrv":          ("VFC",          "VFC (equilibrado/normal/bajo/malo)",    "bajo"),
    "fc_reposo":    ("FC reposo",    "FC reposo en ppm",                      "54"),
    "peso":         ("peso",         "Peso de hoy en kg",                     "98"),
}


def _campos_faltantes(m: dict, hoy: date = None) -> list:
    """Lista ordenada de métricas clave que Garmin NO trajo, para pedírselas al usuario."""
    hoy = hoy or date.today()
    faltan = []
    if m.get("body_battery") is None:
        faltan.append("body_battery")
    if m.get("sueno_score") is None and not m.get("horas_sueno"):
        faltan.append("sueno")
    if not m.get("hrv_status") and not m.get("hrv_valor"):
        faltan.append("hrv")
    if m.get("fc_reposo") is None:
        faltan.append("fc_reposo")
    if not m.get("peso_kg"):   # el peso siempre es manual (Garmin no lo aporta)
        faltan.append("peso")
    return faltan


def _preguntas_faltantes(faltan: list) -> str:
    """Mensaje que pide SOLO las métricas que faltan, en orden. El peso siempre
    es manual, así que se pide aparte y no bajo 'no pude recoger de Garmin'."""
    garmin_faltan = [f for f in faltan if f != "peso"]
    lineas = ["👋 Buenos días JP"]
    if garmin_faltan:
        legibles = ", ".join(CAMPO_ETIQUETA[f][0] for f in garmin_faltan)
        lineas.append(f"Hoy no pude recoger de Garmin: *{legibles}*.")
    lineas += ["Dime estos datos (míralos en el reloj) 👇", ""]
    for i, f in enumerate(faltan, 1):
        lineas.append(f"{i}. {CAMPO_ETIQUETA[f][1]}")
    ejemplo = " / ".join(CAMPO_ETIQUETA[f][2] for f in faltan)
    lineas += ["", f"Respóndeme en ese orden, separado por / . Ej: *{ejemplo}*"]
    return "\n".join(lineas)


# ── DESCARGA AUTOMÁTICA GARMIN ────────────────────────────────────────────────
def descargar_garmin(para_fecha: date = None) -> dict:
    """
    Descarga todas las métricas relevantes de Garmin Connect.
    para_fecha: fecha de la que queremos datos (por defecto ayer/hoy según hora)
    """
    if para_fecha is None:
        # Los datos de sueño/HRV son del día anterior por la mañana
        para_fecha = date.today()

    fecha_str = para_fecha.isoformat()

    try:
        client = _get_garmin_client()
        metricas = {"fecha": fecha_str, "fuente": "garmin"}

        # Estadísticas diarias (se reutilizan para Body Battery y FC/estrés)
        try:
            stats = client.get_stats(fecha_str) or {}
        except Exception:
            stats = {}

        # Body Battery "al despertar" = PICO del día. Preferimos el máximo diario
        # que reporta Garmin (no depende de la hora de consulta); si no está,
        # usamos el máximo del array de valores. (Antes cogía las 00:00 → ≈9 mal.)
        bb = None
        for k in ("bodyBatteryAtWakeTime", "bodyBatteryHighestValue", "bodyBatteryMostRecentValue"):
            if stats.get(k) is not None:
                bb = stats.get(k)
                break
        if bb is None:
            try:
                bb_data = client.get_body_battery(fecha_str)
                if bb_data and len(bb_data) > 0:
                    valores = bb_data[0].get("bodyBatteryValuesArray", []) or []
                    niveles = [v[1] for v in valores
                               if v and len(v) > 1 and isinstance(v[1], (int, float))]
                    if niveles:
                        bb = max(niveles)
            except Exception:
                pass
        metricas["body_battery"] = bb

        # Sueño → priorizamos la PUNTUACIÓN de sueño (0-100), no las horas.
        try:
            sueno = client.get_sleep_data(fecha_str)
            if sueno and "dailySleepDTO" in sueno:
                dto = sueno["dailySleepDTO"]
                metricas["horas_sueno"]    = round(dto.get("sleepTimeSeconds", 0) / 3600, 1)
                metricas["sueno_profundo"] = dto.get("deepSleepSeconds", 0) // 60
                metricas["sueno_rem"]      = dto.get("remSleepSeconds", 0) // 60
                # La puntuación puede venir en dto.sleepScores.overall.value o en
                # el nivel superior según la versión de Garmin.
                score = (dto.get("sleepScores", {}).get("overall", {}) or {}).get("value")
                if score is None:
                    score = (sueno.get("sleepScores", {}).get("overall", {}) or {}).get("value")
                if score is None:
                    score = dto.get("sleepScoreValue") or sueno.get("overallSleepScore")
                metricas["sueno_score"] = score
        except Exception:
            pass

        # HRV
        try:
            hrv = client.get_hrv_data(fecha_str)
            if hrv and "hrvSummary" in hrv:
                summary = hrv["hrvSummary"]
                # El valor real de anoche es 'lastNightAvg' (ms); 'status' es el
                # estado VFC relativo a tu baseline (BALANCED/UNBALANCED/LOW/POOR).
                metricas["hrv_valor"]  = summary.get("lastNightAvg") or summary.get("lastNight")
                metricas["hrv_status"] = (summary.get("status", "") or "").lower()
        except Exception:
            pass

        # FC reposo + estrés + pasos (de las estadísticas ya obtenidas)
        if stats:
            metricas["fc_reposo"]        = stats.get("restingHeartRate")
            metricas["estres_promedio"]  = stats.get("averageStressLevel")
            metricas["pasos"]            = stats.get("totalSteps")
            metricas["calorias_activas"] = stats.get("activeKilocalories")

        # SpO2 nocturno
        try:
            spo2 = client.get_spo2_data(fecha_str)
            if spo2 and "spO2HRSleepData" in spo2:
                avg = spo2["spO2HRSleepData"].get("averageSpO2")
                metricas["spo2_nocturno"] = avg
        except Exception:
            pass

        # Devolvemos lo que haya (aunque sea parcial). Quien llame decidirá qué
        # métricas faltan y se las pedirá al usuario, sin inventar neutros.
        return metricas

    except RuntimeError as e:
        return {"error": str(e), "fecha": fecha_str}


# ── DEBUG GARMIN ──────────────────────────────────────────────────────────────
def debug_garmin(para_fecha: date = None) -> str:
    """Vuelca los campos crudos relevantes que devuelve Garmin, para clavar los
    nombres exactos (Body Battery, sueño, VFC) en el reloj/versión del usuario."""
    fs = (para_fecha or date.today()).isoformat()
    try:
        client = _get_garmin_client()
    except Exception as e:
        return f"No conecto con Garmin: {e}"
    out = [f"🔧 Garmin debug — {fs}"]
    try:
        stats = client.get_stats(fs) or {}
        bb = {k: v for k, v in stats.items() if "battery" in k.lower()}
        out.append("BodyBattery (get_stats): " + (json.dumps(bb, ensure_ascii=False) if bb else "(ninguno)"))
        out.append("restingHeartRate: " + str(stats.get("restingHeartRate")))
        out.append("averageStressLevel: " + str(stats.get("averageStressLevel")))
    except Exception as e:
        out.append(f"stats error: {e}")
    try:
        sueno = client.get_sleep_data(fs) or {}
        dto = sueno.get("dailySleepDTO", {}) or {}
        out.append("sleepScores.overall.value: " + str((dto.get("sleepScores", {}).get("overall", {}) or {}).get("value")))
        out.append("sleepTimeSeconds: " + str(dto.get("sleepTimeSeconds")))
    except Exception as e:
        out.append(f"sleep error: {e}")
    try:
        hrv = client.get_hrv_data(fs) or {}
        out.append("hrvSummary: " + json.dumps(hrv.get("hrvSummary", {}), ensure_ascii=False)[:300])
    except Exception as e:
        out.append(f"hrv error: {e}")
    return "\n".join(out)


# ── ENTRADA MANUAL ────────────────────────────────────────────────────────────
def entrada_manual(body_battery: int, horas_sueno: float,
                   sensacion_sueno: int,  # 1-5 → convertimos a score
                   hrv_status: str = "unknown",
                   fc_reposo: int = None,
                   estres_ayer: int = None,
                   peso_kg: float = None,
                   para_fecha: date = None) -> dict:
    """
    Registro manual cuando Garmin no está disponible o el usuario
    prefiere introducir los datos por Telegram.

    sensacion_sueno: 1=muy mal, 2=mal, 3=regular, 4=bien, 5=muy bien
    hrv_status: 'bueno' | 'normal' | 'bajo' | 'malo'
    """
    if para_fecha is None:
        para_fecha = date.today()

    # Convertir sensación de sueño (1-5) a score aproximado (0-100)
    score_map = {1: 20, 2: 40, 3: 60, 4: 80, 5: 95}
    sueno_score = score_map.get(sensacion_sueno, 60)

    # Convertir hrv_status textual a numérico aproximado
    hrv_map = {"bueno": 85, "normal": 65, "bajo": 40, "malo": 20, "unknown": 60}
    hrv_valor = hrv_map.get(hrv_status.lower(), 60)

    return {
        "fecha":           para_fecha.isoformat(),
        "fuente":          "manual",
        "body_battery":    body_battery,
        "horas_sueno":     horas_sueno,
        "sueno_score":     sueno_score,
        "hrv_valor":       hrv_valor,
        "hrv_status":      hrv_status,
        "fc_reposo":       fc_reposo,
        "estres_promedio": estres_ayer or 30,
        "peso_kg":         peso_kg,
    }


# ── CALCULAR ÍNDICE ───────────────────────────────────────────────────────────
def calcular_indice(metricas: dict) -> dict:
    """
    Calcula el índice de disposición (0-100) y el semáforo.
    Funciona con datos Garmin o manuales.
    """
    puntos = {}

    # 1. Body Battery (0-100 → directo)
    bb = metricas.get("body_battery")
    if bb is not None:
        puntos["body_battery"] = min(100, max(0, bb))
    else:
        puntos["body_battery"] = 50  # neutro si no hay dato

    # 2. Calidad sueño
    score_sueno = metricas.get("sueno_score")
    if score_sueno is None:
        # Calcular desde horas si no hay score directo
        horas = metricas.get("horas_sueno") or 0   # None-safe (clave puede existir con None)
        if   horas >= 8:   score_sueno = 95
        elif horas >= 7:   score_sueno = 80
        elif horas >= 6:   score_sueno = 60
        elif horas >= 5:   score_sueno = 35
        else:              score_sueno = 15
    puntos["calidad_sueno"] = min(100, max(0, score_sueno))

    # 3. VFC (HRV). El ESTADO que da Garmin (relativo a TU baseline) es la señal
    # fiable; el valor absoluto en ms no es comparable entre personas, así que
    # solo se usa como estimación cuando no hay estado.
    hrv_status = (metricas.get("hrv_status") or "").lower()
    hrv_map_status = {
        "balanced": 90, "bueno": 90,
        "normal": 65,
        "unbalanced": 40, "bajo": 40,
        "poor": 20, "low": 20, "malo": 20,
    }
    if hrv_status in hrv_map_status:
        hrv_score = hrv_map_status[hrv_status]        # confiar en el estado VFC
    else:
        hrv_val = metricas.get("hrv_valor")
        if hrv_val and hrv_val > 0:
            hrv_score = (85 if hrv_val >= 60 else 65 if hrv_val >= 40
                         else 50 if hrv_val >= 25 else 30)
        else:
            hrv_score = 60                            # sin dato → neutro
    puntos["hrv"] = hrv_score

    # 4. FC reposo
    # Sin historial personal usamos rangos generales
    # Con historial, comparamos vs media personal
    fc = metricas.get("fc_reposo")
    if fc is None:
        puntos["fc_reposo"] = 60  # neutro
    elif fc <= 55:  puntos["fc_reposo"] = 95
    elif fc <= 65:  puntos["fc_reposo"] = 80
    elif fc <= 75:  puntos["fc_reposo"] = 65
    elif fc <= 85:  puntos["fc_reposo"] = 45
    elif fc <= 95:  puntos["fc_reposo"] = 30
    else:           puntos["fc_reposo"] = 15

    # 5. Estrés ayer (invertido: menos estrés = mejor)
    estres = metricas.get("estres_promedio")
    if estres is None:                       # clave puede existir con None (Garmin parcial)
        estres = 30                          # neutro si no hay dato
    if   estres <= 25: puntos["estres_ayer"] = 90
    elif estres <= 40: puntos["estres_ayer"] = 70
    elif estres <= 55: puntos["estres_ayer"] = 50
    elif estres <= 70: puntos["estres_ayer"] = 30
    else:              puntos["estres_ayer"] = 15

    # Índice ponderado
    indice = sum(puntos[k] * PESOS[k] / 100 for k in PESOS)
    indice = round(indice)

    # Semáforo
    if   indice >= UMBRALES["verde"]:   semaforo = "verde"
    elif indice >= UMBRALES["amarillo"]:semaforo = "amarillo"
    elif indice >= UMBRALES["naranja"]: semaforo = "naranja"
    else:                               semaforo = "rojo"

    emoji_map = {"verde": "🟢", "amarillo": "🟡", "naranja": "🟠", "rojo": "🔴"}

    return {
        "indice":   indice,
        "semaforo": semaforo,
        "emoji":    emoji_map[semaforo],
        "puntos":   puntos,
        "detalle":  _texto_semaforo(semaforo, indice),
    }


def _texto_semaforo(semaforo: str, indice: int) -> str:
    textos = {
        "verde":    f"✅ Disposición ALTA ({indice}/100) — Entreno completo según plan",
        "amarillo": f"⚠️ Disposición MEDIA ({indice}/100) — Reduce intensidad un 20%",
        "naranja":  f"🔶 Disposición BAJA ({indice}/100) — Solo movilidad o cardio muy suave",
        "rojo":     f"🛑 Disposición MUY BAJA ({indice}/100) — Descanso activo hoy",
    }
    return textos.get(semaforo, "")


# ── GUARDAR EN BD ─────────────────────────────────────────────────────────────
def guardar_metricas(metricas: dict, indice_resultado: dict,
                     peso_kg: float = None) -> dict:
    """Persiste las métricas y el índice calculado en SQLite."""
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("""
            INSERT OR REPLACE INTO metricas_diarias (
                fecha, body_battery, horas_sueno, sueno_profundo, sueno_rem,
                sueno_score, hrv_valor, hrv_status, fc_reposo, estres_promedio,
                pasos, spo2_nocturno, calorias_activas,
                indice_disposicion, semaforo, peso_kg, fuente
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            metricas.get("fecha"),
            metricas.get("body_battery"),
            metricas.get("horas_sueno"),
            metricas.get("sueno_profundo"),
            metricas.get("sueno_rem"),
            metricas.get("sueno_score"),
            metricas.get("hrv_valor"),
            metricas.get("hrv_status"),
            metricas.get("fc_reposo"),
            metricas.get("estres_promedio"),
            metricas.get("pasos"),
            metricas.get("spo2_nocturno"),
            metricas.get("calorias_activas"),
            indice_resultado.get("indice"),
            indice_resultado.get("semaforo"),
            peso_kg or metricas.get("peso_kg"),
            metricas.get("fuente", "garmin"),
        ))
        con.commit()
        return {"ok": True, "fecha": metricas.get("fecha")}
    finally:
        con.close()


# ── CACHÉ DE ÚLTIMA LECTURA VÁLIDA ────────────────────────────────────────────
def _ultima_lectura_valida(max_dias: int = GARMIN_CACHE_MAX_DIAS) -> Optional[dict]:
    """
    Devuelve la última métrica de Garmin guardada en BD con índice válido,
    si no es más antigua que max_dias. Sirve de fallback cuando Garmin
    responde 429 o está caído, para no perder el flujo matutino.
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("""
        SELECT * FROM metricas_diarias
        WHERE indice_disposicion IS NOT NULL
        ORDER BY fecha DESC LIMIT 1
    """).fetchone()
    con.close()
    if not row:
        return None

    try:
        f = datetime.fromisoformat(row["fecha"]).date()
    except Exception:
        return None
    if (date.today() - f).days > max_dias:
        return None
    return dict(row)


# ── FLUJO PRINCIPAL MAÑANA ────────────────────────────────────────────────────
def ejecutar_matutino(peso_kg: float = None) -> dict:
    """
    Punto de entrada principal — ejecutar cada mañana.
    1. Intenta descargar de Garmin (con reintentos/backoff)
    2. Si falla → usa la última lectura válida cacheada (≤ N días)
    3. Si tampoco hay caché → solicita datos manuales
    4. Calcula índice, guarda en BD y devuelve resultado para el Decisor
    """
    init_db()
    hoy = date.today()

    # Intentar Garmin
    metricas = descargar_garmin(hoy)

    # Conexión caída del todo → intentar caché reciente antes de molestar
    if "error" in metricas:
        cache = _ultima_lectura_valida()
        if cache:
            indice = calcular_indice(cache)
            return {
                "estado":       "ok",
                "fecha":        hoy.isoformat(),
                "fuente":       "cache",
                "fecha_cache":  cache.get("fecha"),
                "aviso":        f"⚠️ Garmin no disponible — usando lectura del {cache.get('fecha')}",
                "error_garmin": metricas["error"],
                "metricas":     cache,
                "indice":       indice,
            }
        # Sin caché → pediremos todas las métricas
        error_garmin = metricas.get("error")
        metricas = {"fecha": hoy.isoformat(), "fuente": "manual"}
    else:
        error_garmin = None

    # ¿Qué métricas clave faltan? → pedir SOLO esas, conservando las de Garmin
    faltan = _campos_faltantes(metricas, hoy)
    if faltan:
        return {
            "estado":          "necesita_datos_parciales",
            "fecha":           hoy.isoformat(),
            "metricas_garmin": metricas,
            "faltan":          faltan,
            "error_garmin":    error_garmin,
            "preguntas":       _preguntas_faltantes(faltan),
        }

    # Todo presente → calcular, guardar y devolver
    indice = calcular_indice(metricas)
    guardar_metricas(metricas, indice, peso_kg)
    return {
        "estado":   "ok",
        "fecha":    hoy.isoformat(),
        "fuente":   metricas.get("fuente", "garmin"),
        "metricas": metricas,
        "indice":   indice,
    }


def completar_metricas(metricas_garmin: dict, valores: dict, peso_kg: float = None) -> dict:
    """
    Fusiona lo que trajo Garmin con las métricas que el usuario ha aportado
    (las que faltaban), calcula el índice y lo guarda.
    """
    init_db()
    hoy = date.today()
    m = dict(metricas_garmin or {})
    m.setdefault("fecha", hoy.isoformat())
    m.update(valores)
    m["fuente"] = "garmin+manual" if metricas_garmin.get("fuente") == "garmin" else "manual"

    indice = calcular_indice(m)
    guardar_metricas(m, indice, peso_kg or m.get("peso_kg"))
    return {
        "estado":   "ok",
        "fecha":    hoy.isoformat(),
        "fuente":   m["fuente"],
        "metricas": m,
        "indice":   indice,
    }


def ejecutar_con_datos_manuales(body_battery: int, horas_sueno: float,
                                 sensacion_sueno: int, hrv_status: str = "normal",
                                 fc_reposo: int = None, estres_ayer: int = None,
                                 peso_kg: float = None) -> dict:
    """Versión manual para cuando el usuario responde por Telegram."""
    init_db()
    hoy = date.today()

    metricas = entrada_manual(
        body_battery, horas_sueno, sensacion_sueno,
        hrv_status, fc_reposo, estres_ayer, peso_kg, hoy
    )
    indice = calcular_indice(metricas)
    guardar_metricas(metricas, indice, peso_kg)

    return {
        "estado":   "ok",
        "fecha":    hoy.isoformat(),
        "fuente":   "manual",
        "metricas": metricas,
        "indice":   indice,
    }


def _preguntas_manuales(hoy: date) -> str:
    es_lunes = hoy.weekday() == 0
    texto = (
        f"👋 Buenos días JP\n"
        f"No he podido conectar con Garmin — dime:\n\n"
        f"1️⃣ Body Battery al despertar (0-100)\n"
        f"2️⃣ Horas de sueño\n"
        f"3️⃣ Sensación de sueño (1=muy mal · 5=muy bien)\n"
        f"4️⃣ VFC (equilibrado/normal/bajo/malo) — opcional\n"
        f"5️⃣ FC reposo — opcional\n"
    )
    if es_lunes:
        texto += f"⚖️ Peso de hoy (kg) — registro semanal\n"
    texto += "\nEj: *72 / 7 / 4 / normal / 62*"
    return texto


# ── HISTORIAL Y TENDENCIAS ────────────────────────────────────────────────────
def get_tendencia(ultimos_dias: int = 7) -> dict:
    """
    Devuelve tendencia de las últimas N métricas.
    Útil para el Agente Decisor y para informes semanales.
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT * FROM metricas_diarias
        ORDER BY fecha DESC LIMIT ?
    """, (ultimos_dias,)).fetchall()
    con.close()

    if not rows:
        return {"error": "Sin datos históricos aún."}

    indices = [r["indice_disposicion"] for r in rows if r["indice_disposicion"]]
    bbs     = [r["body_battery"]       for r in rows if r["body_battery"]]
    fcs     = [r["fc_reposo"]          for r in rows if r["fc_reposo"]]
    pesos   = [r["peso_kg"]            for r in rows if r["peso_kg"]]

    return {
        "dias":             len(rows),
        "indice_medio":     round(sum(indices)/len(indices), 1) if indices else None,
        "body_battery_medio": round(sum(bbs)/len(bbs), 1) if bbs else None,
        "fc_reposo_media":  round(sum(fcs)/len(fcs), 1) if fcs else None,
        "peso_actual":      pesos[0] if pesos else None,
        "peso_inicial":     pesos[-1] if len(pesos) > 1 else None,
        "diferencia_peso":  round(pesos[0]-pesos[-1], 1) if len(pesos) > 1 else None,
        "detalle":          [dict(r) for r in rows],
    }


# ── CLI / TEST ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    init_db()

    cmd = sys.argv[1] if len(sys.argv) > 1 else "manual"

    if cmd == "garmin":
        resultado = ejecutar_matutino()
        print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))

    elif cmd == "manual":
        # python agente_metrica.py manual <bb> <horas> <sensacion> [hrv] [fc] [peso]
        bb       = int(sys.argv[2])   if len(sys.argv) > 2 else 65
        horas    = float(sys.argv[3]) if len(sys.argv) > 3 else 6.5
        sensacion= int(sys.argv[4])   if len(sys.argv) > 4 else 3
        hrv      = sys.argv[5]        if len(sys.argv) > 5 else "normal"
        fc       = int(sys.argv[6])   if len(sys.argv) > 6 else None
        peso     = float(sys.argv[7]) if len(sys.argv) > 7 else None

        resultado = ejecutar_con_datos_manuales(bb, horas, sensacion, hrv, fc, None, peso)
        print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))

    elif cmd == "tendencia":
        dias = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        print(json.dumps(get_tendencia(dias), ensure_ascii=False, indent=2, default=str))

    else:
        print("Comandos: garmin | manual <bb> <horas> <sensacion> [hrv] [fc] [peso] | tendencia [dias]")
