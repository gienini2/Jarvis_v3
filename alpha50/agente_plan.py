"""
Alpha50 · Agente Plan
Ubicación: C:\\Users\\Usuario\\jarvis\\alpha50\\agente_plan.py

Responsabilidades:
- Leer alpha50_plan.json (+ bestia_plan.json si existe)
- Dado semana + dia_plan → devolver el entreno completo
- Para días cardio: devolver las opciones (carrera/bici/hiit)
- Para días musculación: devolver las superseries
- Para días anaeróbicos y dominadas (nivel Bestia): devolver los bloques
- Formatear el mensaje Telegram listo para enviar
"""

import json
import os
from typing import Optional

# ── CONFIGURACIÓN ────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(__file__)
PLAN_PATH = os.path.join(BASE_DIR, "alpha50_plan.json")
BESTIA_PATH = os.path.join(BASE_DIR, "bestia_plan.json")

# Emojis por tipo
EMOJI = {
    "cardio":      "🏃",
    "musculacion": "💪",
    "descanso":    "😴",
    "carrera":     "👟",
    "bici":        "🚴",
    "hiit":        "⚡",
    "anaerobica":  "🔥",
    "dominadas":   "🧗",
}

NOMBRES_DIA = {1:"Lunes",2:"Martes",3:"Miércoles",4:"Jueves",
               5:"Viernes",6:"Sábado",7:"Domingo"}


# ── CARGA DEL PLAN ───────────────────────────────────────────────────────────
def _cargar_plan() -> dict:
    with open(PLAN_PATH, encoding="utf-8") as f:
        plan = json.load(f)
    # El nivel Bestia vive en su propio archivo — se fusiona si existe
    if os.path.exists(BESTIA_PATH):
        with open(BESTIA_PATH, encoding="utf-8") as f:
            plan.update(json.load(f))
    return plan


def _nombre_dia(dia_plan, dia_data=None) -> str:
    if dia_data and dia_data.get("dia_nombre"):
        return dia_data["dia_nombre"]
    return NOMBRES_DIA.get(dia_plan, f"Día {dia_plan}")


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

    if tipo == "cardio":
        return _resultado_cardio(nivel, semana, dia_plan, dia_data)
    elif tipo == "musculacion":
        return _resultado_musculacion(nivel, semana, dia_plan, dia_data)
    elif tipo == "anaerobica":
        return _resultado_anaerobica(nivel, semana, dia_plan, dia_data)
    elif tipo == "dominadas":
        return _resultado_dominadas(nivel, semana, dia_plan, dia_data)
    else:
        return _resultado_descanso(nivel, semana, dia_plan)


# ── BUILDERS DE RESULTADO ────────────────────────────────────────────────────
def _resultado_descanso(nivel, semana, dia_plan) -> dict:
    return {
        "tipo": "descanso",
        "nivel": nivel,
        "semana": semana,
        "dia_plan": dia_plan,
        "nombre_dia": _nombre_dia(dia_plan),
        "mensaje_telegram": "😴 *Hoy toca descanso*\nRecupera bien. El cuerpo construye músculo y resistencia cuando descansa.",
    }


def _resultado_cardio(nivel, semana, dia_plan, dia_data) -> dict:
    opciones = dia_data.get("opciones", {})

    resultado = {
        "tipo": "cardio",
        "nivel": nivel,
        "semana": semana,
        "dia_plan": dia_plan,
        "nombre_dia": _nombre_dia(dia_plan, dia_data),
        "nombre_rutina": dia_data.get("nombre_rutina", ""),
        "opciones_disponibles": list(opciones.keys()),
        "opciones": opciones,
        "mensaje_telegram": _formato_cardio_telegram(nivel, semana, dia_plan, opciones, dia_data),
    }
    return resultado


def _resultado_musculacion(nivel, semana, dia_plan, dia_data) -> dict:
    muscu = dia_data.get("musculacion", {})

    resultado = {
        "tipo": "musculacion",
        "nivel": nivel,
        "semana": semana,
        "dia_plan": dia_plan,
        "nombre_dia": _nombre_dia(dia_plan, dia_data),
        "nombre_rutina": dia_data.get("nombre_rutina", ""),
        "musculacion": muscu,
        "mensaje_telegram": _formato_muscu_telegram(nivel, semana, dia_plan, muscu, dia_data),
    }
    return resultado


def _resultado_anaerobica(nivel, semana, dia_plan, dia_data) -> dict:
    anae = dia_data.get("anaerobica", {})
    return {
        "tipo": "anaerobica",
        "nivel": nivel,
        "semana": semana,
        "dia_plan": dia_plan,
        "nombre_dia": _nombre_dia(dia_plan, dia_data),
        "nombre_rutina": dia_data.get("nombre_rutina", ""),
        "anaerobica": anae,
        "mensaje_telegram": _formato_bloques_telegram(
            "🔥", nivel, semana, dia_plan, dia_data, anae),
    }


def _resultado_dominadas(nivel, semana, dia_plan, dia_data) -> dict:
    domi = dia_data.get("dominadas", {})
    return {
        "tipo": "dominadas",
        "nivel": nivel,
        "semana": semana,
        "dia_plan": dia_plan,
        "nombre_dia": _nombre_dia(dia_plan, dia_data),
        "nombre_rutina": dia_data.get("nombre_rutina", ""),
        "dominadas": domi,
        "mensaje_telegram": _formato_bloques_telegram(
            "🧗", nivel, semana, dia_plan, dia_data, domi),
    }


# ── FORMATEO TELEGRAM ────────────────────────────────────────────────────────
def _formato_bloques_telegram(emoji, nivel, semana, dia_plan, dia_data, datos) -> str:
    """Formatea rutinas basadas en bloques (anaeróbica y dominadas del nivel Bestia)."""
    nombre = _nombre_dia(dia_plan, dia_data)
    lineas = [f"{emoji} *{nombre} · S{semana} · {nivel}*"]
    if dia_data.get("nombre_rutina"):
        lineas.append(f"_{dia_data['nombre_rutina']}_")
    if dia_data.get("tiempo_estimado"):
        lineas.append(f"⏱ Tiempo estimado: {dia_data['tiempo_estimado']}")
    lineas.append("")
    if datos.get("calentamiento"):
        lineas.append(f"🔥 Calentamiento: {datos['calentamiento']}")
        lineas.append("")

    for i, b in enumerate(datos.get("bloques", []), 1):
        lineas.append(f"*{i}.* {b.get('ejercicio','')}")
        if b.get("series"):         lineas.append(f"   • Series: {b['series']}")
        if b.get("nota"):           lineas.append(f"   • {b['nota']}")
        if b.get("descanso_serie"): lineas.append(f"   • Descanso por serie: {b['descanso_serie']}")
        if b.get("descanso_final"): lineas.append(f"   • Al terminar: {b['descanso_final']}")

    core = datos.get("core", {})
    if core:
        lineas.append("\n📌 *Core:*")
        if core.get("ejercicio_1"): lineas.append(f"  · {core['ejercicio_1']}")
        if core.get("descanso"):    lineas.append(f"  · Descanso: {core['descanso']}")
        if core.get("nota"):        lineas.append(f"  · {core['nota']}")

    if datos.get("estiramientos"):
        lineas.append("\n🧘 Estiramientos al terminar.")
    lineas.append("\nResponde *hecho* cuando termines o *parcial [detalle]* si no completaste.")
    return "\n".join(lineas)


def _formato_cardio_telegram(nivel, semana, dia_plan, opciones, dia_data=None) -> str:
    nombre = _nombre_dia(dia_plan, dia_data)

    lineas = [
        f"🏃 *{nombre} · S{semana} · {nivel}*",
        f"Tipo: CARDIO — elige tu opción:",
        "",
    ]

    if "carrera" in opciones:
        c = opciones["carrera"]
        lineas.append("👟 *A) CARRERA*")
        if c.get("nombre"):        lineas.append(f"  _{c['nombre']}_")
        if c.get("calentamiento"): lineas.append(f"  • Calentamiento: {c['calentamiento']}")
        if c.get("continua"):      lineas.append(f"  • Carrera continua: {c['continua']}")
        if c.get("progresivos"):   lineas.append(f"  • Progresivos: {c['progresivos']}")
        if c.get("series_1"):      lineas.append(f"  • Series: {c['series_1']}")
        if c.get("series_2"):      lineas.append(f"  • Series 2: {c['series_2']}")
        if c.get("series_3"):      lineas.append(f"  • Series 3: {c['series_3']}")
        if c.get("nota"):          lineas.append(f"  • {c['nota']}")
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
        if b.get("nombre"):        lineas.append(f"  _{b['nombre']}_")
        if b.get("calentamiento"): lineas.append(f"  • Calentamiento: {b['calentamiento']}")
        if b.get("continua"):      lineas.append(f"  • Pedaleo: {b['continua']}")
        if b.get("progresivos"):   lineas.append(f"  • Progresivos: {b['progresivos']}")
        if b.get("series_1"):      lineas.append(f"  • Series: {b['series_1']}")
        if b.get("series_2"):      lineas.append(f"  • Series 2: {b['series_2']}")
        if b.get("series_3"):      lineas.append(f"  • Series 3: {b['series_3']}")
        if b.get("nota"):          lineas.append(f"  • {b['nota']}")
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

    letras = ["A", "B", "C"]
    disponibles = " o ".join(f"*{letras[i]}*" for i in range(min(len(opciones), 3)))
    lineas.append(f"Responde {disponibles} para confirmar tu opción.")
    return "\n".join(lineas)


def _superseries_lineas(superseries, lineas, sangria="  "):
    for i, ss in enumerate(superseries, 1):
        linea = f"{sangria}{i}. {ss.get('a','')}"
        if ss.get("b") and ss["b"] != "-":
            linea += f"  +  {ss['b']}"
        lineas.append(linea)
        if ss.get("descanso"): lineas.append(f"{sangria}   - {ss['descanso']}")
        if ss.get("nota"):     lineas.append(f"{sangria}   - {ss['nota']}")


def _formato_muscu_telegram(nivel, semana, dia_plan, muscu, dia_data=None) -> str:
    dia_data = dia_data or {}
    nombre = _nombre_dia(dia_plan, dia_data)

    lineas = [
        f"💪 *{nombre} · S{semana} · {nivel}*",
        f"Tipo: MUSCULACIÓN — Peso corporal",
    ]
    if dia_data.get("nombre_rutina"):
        lineas.append(f"_{dia_data['nombre_rutina']}_")
    if dia_data.get("tiempo_estimado"):
        lineas.append(f"⏱ Tiempo estimado: {dia_data['tiempo_estimado']}")
    lineas += ["", f"🔥 Calentamiento: {muscu.get('calentamiento', '10')}"]

    ciclo_act = muscu.get("ciclo_activacion")
    if ciclo_act:
        lineas.append(f"⚙️ Activación: {ciclo_act.get('a','')} + {ciclo_act.get('b','')}"
                      + (f" ({ciclo_act['descanso']})" if ciclo_act.get("descanso") else ""))
    lineas.append("")

    if muscu.get("superseries"):
        lineas.append("📋 *Superseries* (ejercicio A, sin descanso, ejercicio B):")
        _superseries_lineas(muscu["superseries"], lineas)

    for parte in muscu.get("partes", []):
        lineas.append(f"\n📋 *{parte.get('nombre','Bloque')}:*")
        _superseries_lineas(parte.get("superseries", []), lineas)

    for i, ciclo in enumerate(muscu.get("ciclos", []), 1):
        lineas.append(f"\n📋 *Ciclo {i}* (los 4 seguidos sin descanso):")
        for ej in ciclo.get("ejercicios", []):
            lineas.append(f"  · {ej}")
        if ciclo.get("descanso_ciclo"): lineas.append(f"  - Descanso por vuelta: {ciclo['descanso_ciclo']}")
        if ciclo.get("descanso_final"): lineas.append(f"  - Al terminar el ciclo: {ciclo['descanso_final']}")

    for bloque in muscu.get("bloques_amrap", []):
        lineas.append(f"\n📋 *{bloque.get('nombre','AMRAP')}:*")
        for ej in bloque.get("ejercicios", []):
            lineas.append(f"  · {ej}")
        if bloque.get("nota"):           lineas.append(f"  - {bloque['nota']}")
        if bloque.get("descanso_final"): lineas.append(f"  - Al terminar: {bloque['descanso_final']}")

    extra = muscu.get("extra")
    if extra:
        lineas.append(f"\n➕ *{extra.get('nombre','Extra')}:*")
        if extra.get("nota"): lineas.append(f"  {extra['nota']}")
        for b in extra.get("bloques", []):
            lineas.append(f"  · {b.get('ejercicio','')} — {b.get('series','')}"
                          + (f" ({b['nota']})" if b.get("nota") else ""))

    if muscu.get("nota"):
        lineas.append(f"\nℹ️ {muscu['nota']}")
    if muscu.get("descanso_entre_superseries"):
        lineas.append(f"\n⏱ Entre superseries: {muscu['descanso_entre_superseries']}")
    if muscu.get("descanso_cambio_ejercicio"):
        lineas.append(f"⏱ Al cambiar de ejercicio: {muscu['descanso_cambio_ejercicio']}")
    if muscu.get("estiramientos"):
        lineas.append(f"🧘 Estiramientos: {muscu['estiramientos']}")

    lineas.append("\nResponde *hecho* cuando termines o *parcial [detalle]* si no completaste.")
    return "\n".join(lineas)


# ── DETALLE DE UNA OPCIÓN CARDIO ─────────────────────────────────────────────
def get_detalle_opcion(nivel: str, semana: int, dia_plan: int,
                       opcion: str, factor_t: float = 1.0) -> dict:
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
        "mensaje_telegram": _detalle_opcion_telegram(nivel, semana, dia_plan, opcion, datos, factor_t),
    }


def _reducir_tramo(valor, factor_t) -> str:
    """Aplica el factor de disposición a un tramo tipo '30'' -> '24' _(plan: 30')_'."""
    import re
    if not valor or factor_t >= 1.0:
        return valor
    m = re.match(r"\s*(\d+)", str(valor))
    if not m:
        return valor
    mins = int(m.group(1))
    return f"{round(mins * factor_t)}' _(plan: {mins}')_"


def _detalle_opcion_telegram(nivel, semana, dia_plan, opcion, datos, factor_t=1.0) -> str:
    emoji = EMOJI.get(opcion, "🏃")
    nombre = NOMBRES_DIA.get(dia_plan, f"Día {dia_plan}")

    lineas = [f"{emoji} *{nombre} S{semana} — {opcion.upper()}*", ""]

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
        if datos.get("nombre"):
            lineas.append(f"_{datos['nombre']}_")
        for campo, etiqueta in [
            ("calentamiento",         "🔥 Calentamiento"),
            ("continua",              "🏃 Tramo continuo"),
            ("descanso_post_continua","😮‍💨 Descanso"),
            ("progresivos",           "📈 Progresivos"),
            ("series_1",              "⚡ Series 1"),
            ("descanso_series_1",     "  - Descanso"),
            ("series_2",              "⚡ Series 2"),
            ("descanso_series_2",     "  - Descanso"),
            ("series_3",              "⚡ Series 3"),
            ("nota",                  "ℹ️ Nota"),
            ("descanso_final",        "🏁 Bajada de pulsaciones"),
        ]:
            if datos.get(campo):
                valor = datos[campo]
                if campo == "continua":
                    valor = _reducir_tramo(valor, factor_t)
                lineas.append(f"{etiqueta}: {valor}")

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
