# -*- coding: utf-8 -*-
"""
Alpha50 · Parser de PDFs de plan (nivel Principiante y compatibles)
Ubicación: C:\\Users\\Usuario\\jarvis\\alpha50\\parse_alpha50_pdf.py

Convierte un PDF de una semana en un bloque JSON con el esquema de alpha50_plan.json.
La musculación se normaliza a superseries (par torso/pierna) para reutilizar el
agente_decisor sin cambios. El cardio mantiene carrera/bici/power_walking.

Uso (PowerShell en el PC local):
    ..\\.venv\\Scripts\\python.exe parse_alpha50_pdf.py <archivo.pdf> [--raw]
    --raw : volcar también la extracción fiel sin normalizar (debug)

Dependencia: pip install pypdf
"""
import re, json, sys
from pypdf import PdfReader

DIAS = {"LUNES":1,"MARTES":2,"MIÉRCOLES":3,"MIERCOLES":3,"JUEVES":4,
        "VIERNES":5,"SÁBADO":6,"SABADO":6,"DOMINGO":7}
DIA_NOMBRE = {1:"Lunes",2:"Martes",3:"Miércoles",4:"Jueves",5:"Viernes",6:"Sábado",7:"Domingo"}
TORSO_KW  = ("flex","fondo","plancha","press","remo","hombro")
PIERNA_KW = ("sentadilla","zancada","pierna","glúteo","gluteo","puente","estocada","zancad")


def texto_normalizado(path):
    """Extrae texto de todas las páginas colapsando los espacios rotos de pypdf."""
    r = PdfReader(path)
    return " ".join(re.sub(r"\s+", " ", (p.extract_text() or "")).strip() for p in r.pages)


def detectar_meta(txt):
    sem = re.search(r"SEMANA\s+(\d+)", txt)
    niv = re.search(r"NIVEL\s+([A-ZÁÉÍÓÚ]+)", txt)
    return (int(sem.group(1)) if sem else None,
            niv.group(1).capitalize() if niv else None)


def _quita_pagina_final(b):
    return re.sub(r"\s+\d+\s*$", "", b).strip()


def split_dias(txt):
    """Devuelve [(tipo, dia_idx, cuerpo)] en orden de aparición."""
    pat = re.compile(
        r"NIVEL\s+[A-ZÁÉÍÓÚ]+\s+(ACONDICIONAMIENTO\s+(?:AERÓBICO|AEROBICO|MUSCULAR)|DESCANSO)\s+"
        r"(LUNES|MARTES|MIÉRCOLES|MIERCOLES|JUEVES|VIERNES|SÁBADO|SABADO|DOMINGO)", re.IGNORECASE)
    ms = list(pat.finditer(txt))
    res = []
    for i, m in enumerate(ms):
        cab = m.group(1).upper()
        dia = DIAS[m.group(2).upper()]
        cuerpo = txt[m.end(): ms[i+1].start() if i+1 < len(ms) else len(txt)].strip()
        tipo = "descanso" if "DESCANSO" in cab else ("musculacion" if "MUSCULAR" in cab else "cardio")
        res.append((tipo, dia, _quita_pagina_final(cuerpo)))
    return res


def parse_cardio(cuerpo):
    """Separa las 3 columnas (carrera/bici/power walking) por el marcador de calentamiento."""
    cuerpo = re.sub(r"OP\.\s*CARRERA\s*OP\.\s*BICICLETA\s*OP\.\s*POWER\s*WALKING", "|||", cuerpo, flags=re.I)
    if "|||" in cuerpo:
        cuerpo = cuerpo.split("|||", 1)[1]
    bloques = [b.strip() for b in re.split(r"(?=10'?\s*de\s*calentamiento)", cuerpo, flags=re.I) if b.strip()]
    return dict(zip(["carrera", "bici", "power_walking"],
                    [re.sub(r"\s+", " ", b).strip() for b in bloques]))


def parse_muscu(cuerpo):
    """Extrae la lista plana de ejercicios: 'Nombre N series x R rep' / 'Nombre N x R'."""
    pat = re.compile(r"([A-Za-zÁÉÍÓÚáéíóúñÑ' ]+?)\s+(\d+)\s*(?:series\s*)?x\s*(\d+)\s*(\")?", re.I)
    ej = []
    for m in pat.finditer(cuerpo):
        nombre = m.group(1).strip(" .")
        nombre = re.sub(r"^10'?\s*de\s*calentamiento[^.]*\.\s*", "", nombre, flags=re.I).strip(" .")
        ej.append({"nombre": nombre, "series": int(m.group(2)), "reps": m.group(3) + (m.group(4) or "")})
    md = re.search(r"Descansa\s+([^.]+)\.", cuerpo)
    return {"calentamiento": "10'", "ejercicios": ej, "descanso": md.group(1).strip() if md else ""}


def _fmt(e):
    return f"{e['nombre']} ({e['series']}*{e['reps']})"


def a_superseries(ej):
    """Empareja torso (flexiones...) con pierna (sentadillas...) en formato superserie."""
    torso  = [e for e in ej if any(k in e["nombre"].lower() for k in TORSO_KW)]
    pierna = [e for e in ej if any(k in e["nombre"].lower() for k in PIERNA_KW)]
    usados = set(id(x) for x in torso) | set(id(x) for x in pierna)
    otros  = [e for e in ej if id(e) not in usados]
    ss = []
    for i in range(max(len(torso), len(pierna))):
        ss.append({"a": _fmt(torso[i])  if i < len(torso)  else "",
                   "b": _fmt(pierna[i]) if i < len(pierna) else ""})
    for o in otros:
        ss.append({"a": _fmt(o), "b": ""})
    return ss


def normalizar(path):
    txt = texto_normalizado(path)
    sem, niv = detectar_meta(txt)
    dias_norm, dias_raw = {}, {}
    for tipo, dia, cuerpo in split_dias(txt):
        if tipo == "descanso":
            continue  # los descansos los gestiona agente_cronologia
        if tipo == "cardio":
            op = parse_cardio(cuerpo)
            dias_raw[str(dia)] = {"tipo": tipo, "opciones": op}
            dias_norm[str(dia)] = {"tipo": "cardio", "dia_nombre": DIA_NOMBRE[dia], "opciones": {
                "carrera":       {"calentamiento": "10'", "instrucciones": op.get("carrera", "")},
                "bici":          {"calentamiento": "10'", "instrucciones": op.get("bici", "")},
                "power_walking": {"calentamiento": "10'", "instrucciones": op.get("power_walking", "")}}}
        else:
            mu = parse_muscu(cuerpo)
            dias_raw[str(dia)] = {"tipo": tipo, "musculacion": mu}
            dias_norm[str(dia)] = {"tipo": "musculacion", "dia_nombre": DIA_NOMBRE[dia], "musculacion": {
                "calentamiento": mu["calentamiento"],
                "superseries": a_superseries(mu["ejercicios"]),
                "descanso_intra": mu["descanso"],
                "descanso_entre_superseries": "1'30\"",
                "estiramientos": "10'"}}
    return sem, niv, dias_norm, dias_raw


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "eps3.pdf"
    sem, niv, norm, raw = normalizar(path)
    salida = {"nivel": niv, "semana": sem, "dias": norm}
    if "--raw" in sys.argv:
        salida["_raw"] = raw
    print(json.dumps(salida, ensure_ascii=False, indent=2))
