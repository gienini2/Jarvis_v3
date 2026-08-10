"""
Alpha50 · Agente Decisor
Ubicación: C:\\Users\\Usuario\\jarvis\\alpha50\\agente_decisor.py

Responsabilidades:
- Recibir output de los 3 agentes anteriores
- Aplicar reglas de ajuste según semáforo
- Generar mensaje Telegram completo y accionable
- Gestionar respuestas del usuario (A/B/C, hecho, parcial, no pude)
- Punto de entrada único del sistema Alpha50
"""

import json
import os
import sqlite3
from datetime import date, timedelta
from typing import Optional

BASE_DIR = os.path.dirname(__file__)
DB_PATH  = os.path.join(BASE_DIR, "alpha50_cronologia.db")

# Ajustes por semáforo — específicos por tipo de entreno
AJUSTES = {
    "verde": {
        "descripcion":         "Entreno completo según plan",
        # Musculación
        "series_quitar":       0,      # series a quitar por superserie (de 4 → 4)
        "superseries_quitar":  0,      # superseries a eliminar por el final
        # HIIT
        "ciclos_quitar":       0,      # ciclos a quitar (de 4 → 4)
        "ratio_extra_desc":    0,      # segundos extra de descanso en trabajo/desc
        # Cardio continuo
        "factor_tiempo":       1.0,
        # Series carrera/bici
        "series_cardio_quitar": 0,     # series a quitar por bloque
        "bloques_quitar":       0,     # bloques de series a eliminar (series_2)
    },
    "amarillo": {
        "descripcion":         "Reduce intensidad — día con menos energía",
        # Musculación: 4 series → 3 series por ejercicio
        "series_quitar":       1,
        "superseries_quitar":  0,
        # HIIT: 4 ciclos → 3 ciclos, +10" descanso
        "ciclos_quitar":       1,
        "ratio_extra_desc":    10,
        # Cardio continuo: -20%
        "factor_tiempo":       0.8,
        # Series carrera/bici: -2 series por bloque
        "series_cardio_quitar": 2,
        "bloques_quitar":       0,
    },
    "naranja": {
        "descripcion":         "Movilidad y cardio muy suave",
        # Musculación: 2 series, solo las 2 primeras superseries
        "series_quitar":       2,
        "superseries_quitar":  2,      # eliminar las 2 últimas superseries
        # HIIT: 2 ciclos, +20" descanso
        "ciclos_quitar":       2,
        "ratio_extra_desc":    20,
        # Cardio: 20 min suave
        "factor_tiempo":       0.5,
        # Series carrera/bici: eliminar bloque 2 entero, -3 del bloque 1
        "series_cardio_quitar": 3,
        "bloques_quitar":       1,
    },
}


# ── DECISOR PRINCIPAL ─────────────────────────────────────────────────────────
def decidir(nivel: str = None, semana: int = None, dia_plan: int = None,
            metricas_hoy: dict = None, forzar_descanso: bool = False) -> dict:
    """
    Punto de entrada principal.
    Puede recibir datos ya calculados o los busca en BD si no se pasan.
    """
    from agente_cronologia import get_estado_hoy, init_db as init_cron
    from agente_plan       import get_entreno
    from agente_metrica    import init_db as init_met, get_tendencia

    init_cron()
    init_met()

    # 1. Cronología
    estado_dia = get_estado_hoy()
    if "error" in estado_dia:
        return {"error": estado_dia["error"]}

    nivel    = nivel    or estado_dia["nivel"]
    semana   = semana   or estado_dia["semana_plan"]
    dia_plan = dia_plan or estado_dia["dia_plan"]
    tipo_dia = estado_dia["tipo"]

    # 2. Métricas
    if metricas_hoy is None:
        metricas_hoy = _cargar_metricas_hoy()

    indice   = metricas_hoy.get("indice", {}) if metricas_hoy else {}
    semaforo = indice.get("semaforo", "amarillo") if indice else "amarillo"
    idx_val  = indice.get("indice", 50)          if indice else 50

    # 3. Forzar descanso si se indica explícitamente
    if forzar_descanso:
        semaforo = "rojo"
        idx_val  = 0

    # 4. Días de descanso del plan → ignorar semáforo
    if tipo_dia == "descanso":
        return _resultado_descanso_plan(estado_dia, metricas_hoy)

    # 5. Semáforo rojo → descanso aunque toque entrenar
    if semaforo == "rojo":
        return _resultado_descanso_forzado(estado_dia, idx_val, metricas_hoy)

    # 6. Plan del día
    entreno = get_entreno(nivel, semana, dia_plan)
    if "error" in entreno:
        return {"error": entreno["error"]}

    # 7. Aplicar ajustes
    ajuste = AJUSTES[semaforo]

    # 8. Generar mensaje
    if "bloques" in entreno:                       # Avanzado: sesión única (muscu/HIIT/anaeróbico)
        mensaje = _mensaje_sesion(estado_dia, entreno, indice, metricas_hoy)
    elif tipo_dia == "cardio":
        mensaje = _mensaje_cardio(estado_dia, entreno, indice, ajuste, metricas_hoy)
    else:
        mensaje = _mensaje_musculacion(estado_dia, entreno, indice, ajuste, metricas_hoy)

    return {
        "ok":           True,
        "fecha":        estado_dia["fecha"],
        "nivel":        nivel,
        "semana":       semana,
        "dia_plan":     dia_plan,
        "nombre_dia":   estado_dia["nombre_dia"],
        "tipo":         tipo_dia,
        "semaforo":     semaforo,
        "indice":       idx_val,
        "ajuste":       ajuste,
        "entreno":      entreno,
        "metricas":     metricas_hoy,
        "mensaje_telegram": mensaje,
    }


# ── NOTA DE INTENSIDAD POR SEMÁFORO (formato Principiante) ────────────────────
def _nota_intensidad(semaforo: str) -> str:
    return {
        "verde":    "🟢 Estás bien — hazlo completo según el plan.",
        "amarillo": "🟡 Día algo flojo — baja un poco el ritmo o acorta si lo necesitas.",
        "naranja":  "🟠 Poca energía — quédate en lo suave, sin forzar.",
        "rojo":     "🔴 Mejor descanso activo hoy.",
    }.get(semaforo, "")


def _bloque_estado(nombre, sem, indice, metricas, emoji_tipo, sufijo_nivel=""):
    """Cabecera + métricas resumidas, común a los renderizadores."""
    emoji_sem = {"verde": "🟢", "amarillo": "🟡", "naranja": "🟠", "rojo": "🔴"}
    e_sem = emoji_sem.get(indice.get("semaforo", "amarillo"), "🟡")
    idx   = indice.get("indice", 50)
    lineas = [f"{emoji_tipo} *{nombre} · Semana {sem} · Alpha50{sufijo_nivel}*", "", "📊 *Tu estado hoy:*"]
    m = metricas.get("metricas", {}) if metricas else {}
    lineas += _lineas_metricas(m)
    lineas += ["", f"{e_sem} *Disposición: {idx}/100*", _nota_intensidad(indice.get('semaforo', 'amarillo')), ""]
    return lineas


def _lineas_metricas(m: dict) -> list:
    """Líneas de métricas resumidas (común a todos los mensajes)."""
    L = []
    if m.get("body_battery") is not None: L.append(f"  ⚡ Body Battery: {m['body_battery']}/100")
    if m.get("sueno_score") is not None:  L.append(f"  😴 Sueño: {m['sueno_score']}/100")
    elif m.get("horas_sueno"):            L.append(f"  😴 Sueño: {m['horas_sueno']}h")
    if m.get("hrv_status"):
        vfc = {"balanced": "Equilibrado", "unbalanced": "Desequilibrado",
               "low": "Bajo", "poor": "Malo", "bueno": "Bueno", "normal": "Normal",
               "bajo": "Bajo", "malo": "Malo"}.get(str(m["hrv_status"]).lower(), m["hrv_status"])
        L.append(f"  💓 VFC: {vfc}")
    if m.get("fc_reposo"):                L.append(f"  ❤️ FC reposo: {m['fc_reposo']} ppm")
    if m.get("peso_kg"):                  L.append(f"  ⚖️ Peso: {m['peso_kg']} kg")
    return L


def _mensaje_cardio_principiante(estado_dia, entreno, indice, metricas) -> str:
    sem = estado_dia["semana_plan"]; nombre = estado_dia["nombre_dia"]
    suf = f" {estado_dia.get('nivel', '')}".rstrip()
    lineas = _bloque_estado(nombre, sem, indice, metricas, "🏃", suf)
    opciones = entreno.get("opciones", {})
    lineas.append("🏃 *Elige tu opción de cardio:*\n")
    etiquetas = {"carrera": ("A", "👟", "CARRERA"),
                 "bici":    ("B", "🚴", "BICI"),
                 "power_walking": ("C", "🚶", "POWER WALKING")}
    for op, (letra, emoji, nom) in etiquetas.items():
        if op not in opciones:
            continue
        lineas.append(f"{emoji} *{letra}) {nom}*")
        for paso in opciones[op].get("pasos", []):
            lineas.append(f"  • {paso['campo']}: {paso['valor']}")
        lineas.append("")
    lineas.append("Responde *A*, *B* o *C* para confirmar tu opción.")
    return "\n".join(lineas)


def _mensaje_musculacion_principiante(estado_dia, entreno, indice, metricas) -> str:
    sem = estado_dia["semana_plan"]; nombre = estado_dia["nombre_dia"]
    suf = f" {estado_dia.get('nivel', '')}".rstrip()
    lineas = _bloque_estado(nombre, sem, indice, metricas, "💪", suf)
    muscu = entreno.get("musculacion", {})
    cal = muscu.get("calentamiento", "10'")
    lineas += ["💪 *MUSCULACIÓN — Peso corporal*", "",
               f"🔥 Calentamiento: {cal}", "",
               "📋 *Ejercicios:*"]
    for i, ej in enumerate(muscu.get("ejercicios", []), 1):
        lineas.append(f"  {i}. {ej}")
    if muscu.get("abdominales"):
        lineas.append(f"\n🔸 Abdominales: {muscu['abdominales']}")
    if muscu.get("descanso_series"):
        lineas.append(f"⏱ Descanso entre series: {muscu['descanso_series']}")
    if muscu.get("descanso_final"):
        lineas.append(f"⏱ Al cambiar de ejercicio: {muscu['descanso_final']}")
    if muscu.get("estiramientos"):
        lineas.append(f"🧘 Estiramientos: {muscu['estiramientos']}")
    lineas += ["", "Al terminar responde:", "  ✅ *hecho*",
               "  ⚡ *parcial [qué completaste]*", "  ❌ *no pude*"]
    return "\n".join(lineas)


def _mensaje_sesion(estado_dia, entreno, indice, metricas) -> str:
    """Sesión única prescrita (Avanzado): musculación / HIIT / anaeróbico."""
    sem = estado_dia["semana_plan"]; nombre = estado_dia["nombre_dia"]
    suf = f" {estado_dia.get('nivel', '')}".rstrip()
    emoji = {"musculacion": "💪", "hiit": "⚡", "anaerobico": "🧗"}.get(entreno.get("tipo"), "🏋️")
    lineas = _bloque_estado(nombre, sem, indice, metricas, emoji, suf)
    lineas.append(f"{emoji} *{entreno.get('titulo', 'Sesión').upper()}*")
    lineas.append("")
    for b in entreno.get("bloques", []):
        lineas.append(f"  • {b.get('campo')}: {b.get('valor')}")
    lineas += ["", "Al terminar responde:", "  ✅ *hecho*",
               "  ⚡ *parcial [qué completaste]*", "  ❌ *no pude*"]
    return "\n".join(lineas)


# ── MENSAJES ──────────────────────────────────────────────────────────────────
def _mensaje_cardio(estado_dia, entreno, indice, ajuste, metricas) -> str:
    # Formato Principiante: opciones con "pasos" → renderizador propio
    opciones_ = entreno.get("opciones", {})
    if any(isinstance(o, dict) and "pasos" in o for o in opciones_.values()):
        return _mensaje_cardio_principiante(estado_dia, entreno, indice, metricas)

    sem    = estado_dia["semana_plan"]
    nombre = estado_dia["nombre_dia"]
    suf    = f" {estado_dia.get('nivel', '')}".rstrip()
    emoji_sem = {"verde": "🟢", "amarillo": "🟡", "naranja": "🟠", "rojo": "🔴"}
    e_sem  = emoji_sem.get(indice.get("semaforo", "amarillo"), "🟡")
    idx    = indice.get("indice", 50)

    lineas = [
        f"🏃 *{nombre} · Semana {sem} · Alpha50{suf}*",
        f"",
        f"📊 *Tu estado hoy:*",
    ]

    # Métricas resumidas
    m = metricas.get("metricas", {}) if metricas else {}
    lineas += _lineas_metricas(m)

    lineas += [
        f"",
        f"{e_sem} *Disposición: {idx}/100 — {ajuste['descripcion']}*",
        f"",
    ]

    # Naranja → cardio suave, sin series
    if ajuste["factor_tiempo"] <= 0.5:
        lineas += [
            f"🔶 *Hoy toca cardio muy suave:*",
            f"  • 10' calentamiento articular",
            f"  • 20' caminata o bici tranquila",
            f"  • 10' estiramientos",
            f"",
            f"Sin series, sin sprints. El cuerpo necesita moverse sin sobrecargarse.",
            f"",
            f"Responde *hecho* o *no pude*.",
        ]
        return "\n".join(lineas)

    # Verde / Amarillo → mostrar opciones con ajuste inteligente
    opciones   = entreno.get("opciones", {})
    factor_t   = ajuste["factor_tiempo"]
    s_quitar   = ajuste["series_cardio_quitar"]
    b_quitar   = ajuste["bloques_quitar"]
    c_quitar   = ajuste["ciclos_quitar"]
    extra_desc = ajuste["ratio_extra_desc"]
    ajustado   = ajuste["descripcion"] if s_quitar or c_quitar else ""

    lineas.append("🏃 *Elige tu opción de cardio:*\n")

    letras = {"carrera": "A", "bici": "B", "hiit": "C"}
    emojis_op = {"carrera": "👟", "bici": "🚴", "hiit": "⚡"}

    for opcion, letra in letras.items():
        if opcion not in opciones:
            continue
        datos = opciones[opcion]
        e = emojis_op[opcion]
        lineas.append(f"{e} *{letra}) {opcion.upper()}*")

        if opcion == "hiit":
            ciclos     = datos.get("ciclos", 4)
            ciclos_adj = max(1, ciclos - c_quitar)
            tw         = datos.get("trabajo_descanso", "")

            lineas.append(f"  • Ciclos: {ciclos_adj}" +
                          (f" _(plan: {ciclos})_" if ciclos_adj != ciclos else ""))

            # Ajustar ratio trabajo/descanso sumando segundos de descanso
            if tw and extra_desc > 0:
                tw_adj = _ajustar_ratio_hiit(tw, extra_desc)
                lineas.append(f"  • Trabajo/Desc: {tw_adj} _(plan: {tw})_")
            elif tw:
                lineas.append(f"  • Trabajo/Desc: {tw}")

            ejs = datos.get("ejercicios", [])
            if ejs:
                lineas.append(f"  • {len(ejs)} ejercicios")

        else:
            # Carrera o bici
            cal = datos.get("calentamiento", "10'")
            lineas.append(f"  • Calentamiento: {cal}")

            continua = datos.get("continua", "")
            if continua:
                mins = _extraer_minutos(continua)
                if mins and factor_t < 1.0:
                    mins_adj = round(mins * factor_t)
                    lineas.append(f"  • Tramo continuo: {mins_adj}' _(plan: {mins}')_")
                else:
                    lineas.append(f"  • Tramo continuo: {continua}")

            # Series bloque 1
            s1 = datos.get("series_1", "")
            if s1:
                s1_adj = _ajustar_series_cardio(s1, s_quitar)
                if s1_adj != s1:
                    lineas.append(f"  • Series: {s1_adj} _(plan: {s1})_")
                else:
                    lineas.append(f"  • Series: {s1}")

            # Series bloque 2 (solo si no hay que eliminarlo)
            s2 = datos.get("series_2", "")
            if s2 and b_quitar == 0:
                s2_adj = _ajustar_series_cardio(s2, s_quitar)
                if s2_adj != s2:
                    lineas.append(f"  • Series 2: {s2_adj} _(plan: {s2})_")
                else:
                    lineas.append(f"  • Series 2: {s2}")
            elif s2 and b_quitar > 0:
                lineas.append(f"  • Series 2: eliminadas hoy")

        core = datos.get("core", {})
        if core.get("ejercicio_1"):
            lineas.append(f"  📌 {core['ejercicio_1']}")
        lineas.append("")

    if ajustado:
        lineas.append(f"⚠️ _{ajustado}_")
        lineas.append("")
    lineas.append("Responde *A*, *B* o *C* para ver el detalle completo.")
    return "\n".join(lineas)


def _mensaje_musculacion(estado_dia, entreno, indice, ajuste, metricas) -> str:
    # Formato Principiante: musculación con lista de "ejercicios" → renderizador propio
    if "ejercicios" in entreno.get("musculacion", {}):
        return _mensaje_musculacion_principiante(estado_dia, entreno, indice, metricas)

    sem    = estado_dia["semana_plan"]
    nombre = estado_dia["nombre_dia"]
    suf    = f" {estado_dia.get('nivel', '')}".rstrip()
    emoji_sem = {"verde": "🟢", "amarillo": "🟡", "naranja": "🟠"}
    e_sem  = emoji_sem.get(indice.get("semaforo", "amarillo"), "🟡")
    idx    = indice.get("indice", 50)

    s_quitar  = ajuste["series_quitar"]       # series a quitar por ejercicio
    ss_quitar = ajuste["superseries_quitar"]  # superseries a eliminar por el final

    m = metricas.get("metricas", {}) if metricas else {}

    lineas = [
        f"💪 *{nombre} · Semana {sem} · Alpha50{suf}*",
        f"",
        f"📊 *Tu estado hoy:*",
    ]
    lineas += _lineas_metricas(m)

    lineas += [
        f"",
        f"{e_sem} *Disposición: {idx}/100 — {ajuste['descripcion']}*",
        f"",
        f"💪 *MUSCULACIÓN — Peso corporal*",
        f"",
        f"🔥 Calentamiento: {entreno.get('musculacion', {}).get('calentamiento', '10')}",
        f"",
    ]

    muscu       = entreno.get("musculacion", {})
    superseries = muscu.get("superseries", [])

    # Recortar superseries si naranja
    if ss_quitar > 0:
        total = len(superseries)
        superseries = superseries[:max(1, total - ss_quitar)]
        lineas.append(f"⚠️ _Hoy solo {len(superseries)} de {total} superseries_\n")
    elif s_quitar > 0:
        lineas.append(f"⚠️ _Hoy -{s_quitar} serie por ejercicio_\n")

    lineas.append("📋 *Superseries:*")
    lineas.append(f"_(flexión → 15\" desc → piernas → 50\" desc → siguiente)_")
    lineas.append("")

    for i, ss in enumerate(superseries, 1):
        a = _ajustar_series_muscu(ss.get("a", ""), s_quitar)
        b = _ajustar_series_muscu(ss.get("b", ""), s_quitar)
        lineas.append(f"  {i}. {a}")
        lineas.append(f"     ＋ {b}")
        lineas.append("")

    descanso_ss = muscu.get("descanso_entre_superseries")
    if descanso_ss:
        lineas.append(f"⏱ Entre superseries: {descanso_ss}")
    if muscu.get("estiramientos"):
        lineas.append(f"🧘 Estiramientos: {muscu['estiramientos']}")

    lineas += [
        f"",
        f"Al terminar responde:",
        f"  ✅ *hecho*",
        f"  ⚡ *parcial [qué completaste]*",
        f"  ❌ *no pude*",
    ]
    return "\n".join(lineas)


def _resultado_descanso_plan(estado_dia, metricas) -> dict:
    nombre = estado_dia["nombre_dia"]
    m = metricas.get("metricas", {}) if metricas else {}
    bb = m.get("body_battery")
    msg = (
        f"😴 *{nombre} · Descanso planificado*\n\n"
        f"Hoy no toca entrenar.\n"
    )
    if bb:
        msg += f"Tu Body Battery es {bb}/100 — aprovecha para recargar bien.\n"
    msg += "\nDescansa, hidratate y come bien. Mañana volvemos."
    msg += "\n\nResponde *ok* para registrarlo 👍"
    return {
        "ok": True,
        "tipo": "descanso",
        "nombre_dia": nombre,
        "mensaje_telegram": msg,
    }


def _resultado_descanso_forzado(estado_dia, idx, metricas) -> dict:
    nombre = estado_dia["nombre_dia"]
    m = metricas.get("metricas", {}) if metricas else {}
    bb = m.get("body_battery", "?")
    msg = (
        f"🛑 *{nombre} · Descanso recomendado*\n\n"
        f"Tu disposición hoy es muy baja ({idx}/100).\n"
        f"Body Battery: {bb}/100\n\n"
        f"Forzar el entreno hoy haría más daño que bien.\n"
        f"Descansa activamente: camina, estira, hidratate.\n\n"
        f"Responde *ok* para registrar el descanso\n"
        f"o *igualmente* si quieres entrenar igual _(bajo tu responsabilidad)_."
    )
    return {
        "ok": True,
        "tipo": "descanso_forzado",
        "indice": idx,
        "nombre_dia": nombre,
        "mensaje_telegram": msg,
    }


# ── PROCESAR RESPUESTA USUARIO ────────────────────────────────────────────────
def procesar_respuesta(texto: str, contexto: dict = None) -> dict:
    """
    Procesa la respuesta del usuario por Telegram.
    Retorna acción a tomar y mensaje de confirmación.

    Patrones reconocidos:
    - "A" / "B" / "C"         → selección opción cardio
    - "hecho"                  → completado
    - "parcial [detalle]"      → parcial con descripción
    - "no pude" / "saltado"    → saltado
    - "ok"                     → descanso registrado
    - "igualmente"             → entrena pese a rojo
    """
    from agente_cronologia import registrar_dia, get_estado_hoy
    from agente_plan       import get_detalle_opcion, get_entreno

    texto_lower = texto.strip().lower()
    estado_hoy  = get_estado_hoy()

    # Selección opción cardio
    if texto_lower in ("a", "b", "c") and estado_hoy.get("tipo") == "cardio":
        mapa = {"a": "carrera", "b": "bici", "c": "hiit"}
        opcion = mapa[texto_lower]
        nivel  = estado_hoy["nivel"]
        semana = estado_hoy["semana_plan"]
        dia    = estado_hoy["dia_plan"]
        # Principiante: la opción C es Power Walking, no HIIT
        ops = get_entreno(nivel, semana, dia).get("opciones", {})
        if opcion not in ops and texto_lower == "c" and "power_walking" in ops:
            opcion = "power_walking"
        # Mantener el recorte por disposición que se mostró en el resumen
        factor_t = (contexto or {}).get("ajuste", {}).get("factor_tiempo", 1.0)
        detalle = get_detalle_opcion(nivel, semana, dia, opcion, factor_t)
        return {
            "accion":           "mostrar_detalle",
            "opcion":           opcion,
            "mensaje_telegram": detalle.get("mensaje_telegram", ""),
        }

    # Completado
    if texto_lower in ("hecho", "completado", "✅"):
        registrar_dia("completado",
                      opcion_cardio=contexto.get("opcion") if contexto else None)
        return {
            "accion":           "registrado",
            "estado":           "completado",
            "mensaje_telegram": _msg_confirmacion("completado", estado_hoy),
        }

    # Parcial
    if texto_lower.startswith("parcial"):
        detalle_parcial = texto[7:].strip() or "sin detalle"
        registrar_dia("parcial",
                      opcion_cardio=contexto.get("opcion") if contexto else None,
                      completado_hasta=detalle_parcial)
        return {
            "accion":           "registrado",
            "estado":           "parcial",
            "detalle":          detalle_parcial,
            "mensaje_telegram": _msg_confirmacion("parcial", estado_hoy, detalle_parcial),
        }

    # Saltado / no pude
    if texto_lower in ("no pude", "saltado", "❌", "no"):
        registrar_dia("saltado")
        return {
            "accion":           "registrado",
            "estado":           "saltado",
            "mensaje_telegram": _msg_confirmacion("saltado", estado_hoy),
        }

    # Descanso confirmado
    if texto_lower in ("ok", "descansado"):
        registrar_dia("descanso")
        return {
            "accion":           "registrado",
            "estado":           "descanso",
            "mensaje_telegram": "✅ Descanso registrado. Mañana volvemos con energía.",
        }

    return {
        "accion":           "no_reconocido",
        "mensaje_telegram": "No entendí la respuesta. Di *hecho*, *parcial [detalle]*, *no pude*, *A*, *B* o *C*.",
    }


def _msg_confirmacion(estado: str, estado_dia: dict, detalle: str = None) -> str:
    sem    = estado_dia.get("semana_plan", "?")
    nombre = estado_dia.get("nombre_dia", "hoy")

    if estado == "completado":
        return (
            f"✅ *¡Entreno registrado!*\n"
            f"S{sem} · {nombre} → Completado\n\n"
            f"Bien hecho. Descansa y recupérate bien esta tarde. 💪"
        )
    elif estado == "parcial":
        return (
            f"⚡ *Entreno parcial registrado*\n"
            f"S{sem} · {nombre} → {detalle or 'parcial'}\n\n"
            f"Algo es mejor que nada. La semana se mantiene — "
            f"si hay más días saltados se repetirá la semana."
        )
    elif estado == "saltado":
        return (
            f"❌ *Día registrado como saltado*\n"
            f"S{sem} · {nombre}\n\n"
            f"No pasa nada. La semana {sem} se repetirá la próxima semana "
            f"para no perderte este contenido."
        )
    return "✅ Registrado."


# ── HELPERS ───────────────────────────────────────────────────────────────────
def _cargar_metricas_hoy() -> Optional[dict]:
    """Carga las métricas de hoy desde BD."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM metricas_diarias WHERE fecha=?",
        (date.today().isoformat(),)
    ).fetchone()
    con.close()
    if not row:
        return None
    m = dict(row)
    return {
        "metricas": m,
        "indice": {
            "indice":   m.get("indice_disposicion", 50),
            "semaforo": m.get("semaforo", "amarillo"),
            "emoji":    {"verde":"🟢","amarillo":"🟡","naranja":"🟠","rojo":"🔴"}.get(
                            m.get("semaforo","amarillo"), "🟡"),
            "detalle":  "",
        },
    }


def _extraer_minutos(texto: str) -> Optional[int]:
    import re
    m = re.match(r"(\d+)", texto.strip())
    return int(m.group(1)) if m else None


def _ajustar_series_muscu(texto: str, series_quitar: int) -> str:
    """
    'Flexion normal (4x10)' con series_quitar=1 → 'Flexion normal (3x10, antes 4)'
    Nunca baja de 1 serie. (Notación con 'x' para no romper el Markdown de Telegram.)
    """
    import re
    def reemplazar(m):
        series_orig = int(m.group(1))
        series_adj  = max(1, series_orig - series_quitar)
        reps        = m.group(2)
        if series_adj != series_orig:
            return f"({series_adj}x{reps}, antes {series_orig})"
        return f"({series_adj}x{reps})"
    return re.sub(r'\((\d+)x(\d+[^)]*)\)', reemplazar, texto)


def _ajustar_series_cardio(texto: str, series_quitar: int) -> str:
    """
    '6x200m // 6x50\"' con series_quitar=2 → '4x200m // 4x50\"'
    Ajusta el primer número (nº de series) en cada bloque separado por //.
    """
    import re
    def reemplazar(m):
        n    = max(1, int(m.group(1)) - series_quitar)
        rest = m.group(2)
        return f"{n}x{rest}"
    return re.sub(r'(\d+)x([^\s/]+)', reemplazar, texto)


def _ajustar_ratio_hiit(ratio: str, extra_desc: int) -> str:
    """
    '40\" / 30\"' con extra_desc=10 → '40\" / 40\"'
    Suma segundos al descanso para bajar intensidad.
    """
    import re
    partes = ratio.split("/")
    if len(partes) == 2:
        m = re.search(r'(\d+)', partes[1])
        if m:
            desc_orig = int(m.group(1))
            desc_adj  = desc_orig + extra_desc
            partes[1] = partes[1].replace(str(desc_orig), str(desc_adj), 1)
            return "/".join(partes)
    return ratio


# ── CLI / TEST ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "decidir"

    if cmd == "decidir":
        # Simular métricas si no hay datos en BD
        metricas_sim = {
            "metricas": {
                "body_battery": int(sys.argv[2]) if len(sys.argv) > 2 else 68,
                "horas_sueno":  float(sys.argv[3]) if len(sys.argv) > 3 else 6.5,
                "hrv_status":   sys.argv[4] if len(sys.argv) > 4 else "bajo",
                "fc_reposo":    int(sys.argv[5]) if len(sys.argv) > 5 else 78,
                "estres_promedio": 30,
                "peso_kg":      float(sys.argv[6]) if len(sys.argv) > 6 else 99.0,
            },
            "indice": None,
        }
        # Calcular índice sobre las métricas simuladas
        from agente_metrica import calcular_indice
        metricas_sim["indice"] = calcular_indice(metricas_sim["metricas"])

        resultado = decidir(metricas_hoy=metricas_sim)
        print(resultado.get("mensaje_telegram",
              json.dumps(resultado, ensure_ascii=False, indent=2, default=str)))

    elif cmd == "respuesta":
        texto = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "hecho"
        res = procesar_respuesta(texto)
        print(res.get("mensaje_telegram",
              json.dumps(res, ensure_ascii=False, indent=2)))

    else:
        print("Comandos: decidir [bb] [horas] [hrv] [fc] [peso] | respuesta <texto>")

# fin

