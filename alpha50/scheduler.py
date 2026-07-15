"""
Alpha50 · Scheduler + Intent Handler
Ubicación: C:\\Users\\Usuario\\jarvis\\alpha50\\scheduler.py

Responsabilidades:
- Ejecutar el flujo matutino cada día a las 07:00
- Solicitar métricas manuales si Garmin no responde
- Escuchar respuestas del usuario y enrutarlas
- Integrarse con el relay de Fígaro (mismo canal Telegram que Jarvis)

Integración con Jarvis:
- Añadir intent 'alpha50' en core/intent.py
- Llamar a alpha50_intent_handler() desde api/main.py
- El scheduler corre como proceso independiente vía NSSM en el PC local

Arranque manual (PowerShell):
    cd C:\\Users\\Usuario\\jarvis\\alpha50
    ..\\.venv\\Scripts\\python.exe scheduler.py

Arranque automático (NSSM):
    nssm install Alpha50Scheduler ..\\.venv\\Scripts\\python.exe
    nssm set Alpha50Scheduler AppDirectory C:\\Users\\Usuario\\jarvis\\alpha50
    nssm set Alpha50Scheduler AppParameters scheduler.py
    nssm start Alpha50Scheduler
"""

import os
import sys
import json
import time
import sqlite3
import requests
import schedule
import threading
from datetime import date, datetime
from typing import Optional

# Windows/NSSM corre con cp1252: forzar UTF-8 en la salida para que los prints
# con emojis/acentos/flechas (→) no revienten el servicio con UnicodeEncodeError.
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── RUTAS ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Añadir el directorio raíz de Jarvis al path
JARVIS_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, JARVIS_DIR)

# ── CONFIGURACIÓN ─────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(JARVIS_DIR, ".env"))

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
RELAY_URL        = os.environ.get("RELAY_URL", "http://100.78.43.76:10004")
RELAY_API_KEY    = os.environ.get("RELAY_API_KEY", "")
HORA_MATUTINO    = os.environ.get("ALPHA50_HORA", "07:00")

DB_PATH = os.path.join(BASE_DIR, "alpha50_cronologia.db")


def _connect_db() -> sqlite3.Connection:
    """Conexion apta para el scheduler y la API a la vez."""
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.execute("PRAGMA busy_timeout = 15000")
    con.execute("PRAGMA journal_mode = WAL")
    return con


# ── ESTADO DE SESIÓN (persistido en BD, compartido entre procesos) ────────────
# JarvisAPI (Telegram), Jarvis Chat y el Scheduler son procesos distintos; el
# estado del diálogo (qué espera el bot) debe estar en la BD para que una
# pregunta lanzada en un proceso pueda responderse desde otro.
def _sesion_init():
    con = _connect_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS alpha50_sesion (
            id            INTEGER PRIMARY KEY CHECK (id = 1),
            esperando     TEXT,
            opcion_elegida TEXT,
            contexto      TEXT,
            actualizado   TEXT
        )
    """)
    con.commit()
    con.close()


def _sesion_get() -> dict:
    _sesion_init()
    con = _connect_db()
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM alpha50_sesion WHERE id=1").fetchone()
    con.close()
    if not row:
        return {"esperando": None, "opcion_elegida": None, "contexto": {}}
    try:
        ctx = json.loads(row["contexto"]) if row["contexto"] else {}
    except Exception:
        ctx = {}
    return {"esperando": row["esperando"], "opcion_elegida": row["opcion_elegida"], "contexto": ctx}


def _sesion_write(s: dict):
    _sesion_init()
    con = _connect_db()
    con.execute(
        "INSERT OR REPLACE INTO alpha50_sesion (id, esperando, opcion_elegida, contexto, actualizado) "
        "VALUES (1, ?, ?, ?, datetime('now','localtime'))",
        (s.get("esperando"), s.get("opcion_elegida"),
         json.dumps(s.get("contexto") or {}, ensure_ascii=False, default=str))
    )
    con.commit()
    con.close()


def _sesion_update(**cambios):
    """Actualiza solo los campos indicados, conservando el resto."""
    s = _sesion_get()
    s.update(cambios)
    _sesion_write(s)


def _sesion_clear():
    _sesion_write({"esperando": None, "opcion_elegida": None, "contexto": {}})


# ── TELEGRAM (vía relay de Fígaro) ────────────────────────────────────────────
def enviar_telegram(mensaje: str, parse_mode: str = "Markdown") -> bool:
    """
    Envía mensaje al chat de JP a través del relay de Fígaro (/notify).
    Esta es la vía correcta en la arquitectura de Jarvis: no se conecta
    directamente a la API de Telegram, sino que delega en el relay que
    ya tiene el bot y el chat_id autorizado.
    """
    url = f"{RELAY_URL}/notify"
    headers = {"X-Relay-Key": RELAY_API_KEY} if RELAY_API_KEY else {}
    try:
        r = requests.post(url, json={"message": mensaje}, headers=headers, timeout=10)
        if r.status_code == 200:
            return True
        print(f"[Alpha50] Relay respondió {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        print(f"[Alpha50] Error enviando al relay: {e}")
        # Imprimir el mensaje en consola como fallback para no perderlo
        print(f"[Alpha50] Mensaje no enviado:\n{mensaje}")
        return False


# ── MARCADOR DE EJECUCIÓN DIARIA (para catch-up) ──────────────────────────────
def _init_run_marker():
    con = _connect_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS matutino_runs (
            fecha       TEXT PRIMARY KEY,
            lanzado_en  TEXT
        )
    """)
    con.commit()
    con.close()


def _matutino_ya_lanzado_hoy() -> bool:
    """True si el flujo matutino ya se disparó hoy (evita duplicados)."""
    _init_run_marker()
    con = _connect_db()
    row = con.execute(
        "SELECT 1 FROM matutino_runs WHERE fecha=?",
        (date.today().isoformat(),)
    ).fetchone()
    con.close()
    return row is not None


def _marcar_matutino_lanzado():
    """Registra que el flujo matutino se ha disparado hoy."""
    _init_run_marker()
    con = _connect_db()
    con.execute(
        "INSERT OR REPLACE INTO matutino_runs (fecha, lanzado_en) VALUES (?,?)",
        (date.today().isoformat(), datetime.now().isoformat(timespec="seconds"))
    )
    con.commit()
    con.close()


def _hora_ya_pasada(hora_str: str) -> bool:
    """True si la hora HH:MM de hoy ya pasó respecto a ahora."""
    try:
        h, m = map(int, hora_str.split(":"))
    except Exception:
        return False
    ahora    = datetime.now()
    objetivo = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    return ahora >= objetivo


# ── FLUJO MATUTINO ────────────────────────────────────────────────────────────
def ejecutar_matutino():
    """
    Flujo completo cada mañana:
    1. Intenta obtener métricas de Garmin
    2. Si falla → pide datos manuales
    3. Si tiene métricas → calcula y envía entreno del día
    """
    from agente_cronologia import get_estado_hoy, init_db as init_cron
    from agente_metrica    import ejecutar_matutino as garmin_matutino, init_db as init_met

    print(f"[Alpha50] Flujo matutino — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    init_cron()
    init_met()

    # ¿Es lunes? → pedir peso también
    es_lunes = date.today().weekday() == 0

    # Intentar Garmin
    resultado_garmin = garmin_matutino()

    enviado = False
    if resultado_garmin.get("estado") == "necesita_datos_parciales":
        # Garmin trajo algo pero faltan métricas → pedir SOLO las que faltan
        _sesion_update(esperando="metricas_faltantes", contexto={
            "metricas_garmin": resultado_garmin["metricas_garmin"],
            "faltan":          resultado_garmin["faltan"],
            "es_lunes":        es_lunes,
        })

        enviado = enviar_telegram(resultado_garmin["preguntas"])
        if enviado:
            print(f"[Alpha50] Esperando métricas faltantes: {resultado_garmin['faltan']}")

    elif resultado_garmin.get("estado") == "necesita_datos_manuales":
        # (compatibilidad) Garmin no disponible → solicitar todas
        _sesion_update(esperando="metricas", contexto={"es_lunes": es_lunes})

        enviado = enviar_telegram(resultado_garmin["preguntas"])
        if enviado:
            print("[Alpha50] Esperando métricas manuales del usuario")

    elif resultado_garmin.get("estado") == "ok":
        # Garmin OK → ir directo al decisor
        enviado = _ejecutar_decisor(resultado_garmin)

    else:
        enviado = enviar_telegram("⚠️ Alpha50: error al iniciar el flujo matutino. Revisa los logs.")

    # Marcar el disparo de hoy SOLO si se pudo enviar. Si el relay/Tailscale
    # aún no estaba listo (típico al encender el PC), no se marca y el catch-up
    # lo reintentará en el bucle hasta lograrlo.
    if enviado:
        _marcar_matutino_lanzado()
    else:
        print("[Alpha50] Envío fallido (¿relay/Tailscale no listo?). Se reintentará.")
    return enviado


def _ejecutar_decisor(metricas_resultado: dict) -> bool:
    """Llama al decisor y envía el mensaje resultante. Devuelve True si se envió."""
    from agente_decisor import decidir

    resultado = decidir(metricas_hoy=metricas_resultado)
    msg = resultado.get("mensaje_telegram", "")

    # Si las métricas vienen de la caché (Garmin caído), avisar al usuario
    if msg and metricas_resultado.get("aviso"):
        msg = f"{metricas_resultado['aviso']}\n\n{msg}"

    enviado = enviar_telegram(msg) if msg else False

    # Actualizar estado sesión según tipo de día
    tipo = resultado.get("tipo", "")
    if tipo == "cardio" and resultado.get("semaforo") not in ("rojo",):
        _sesion_update(esperando="opcion_cardio", opcion_elegida=None, contexto=resultado)
    elif tipo in ("musculacion", "hiit", "anaerobico", "sesion"):
        _sesion_update(esperando="confirmacion", opcion_elegida=None, contexto=resultado)
    elif tipo in ("descanso", "descanso_forzado"):
        _sesion_update(esperando="confirmacion_descanso", opcion_elegida=None, contexto=resultado)
    else:
        _sesion_clear()

    print(f"[Alpha50] Mensaje enviado. Esperando: {_sesion_get()['esperando']}")
    return enviado


# ── INTENT HANDLER (llamado desde Jarvis) ─────────────────────────────────────
def alpha50_intent_handler(texto_usuario: str) -> Optional[str]:
    """
    Punto de entrada desde Jarvis (core/intent.py).
    Devuelve respuesta para enviar al usuario, o None si no es un mensaje Alpha50.

    Integración en core/intent.py:
        from alpha50.scheduler import alpha50_intent_handler
        # En classify() añadir antes del return:
        resp_alpha50 = alpha50_intent_handler(texto)
        if resp_alpha50:
            return {"intent": "alpha50", "respuesta": resp_alpha50}
    """
    from agente_decisor  import procesar_respuesta
    from agente_metrica  import ejecutar_con_datos_manuales, completar_metricas

    texto_lower = texto_usuario.strip().lower()

    s = _sesion_get()
    esperando = s["esperando"]
    contexto  = s["contexto"]

    # ── Comandos y lenguaje natural de Alpha50 SIEMPRE primero ────────────────
    # Funciona aunque haya un estado pendiente y sirve para desbloquear la sesión.
    cmd = _detectar_comando_alpha50(texto_lower)
    if cmd is not None:
        return _manejar_comando_alpha50(cmd)

    _parece_datos = any(ch.isdigit() for ch in texto_usuario)

    # ── Esperando SOLO las métricas que Garmin no pudo traer ──────────────────
    if esperando == "metricas_faltantes" and _parece_datos:
        faltan = contexto.get("faltan", [])
        parsed = _parsear_faltantes(texto_usuario, faltan)
        if parsed.get("error"):
            return parsed["error"]

        resultado = completar_metricas(contexto.get("metricas_garmin", {}), parsed["valores"])

        _sesion_update(esperando=None)
        _ejecutar_decisor_async(resultado)
        return "✅ Métricas completadas, calculando tu entreno..."

    # ── Esperando métricas manuales (todas) ──────────────────────────────────
    if esperando == "metricas" and _parece_datos:
        resultado = _parsear_metricas_manuales(texto_usuario, contexto)
        if resultado.get("error"):
            return resultado["error"]

        # Guardar métricas y continuar
        metricas = ejecutar_con_datos_manuales(**resultado["kwargs"])

        _sesion_update(esperando=None)

        # Ir al decisor con las métricas recién introducidas
        _ejecutar_decisor_async(metricas)
        return "✅ Métricas registradas, calculando tu entreno..."

    # ── Esperando opción cardio (A/B/C) ──────────────────────────────────────
    if esperando == "opcion_cardio" and texto_lower in ("a", "b", "c"):
        res = procesar_respuesta(texto_usuario, contexto)
        # La opción real la resuelve el decisor (carrera/bici/hiit o power_walking)
        mapa = {"a": "carrera", "b": "bici", "c": "hiit"}

        _sesion_update(esperando="confirmacion",
                       opcion_elegida=res.get("opcion") or mapa.get(texto_lower))

        return res.get("mensaje_telegram")

    # ── Esperando confirmación (hecho/parcial/no pude) ────────────────────────
    if esperando in ("confirmacion", "confirmacion_descanso"):
        opcion = s.get("opcion_elegida")
        ctx = {"opcion": opcion} if opcion else {}
        res = procesar_respuesta(texto_usuario, ctx)

        # Si no era una respuesta de confirmación, dejar que el flujo normal
        # lo maneje (permite hablar de otras cosas con el estado pendiente).
        if res.get("accion") == "no_reconocido":
            return None

        if res.get("accion") == "registrado":
            _sesion_clear()

        return res.get("mensaje_telegram")

    # No es un mensaje Alpha50 (los comandos se resuelven al principio)
    return None


def _ejecutar_decisor_async(metricas):
    """Ejecuta el decisor en un thread para no bloquear el intent handler."""
    t = threading.Thread(target=_ejecutar_decisor, args=(metricas,), daemon=True)
    t.start()


def _parsear_faltantes(texto: str, faltan: list) -> dict:
    """
    Parsea la respuesta con SOLO las métricas que faltaban, en el orden pedido.
    faltan es una lista tipo ['body_battery','hrv','fc_reposo'].
    """
    # Separador exclusivo "/" para no romper decimales con coma (7,5 · 98,5)
    partes = [p.strip() for p in texto.split("/") if p.strip()]
    if len(partes) < len(faltan):
        orden = " / ".join(faltan)
        return {"error": f"Necesito {len(faltan)} valores en este orden: {orden}. "
                         f"Sepáralos con / e inténtalo de nuevo."}
    valores = {}
    try:
        for i, campo in enumerate(faltan):
            v = partes[i]
            if campo == "body_battery":
                bb = int(v)
                if not (0 <= bb <= 100):
                    return {"error": "Body Battery debe ir de 0 a 100. Inténtalo de nuevo."}
                valores["body_battery"] = bb
            elif campo == "sueno":
                # Puntuación de sueño (0-100). Si mete horas (ej "7"/"7.5"), lo
                # tratamos como horas por compatibilidad.
                if "h" in v.lower() or "." in v or "," in v:
                    valores["horas_sueno"] = float(v.lower().replace("h", "").replace(",", "."))
                else:
                    sc = int(v)
                    if not (0 <= sc <= 100):
                        return {"error": "Puntuación de sueño debe ir de 0 a 100. Inténtalo de nuevo."}
                    valores["sueno_score"] = sc
            elif campo == "hrv":
                valores["hrv_status"] = v.lower()
            elif campo == "fc_reposo":
                valores["fc_reposo"] = int("".join(ch for ch in v if ch.isdigit()))
            elif campo == "peso":
                valores["peso_kg"] = float(v.lower().replace("kg", "").replace(",", "."))
        return {"valores": valores}
    except (ValueError, IndexError):
        return {"error": "No entendí los valores. Revisa el formato y vuelve a enviarlos."}


def _parsear_metricas_manuales(texto: str, contexto: dict) -> dict:
    """
    Parsea respuesta tipo: '72 / 7 / 4 / normal / 62 / 99'
    Campos: body_battery / horas / sensacion / hrv / fc_reposo / peso(opcional)
    """
    # Separador exclusivo "/" para no romper decimales con coma (7,5 · 98,5) --
    # mismo criterio que _parsear_faltantes(). Antes hacia .replace(",", "/")
    # antes de partir, lo que convertia "8,5" en dos campos ("8" y "5") y
    # descuadraba todo lo que venia despues.
    partes = [p.strip() for p in texto.split("/") if p.strip()]
    try:
        bb       = int(partes[0])
        horas    = float(partes[1].replace(",", "."))
        sensacion= int(partes[2])
        hrv      = partes[3].lower() if len(partes) > 3 else "normal"
        fc       = int(partes[4]) if len(partes) > 4 and partes[4].isdigit() else None
        peso     = float(partes[5].replace(",", ".")) if len(partes) > 5 else None

        # Validaciones básicas
        if not (0 <= bb <= 100):
            return {"error": "Body Battery debe estar entre 0 y 100. Inténtalo de nuevo."}
        if not (0 <= horas <= 24):
            return {"error": "Horas de sueño no válidas. Inténtalo de nuevo."}
        if not (1 <= sensacion <= 5):
            return {"error": "Sensación debe ser del 1 al 5. Inténtalo de nuevo."}

        return {
            "kwargs": {
                "body_battery":    bb,
                "horas_sueno":     horas,
                "sensacion_sueno": sensacion,
                "hrv_status":      hrv,
                "fc_reposo":       fc,
                "peso_kg":         peso,
            }
        }
    except (ValueError, IndexError):
        return {
            "error": (
                "No entendí los datos. Formato: *BB / horas / sensación / hrv / fc*\n"
                "Ejemplo: *72 / 7 / 4 / normal / 62*\n"
                "_(hrv y fc son opcionales)_"
            )
        }


def _detectar_comando_alpha50(texto: str):
    """
    Decide si un mensaje es para Alpha50 y lo normaliza a un subcomando.
    Devuelve el texto de comando (p. ej. 'alpha50 ahora') o None si no aplica.
    Reconoce tanto el prefijo 'alpha50 …' como lenguaje natural del entreno.
    """
    t = texto.strip().lower()
    # Explícito
    if t.startswith("/alpha50"):
        return t[1:].strip()
    if t.startswith("alpha50") or "alpha50" in t:
        return t

    def has(*kw):
        return any(k in t for k in kw)

    # Lenguaje natural → subcomando
    if has("qué entreno", "que entreno", "qué entrenamiento", "que entrenamiento",
           "toca hoy", "toca entrenar", "mi rutina", "rutina de hoy", "entreno de hoy",
           "qué me toca", "que me toca", "qué hago hoy", "que hago hoy",
           "qué tengo que entrenar", "que tengo que entrenar"):
        return "alpha50 ahora"
    if has("mi progreso", "cómo voy con el entreno", "como voy con el entreno",
           "evolución del peso", "tendencia del entreno"):
        return "alpha50 tendencia"
    if has("resumen de la semana", "cómo va la semana", "como va la semana",
           "mi semana de entreno"):
        return "alpha50 semana"
    if has("en qué nivel", "en que nivel", "qué nivel estoy", "que nivel estoy",
           "en qué semana estoy", "en que semana estoy"):
        return "alpha50 estado"
    return None


def _manejar_comando_alpha50(texto: str) -> str:
    """Comandos manuales: /alpha50 estado, resumen, semana, nivel, etc."""
    from agente_cronologia import (get_estado_hoy, get_resumen_semana,
                                    cambiar_nivel, NIVELES_ORDEN)
    from agente_metrica    import get_tendencia

    # Debug: volcado crudo de campos de Garmin
    if "debug" in texto:
        from agente_metrica import debug_garmin
        return debug_garmin()

    # Registrar el entreno de hoy en cualquier momento:
    #   "alpha50 hecho"  ·  "alpha50 parcial [detalle]"  ·  "alpha50 no pude"
    if any(w in texto for w in ("hecho", "completado", "parcial", "no pude", "saltado")):
        from agente_decisor import procesar_respuesta
        resp = texto.replace("/alpha50", "").replace("alpha50", "").strip()
        res = procesar_respuesta(resp)
        _sesion_clear()   # cerrar cualquier estado pendiente tras registrar
        return res.get("mensaje_telegram", "✅ Registrado.")

    # Cambiar nivel/semana: "alpha50 nivel Principiante [semana]"
    if "nivel" in texto:
        # Normalizar "pre principiante" / "pre-principiante" → "preprincipiante"
        texto = texto.replace("pre principiante", "preprincipiante").replace("pre-principiante", "preprincipiante")
        nivmap = {n.lower(): n for n in NIVELES_ORDEN}
        niv, sem = None, 1
        for p in texto.split():
            if p in nivmap:
                niv = nivmap[p]
            elif p.isdigit():
                sem = int(p)
        if not niv:
            return ("¿A qué nivel? Usa uno de: " + ", ".join(NIVELES_ORDEN) +
                    "\nEj: *alpha50 nivel Principiante 1*")
        res = cambiar_nivel(niv, sem)
        if res.get("error"):
            return res["error"]
        return (f"✅ Nivel cambiado a *{niv}* · Semana {sem}.\n"
                f"Escribe *alpha50 ahora* para ver el entreno de hoy.")

    if "estado" in texto:
        estado = get_estado_hoy()
        return (
            f"📅 *Alpha50 — Hoy*\n"
            f"Nivel: {estado.get('nivel', '?')}\n"
            f"Semana: {estado.get('semana_plan', '?')}\n"
            f"Día: {estado.get('nombre_dia', '?')}\n"
            f"Tipo: {estado.get('tipo', '?')}\n"
            f"Registrado: {'✅' if estado.get('ya_registrado') else '⏳'}"
        )

    if "semana" in texto or "resumen" in texto:
        resumen = get_resumen_semana()
        saltados = resumen.get("saltados", 0)
        return (
            f"📊 *Alpha50 — Semana {resumen.get('semana_plan', '?')}*\n"
            f"✅ Completados: {resumen.get('completados', 0)}\n"
            f"⚡ Parciales: {resumen.get('parciales', 0)}\n"
            f"❌ Saltados: {saltados}\n"
            f"{'⚠️ Se repetirá la semana' if resumen.get('se_repetira_semana') else '👍 Vas bien'}"
        )

    if "tendencia" in texto or "progreso" in texto:
        tend = get_tendencia(7)
        peso_actual  = tend.get("peso_actual")
        peso_inicial = tend.get("peso_inicial")
        dif_peso     = tend.get("diferencia_peso")
        msg = (
            f"📈 *Alpha50 — Tendencia 7 días*\n"
            f"Disposición media: {tend.get('indice_medio', '?')}/100\n"
            f"Body Battery medio: {tend.get('body_battery_medio', '?')}\n"
            f"FC reposo media: {tend.get('fc_reposo_media', '?')} ppm\n"
        )
        if peso_actual:
            msg += f"⚖️ Peso actual: {peso_actual} kg\n"
        if dif_peso is not None:
            emoji = "📉" if dif_peso < 0 else "📈"
            msg += f"{emoji} Variación: {dif_peso:+.1f} kg"
        return msg

    if "ahora" in texto or "forzar" in texto:
        # Forzar flujo matutino manualmente
        t = threading.Thread(target=ejecutar_matutino, daemon=True)
        t.start()
        return "🔄 Iniciando flujo Alpha50..."

    return (
        "🏃 *Alpha50 — Comandos disponibles:*\n"
        "alpha50 ahora — ver el entreno de hoy\n"
        "alpha50 hecho — registrar el entreno como completado\n"
        "alpha50 parcial [detalle] — registrar parcial\n"
        "alpha50 no pude — registrar como saltado\n"
        "alpha50 estado — qué toca hoy (nivel/semana/día)\n"
        "alpha50 semana — resumen de la semana\n"
        "alpha50 tendencia — progreso 7 días\n"
        "alpha50 nivel <Nivel> [semana] — cambiar de nivel\n"
    )


# ── SCHEDULER ─────────────────────────────────────────────────────────────────
def arrancar_scheduler():
    """Programa el flujo matutino y arranca el loop."""
    schedule.every().day.at(HORA_MATUTINO).do(ejecutar_matutino)
    print(f"[Alpha50] Scheduler arrancado — flujo matutino a las {HORA_MATUTINO}")
    print(f"[Alpha50] Próxima ejecución: {schedule.next_run()}")

    # Catch-up con reintento: si el PC arrancó después de la hora y hoy no se
    # lanzó el flujo, se dispara. Si el envío falla (relay/Tailscale aún no
    # listo al encender), NO se marca como hecho, así que el bucle lo reintenta
    # cada 30 s hasta que la red esté disponible y el mensaje salga.
    while True:
        schedule.run_pending()

        if _hora_ya_pasada(HORA_MATUTINO) and not _matutino_ya_lanzado_hoy():
            print("[Alpha50] Catch-up: la hora ya paso y no hay flujo hoy -> intentando")
            try:
                ejecutar_matutino()
            except Exception as e:
                print(f"[Alpha50] Error en catch-up: {e}")

        time.sleep(30)


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Alpha50 Scheduler")
    parser.add_argument("--ahora",    action="store_true", help="Ejecutar flujo matutino ahora")
    parser.add_argument("--test",     action="store_true", help="Test sin enviar Telegram")
    parser.add_argument("--comando",  type=str,            help="Simular comando de usuario")
    args = parser.parse_args()

    if args.ahora:
        print("[Alpha50] Ejecutando flujo matutino manualmente...")
        ejecutar_matutino()

    elif args.test:
        print("[Alpha50] Modo test — simulando flujo con métricas de ejemplo")
        from agente_metrica import ejecutar_con_datos_manuales
        from agente_decisor  import decidir

        metricas = ejecutar_con_datos_manuales(
            body_battery=72, horas_sueno=7.0, sensacion_sueno=4,
            hrv_status="normal", fc_reposo=70, peso_kg=99.0
        )
        resultado = decidir(metricas_hoy=metricas)
        print("\n" + "="*50)
        print(resultado.get("mensaje_telegram", json.dumps(resultado, indent=2,
                             ensure_ascii=False, default=str)))

    elif args.comando:
        print(f"[Alpha50] Simulando comando: '{args.comando}'")
        respuesta = alpha50_intent_handler(args.comando)
        print(respuesta or "(no reconocido como comando Alpha50)")

    else:
        # Modo normal — scheduler continuo
        arrancar_scheduler()
