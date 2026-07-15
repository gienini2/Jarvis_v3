"""
Alpha50 · Agente Plan
Ubicación: C:\\Users\\Usuario\\jarvis\\alpha50\\agente_plan.py

Responsabilidades:
- Leer alpha50_plan.json
- Dado semana + dia_plan → devolver el entreno completo
- Para días cardio: devolver las 3 opciones (carrera/bici/hiit)
- Para días musculación: devolver las superseries
- Formatear el mensaje Telegram listo para enviar
"""

import json
import os
from typing import Optional

# ── CONFIGURACIÓN ────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(__file__)
PLAN_PATH = os.path.join(BASE_DIR, "alpha50_plan.json")

# Emojis por tipo
EMOJI = {
    "cardio":      "🏃",
    "musculacion": "💪",
    "descanso":    "😴",
    "carrera":     "👟",
    "bici":        "🚴",
    "hiit":        "⚡",
    "power_walking": "🚶",
}

# ── CARGA DEL PLAN ───────────────────────────────────────────────────────────
def _cargar_plan() -> dict:
    with open(PLAN_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── CONSULTA PRINCIPAL ───────────────────────────────────────────────────────
def get_entreno(nivel: str, semana: int, dia_plan: int) -> dict:
    """
    Devuelve el entreno completo para nivel + semana + dia_plan.
    dia_plan: 1=Lunes, 2=Martes, 3=Miércoles, 4=Jueves,
              5=Viernes, 6=Sábado, 7=Domingo
    """
    plan = _cargar_plan()

    sem_key = str(semana)
    dia_key = str(dia_plan)

    nivel_data = plan.get(nivel)
    if not nivel_data:
        return {"error": f"Nivel '{nivel}' no encontrado. Disponibles: {list(plan.keys())}"}

    sem_data = nivel_data.get(sem_key)
    if not sem_data:
        return {"error": f"Semana {semana} no encontrada para nivel {nivel}."}

    dia_data = sem_data.get(dia_key)
    if not dia_data:
        # Días 4 y 7 son descanso — no tienen entrada en el JSON
        if dia_plan in (4, 7):
            return _resultado_descanso(nivel, semana, dia_plan)
        return {"error": f"Día {dia_plan} no encontrado en semana {semana}."}

    tipo = dia_data.get("tipo")

    # Días tipo "sesión" (Avanzado): musculación/HIIT/anaeróbico con "bloques"
    if "bloques" in dia_data:
        return _resultado_sesion(nivel, semana, dia_plan, dia_data)
    if tipo == "cardio":
        return _resultado_cardio(nivel, semana, dia_plan, dia_data)
    elif tipo == "musculacion":
        return _resultado_musculacion(nivel, semana, dia_plan, dia_data)
    else:
        return _resultado_descanso(nivel, semana, dia_plan)


def _resultado_sesion(nivel, semana, dia_plan, dia_data) -> dict:
    """Día de sesión única prescrita (Avanzado): lista de bloques con título."""
    return {
        "tipo":        dia_data.get("tipo", "sesion"),
        "nivel":       nivel,
        "semana":      semana,
        "dia_plan":    dia_plan,
        "nombre_dia":  dia_data.get("dia_nombre", f"Día {dia_plan}"),
        "titulo":      dia_data.get("titulo", ""),
        "bloques":     dia_data.get("bloques", []),
    }


# ── BUILDERS DE RESULTADO ────────────────────────────────────────────────────
def _resultado_descanso(nivel, semana, dia_plan) -> dict:
    nombres = {1:"Lunes",2:"Martes",3:"Miércoles",4:"Jueves",
               5:"Viernes",6:"Sábado",7:"Domingo"}
    return {
        "tipo": "descanso",
        "nivel": nivel,
        "semana": semana,
        "dia_plan": dia_plan,
        "nombre_dia": nombres.get(dia_plan, ""),
        "mensaje_telegram": "😴 *Hoy toca descanso*\nRecupera bien. El cuerpo construye músculo y resistencia cuando descansa.",
    }


def _resultado_cardio(nivel, semana, dia_plan, dia_data) -> dict:
    nombres = {1:"Lunes",3:"Miércoles",6:"Sábado"}
    opciones = dia_data.get("opciones", {})

    resultado = {
        "tipo": "cardio",
        "nivel": nivel,
        "semana": semana,
        "dia_plan": dia_plan,
        "nombre_dia": nombres.get(dia_plan, f"Día {dia_plan}"),
        "opciones_disponibles": list(opciones.keys()),
        "opciones": opciones,
        "mensaje_telegram": _formato_cardio_telegram(nivel, semana, dia_plan, opciones),
    }
    return resultado


def _resultado_musculacion(nivel, semana, dia_plan, dia_data) -> dict:
    nombres = {2:"Martes", 5:"Viernes"}
    muscu = dia_data.get("musculacion", {})

    resultado = {
        "tipo": "musculacion",
        "nivel": nivel,
        "semana": semana,
        "dia_plan": dia_plan,
        "nombre_dia": nombres.get(dia_plan, f"Día {dia_plan}"),
        "musculacion": muscu,
        "mensaje_telegram": _formato_muscu_telegram(nivel, semana, dia_plan, muscu),
    }
    return resultado


# ── FORMATEO TELEGRAM ────────────────────────────────────────────────────────
def _formato_cardio_telegram(nivel, semana, dia_plan, opciones) -> str:
    nombres = {1:"Lunes",3:"Miércoles",6:"Sábado"}
    nombre = nombres.get(dia_plan, f"Día {dia_plan}")

    lineas = [
        f"🏃 *{nombre} · S{semana} · {nivel}*",
        f"Tipo: CARDIO — elige tu opción:",
        "",
    ]

    if "carrera" in opciones:
        c = opciones["carrera"]
        lineas.append("👟 *A) CARRERA*")
        if c.get("calentamiento"): lineas.append(f"  • Calentamiento: {c['calentamiento']}")
        if c.get("continua"):      lineas.append(f"  • Carrera continua: {c['continua']}")
        if c.get("progresivos"):   lineas.append(f"  • Progresivos: {c['progresivos']}")
        if c.get("series_1"):      lineas.append(f"  • Series: {c['series_1']}")
        if c.get("series_2"):      lineas.append(f"  • Series 2: {c['series_2']}")
        if c.get("descanso_final"):lineas.append(f"  • Bajada: {c['descanso_final']}")
        core = c.get("core", {})
        if core:
            lineas.append("  📌 Core:")
            if core.get("ejercicio_1"): lineas.append(f"    · {core['ejercicio_1']}")
            if core.get("ejercicio_2"): lineas.append(f"    · {core['ejercicio_2']}")
        lineas.append("")

    if "bici" in opciones:
        b = opciones["bici"]
        lineas.append("🚴 *B) BICI*")
        if b.get("calentamiento"): lineas.append(f"  • Calentamiento: {b['calentamiento']}")
        if b.get("continua"):      lineas.append(f"  • Pedaleo: {b['continua']}")
        if b.get("progresivos"):   lineas.append(f"  • Progresivos: {b['progresivos']}")
        if b.get("series_1"):      lineas.append(f"  • Series: {b['series_1']}")
        if b.get("series_2"):      lineas.append(f"  • Series 2: {b['series_2']}")
        if b.get("descanso_final"):lineas.append(f"  • Bajada: {b['descanso_final']}")
        core = b.get("core", {})
        if core:
            lineas.append("  📌 Core:")
            if core.get("ejercicio_1"): lineas.append(f"    · {core['ejercicio_1']}")
            if core.get("ejercicio_2"): lineas.append(f"    · {core['ejercicio_2']}")
        lineas.append("")

    if "hiit" in opciones:
        h = opciones["hiit"]
        lineas.append("⚡ *C) HIIT*")
        if h.get("ciclos"):           lineas.append(f"  • Ciclos: {h['ciclos']}")
        if h.get("trabajo_descanso"): lineas.append(f"  • Trabajo/Descanso: {h['trabajo_descanso']}")
        ejercicios = h.get("ejercicios", [])
        if ejercicios:
            lineas.append(f"  • Ejercicios ({len(ejercicios)}):")
            for ej in ejercicios:
                lineas.append(f"    · {ej}")
        if h.get("descanso_ciclo"):   lineas.append(f"  • Descanso entre ciclos: {h['descanso_ciclo']}")
        if h.get("series_burpees"):   lineas.append(f"  • Burpees finales: {h['series_burpees']}")
        core = h.get("core", {})
        if core:
            lineas.append("  📌 Core:")
            if core.get("ejercicio_1"): lineas.append(f"    · {core['ejercicio_1']}")
            if core.get("ejercicio_2"): lineas.append(f"    · {core['ejercicio_2']}")
        lineas.append("")

    lineas.append("Responde *A*, *B* o *C* para confirmar tu opción.")
    return "\n".join(lineas)


def _formato_muscu_telegram(nivel, semana, dia_plan, muscu) -> str:
    nombres = {2:"Martes", 5:"Viernes"}
    nombre = nombres.get(dia_plan, f"Día {dia_plan}")

    lineas = [
        f"💪 *{nombre} · S{semana} · {nivel}*",
        f"Tipo: MUSCULACIÓN — Peso corporal",
        "",
        f"🔥 Calentamiento: {muscu.get('calentamiento', '10')}",
        "",
        "📋 *Superseries* (flexión → descanso 15\" → sentadilla → descanso 50\"):",
    ]

    superseries = muscu.get("superseries", [])
    for i, ss in enumerate(superseries, 1):
        lineas.append(f"  {i}. {ss.get('a','')}  +  {ss.get('b','')}")

    if muscu.get("descanso_entre_superseries"):
        lineas.append(f"\n⏱ Entre superseries: {muscu['descanso_entre_superseries']}")
    if muscu.get("estiramientos"):
        lineas.append(f"🧘 Estiramientos: {muscu['estiramientos']}")

    lineas.append("\nResponde *hecho* cuando termines o *parcial [detalle]* si no completaste.")
    return "\n".join(lineas)


# ── DETALLE DE UNA OPCIÓN CARDIO ─────────────────────────────────────────────
def get_detalle_opcion(nivel: str, semana: int, dia_plan: int,
                       opcion: str) -> dict:
    """
    Devuelve el detalle de una opción cardio específica (carrera/bici/hiit)
    con el mensaje Telegram formateado para esa opción concreta.
    """
    entreno = get_entreno(nivel, semana, dia_plan)
    if "error" in entreno:
        return entreno
    if entreno["tipo"] != "cardio":
        return {"error": "Este día no es de cardio."}

    opcion = opcion.lower()
    datos = entreno["opciones"].get(opcion)
    if not datos:
        return {"error": f"Opción '{opcion}' no disponible. Usa: {entreno['opciones_disponibles']}"}

    return {
        "tipo": "cardio",
        "opcion": opcion,
        "datos": datos,
        "mensaje_telegram": _detalle_opcion_telegram(nivel, semana, dia_plan, opcion, datos),
    }


def _detalle_opcion_telegram(nivel, semana, dia_plan, opcion, datos) -> str:
    emoji = EMOJI.get(opcion, "🏃")
    nombres = {1:"Lunes",3:"Miércoles",6:"Sábado"}
    nombre = nombres.get(dia_plan, f"Día {dia_plan}")

    lineas = [f"{emoji} *{nombre} S{semana} — {opcion.upper()}*", ""]

    # Formato Principiante: lista de pasos
    if "pasos" in datos:
        for p in datos["pasos"]:
            lineas.append(f"• {p.get('campo')}: {p.get('valor')}")
        lineas.append("\n¡A por ello! Responde *hecho*, *parcial [detalle]* o *no pude*.")
        return "\n".join(lineas)

    if opcion == "hiit":
        if datos.get("ciclos"):           lineas.append(f"🔄 Ciclos: {datos['ciclos']}")
        if datos.get("trabajo_descanso"): lineas.append(f"⏱ Trabajo/Descanso: {datos['trabajo_descanso']}")
        ejs = datos.get("ejercicios", [])
        if ejs:
            lineas.append(f"\n📋 Ejercicios ({len(ejs)}):")
            for i, ej in enumerate(ejs, 1):
                lineas.append(f"  {i}. {ej}")
        if datos.get("descanso_ciclo"):   lineas.append(f"\n😮‍💨 Descanso entre ciclos: {datos['descanso_ciclo']}")
        if datos.get("descanso_final"):   lineas.append(f"✅ Descanso final: {datos['descanso_final']}")
        if datos.get("series_burpees"):   lineas.append(f"💥 Burpees: {datos['series_burpees']}")
    else:
        for campo, etiqueta in [
            ("calentamiento",         "🔥 Calentamiento"),
            ("continua",              "🏃 Tramo continuo"),
            ("descanso_post_continua","😮‍💨 Descanso"),
            ("progresivos",           "📈 Progresivos"),
            ("series_1",              "⚡ Series 1"),
            ("descanso_series_1",     "  ↳ Descanso"),
            ("series_2",              "⚡ Series 2"),
            ("descanso_series_2",     "  ↳ Descanso"),
            ("descanso_final",        "🏁 Bajada de pulsaciones"),
        ]:
            if datos.get(campo):
                lineas.append(f"{etiqueta}: {datos[campo]}")

    core = datos.get("core", {})
    if core:
        lineas.append("\n📌 *Core:*")
        if core.get("ejercicio_1"): lineas.append(f"  · {core['ejercicio_1']}")
        if core.get("ejercicio_2"): lineas.append(f"  · {core['ejercicio_2']}")
        if core.get("estiramientos"): lineas.append(f"  · Estiramientos: {core['estiramientos']}")

    lineas.append("\n¡A por ello! Responde *hecho*, *parcial [detalle]* o *no pude*.")
    return "\n".join(lineas)


# ── CLI / TEST ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    cmd    = sys.argv[1] if len(sys.argv) > 1 else "entreno"
    nivel  = sys.argv[2] if len(sys.argv) > 2 else "Intermedio"
    semana = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    dia    = int(sys.argv[4]) if len(sys.argv) > 4 else 1

    if cmd == "entreno":
        resultado = get_entreno(nivel, semana, dia)
        # Mostrar mensaje Telegram limpio
        print(resultado.get("mensaje_telegram", json.dumps(resultado, ensure_ascii=False, indent=2)))

    elif cmd == "opcion":
        opcion = sys.argv[5] if len(sys.argv) > 5 else "carrera"
        resultado = get_detalle_opcion(nivel, semana, dia, opcion)
        print(resultado.get("mensaje_telegram", json.dumps(resultado, ensure_ascii=False, indent=2)))

    elif cmd == "json":
        resultado = get_entreno(nivel, semana, dia)
        resultado.pop("mensaje_telegram", None)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
