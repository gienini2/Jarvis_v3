# -*- coding: utf-8 -*-
"""PDF del plan de fisicas Montornes (prueba 10-sep-2026), en castellano.
Calibrado con datos reales (Garmin + alpha50) y las 5 pruebas reales de las bases.
Foco: abdominales (unico test que no pasa). Formato calcado al Intermedio de alpha50."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, ListFlowable, ListItem,
)

OUT = r"C:\Users\Usuario\Downloads\plan_fisiques_montornes.pdf"

AZUL   = colors.HexColor("#1f3a5f")
AZUL2  = colors.HexColor("#2e5c8a")
VERDE  = colors.HexColor("#2e7d32")
AMBAR  = colors.HexColor("#e08a00")
AMBARBG= colors.HexColor("#fbe9cf")
ROJO   = colors.HexColor("#b03030")
ROJOBG = colors.HexColor("#f6dcdc")
AZULBG = colors.HexColor("#dce8f4")
VERDEBG= colors.HexColor("#e2f0e3")
GRIS   = colors.HexColor("#54606e")
GRISBG = colors.HexColor("#eef2f6")
GRISLN = colors.HexColor("#d4dde6")

styles = getSampleStyleSheet()
def S(name, **kw):
    kw.setdefault("parent", styles["Normal"]); return ParagraphStyle(name, **kw)

body   = S("body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=colors.HexColor("#1a1a1a"), spaceAfter=5)
bodys  = S("bodys", parent=body, fontSize=9, leading=12.5)
h1     = S("h1", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=AZUL, spaceBefore=6, spaceAfter=4)
h2     = S("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=AZUL2, spaceBefore=9, spaceAfter=3)
lead   = S("lead", fontName="Helvetica", fontSize=10, leading=15, textColor=colors.HexColor("#222"), spaceAfter=6)
cell   = S("cell", fontName="Helvetica", fontSize=8.5, leading=11)
cellb  = S("cellb", fontName="Helvetica-Bold", fontSize=8.5, leading=11)
cellw  = S("cellw", parent=cell, textColor=colors.white)
cellwb = S("cellwb", parent=cellb, textColor=colors.white)
ex     = S("ex", fontName="Helvetica", fontSize=9, leading=12.5, textColor=colors.HexColor("#1a1a1a"))

def bullets(items, st=body):
    lf = [ListItem(Paragraph(it, st), value="square", bulletColor=AZUL2) for it in items]
    return ListFlowable(lf, bulletType="bullet", start="square", leftIndent=12, bulletFontSize=5, spaceBefore=1, spaceAfter=1)

def header_footer(canvas, doc):
    canvas.saveState(); w, h = A4
    canvas.setFillColor(AZUL); canvas.rect(0, h-26*mm, w, 26*mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white); canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(18*mm, h-14*mm, "PLAN DE PRUEBA F\u00cdSICA \u2014 4 SEMANAS")
    canvas.setFont("Helvetica", 9.5)
    canvas.drawString(18*mm, h-20*mm, "Polic\u00eda Local de Montorn\u00e8s del Vall\u00e8s  \u00b7  Prueba f\u00edsica: 10 septiembre 2026, 10:00 h")
    canvas.setFillColor(colors.HexColor("#bcd0e6")); canvas.setFont("Helvetica-Bold", 9)
    canvas.drawRightString(w-18*mm, h-15*mm, "Juan Pablo")
    canvas.setStrokeColor(GRISLN); canvas.setLineWidth(0.5); canvas.line(18*mm, 14*mm, w-18*mm, 14*mm)
    canvas.setFillColor(GRIS); canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18*mm, 9.5*mm, "Generado 12 ago 2026  \u00b7  Foco: abdominales  \u00b7  La costilla manda: ante molestia, bajar carga")
    canvas.drawRightString(w-18*mm, 9.5*mm, "P\u00e1g. %d" % doc.page)
    canvas.restoreState()

doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=30*mm, bottomMargin=17*mm)
doc.addPageTemplates([PageTemplate(id="all",
    frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")], onPage=header_footer)])

def box(flowables, bg=GRISBG, border=GRISLN, pad=8):
    t = Table([[flowables]], colWidths=[doc.width])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),0.6,border),
        ("LEFTPADDING",(0,0),(-1,-1),pad),("RIGHTPADDING",(0,0),(-1,-1),pad),
        ("TOPPADDING",(0,0),(-1,-1),pad),("BOTTOMPADDING",(0,0),(-1,-1),pad)]))
    return t

story = []

# INTRO
story.append(Paragraph(
    "Est\u00e1s <b>admitido</b> (acc\u00e9s lliure, DNI ***4619**). El orden real de las pruebas se cambi\u00f3 por decreto: "
    "cultural <b>8-sep</b>, f\u00edsica <b>10-sep 10:00</b> (Zona Esportiva, Gran Vial 3), catal\u00e1n <b>14-sep</b>. "
    "Este plan ataca solo lo que decide tu 10 de septiembre.", lead))
story.append(box([
    Paragraph("<b>Las pruebas f\u00edsicas de Montorn\u00e8s (no hay navette)</b>", bodys),
    Paragraph("Son 5 ejercicios, cada uno <b>Apto/No apto por separado</b>: hay que pasar los 5, sin compensaci\u00f3n. "
              "Nada de press banca, agilidad ni course navette.", bodys),
], bg=AZULBG, border=AZUL2))
story.append(Spacer(1,8))

# ESTADO ACTUAL
story.append(Paragraph("Tu estado hoy contra los 5 m\u00ednimos (hombre 41-52)", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=6))
data = [
    [Paragraph("Prueba", cellwb), Paragraph("M\u00ednimo", cellwb), Paragraph("Tu marca", cellwb), Paragraph("Estado", cellwb)],
    [Paragraph("Velocidad 50 m", cellb), Paragraph("\u2264 9,1 s", cell), Paragraph("7,02 s (PB verano pasado)", cell), Paragraph("PASA", cellb)],
    [Paragraph("Lanzamiento bal\u00f3n", cellb), Paragraph("\u2265 600 cm", cell), Paragraph("700 cm (bal\u00f3n 4 kg)", cell), Paragraph("PASA", cellb)],
    [Paragraph("Salto horizontal", cellb), Paragraph("\u2265 110 cm", cell), Paragraph("210 cm (PB)", cell), Paragraph("PASA", cellb)],
    [Paragraph("Resistencia 1 km", cellb), Paragraph("\u2264 4\u203250\u2033", cell), Paragraph("4\u203200\u2033 PB \u00b7 hoy navette 6 (34\u00b0C)", cell), Paragraph("PASA*", cellb)],
    [Paragraph("Abdominales 1 min", cellb), Paragraph("\u2265 35", cell), Paragraph("22 y poco", cell), Paragraph("NO PASA", cellb)],
]
t = Table(data, colWidths=[doc.width*0.24, doc.width*0.15, doc.width*0.42, doc.width*0.19])
sty = [("BACKGROUND",(0,0),(-1,0),AZUL),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, GRISBG]),
    ("BOX",(0,0),(-1,-1),0.6,GRISLN),("LINEBELOW",(0,0),(-1,-1),0.4,GRISLN),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6)]
for r in range(1,5): sty.append(("TEXTCOLOR",(3,r),(3,r),VERDE))
sty.append(("BACKGROUND",(0,5),(-1,5),ROJOBG)); sty.append(("TEXTCOLOR",(3,5),(3,5),ROJO))
t.setStyle(TableStyle(sty))
story.append(t); story.append(Spacer(1,4))
story.append(Paragraph("<font size=8>*1 km: tu PB (4\u203200\u2033) es del verano pasado; con la costilla fisurada en Semana Santa bajaste forma. "
    "Aun as\u00ed el corte (4\u203250\u2033) es holgado. <b>Verif\u00edcalo</b> con el test de 1 km y calibramos ritmos.</font>", bodys))
story.append(Paragraph(
    "Traducci\u00f3n: cuatro pruebas ya las tienes. <b>El plan es una cosa: subir abdominales de 22 a 35+</b>, y "
    "mantener el resto sin oxidarlo. La costilla manda por encima de todo.", body))

# ESTRUCTURA
story.append(Paragraph("Estructura semanal (formato Intermedio alpha50)", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=6))
sdata = [
    [Paragraph("D\u00eda", cellwb), Paragraph("Sesi\u00f3n", cellwb), Paragraph("Contenido", cellwb)],
    [Paragraph("Lunes", cellwb), Paragraph("Carrera continua", cellb), Paragraph("Base aer\u00f3bica + <b>Abdominales A</b>", cell)],
    [Paragraph("Martes", cellwb), Paragraph("Musculaci\u00f3n", cellb), Paragraph("Sentadillas + flexiones (superseries) + <b>Abdominales B</b>", cell)],
    [Paragraph("Mi\u00e9rcoles", cellwb), Paragraph("Series velocidad", cellb), Paragraph("Progresivos + series cortas (para el 50 m) + <b>Abdominales A</b>", cell)],
    [Paragraph("Jueves", cellwb), Paragraph("Descanso", cellb), Paragraph("Movilidad suave. Abs solo si la costilla est\u00e1 fina.", cell)],
    [Paragraph("Viernes", cellwb), Paragraph("Espec\u00edfico 1 km", cellb), Paragraph("Series a ritmo objetivo (\u2264 4\u203250\u2033/km) + <b>Abdominales B</b>", cell)],
    [Paragraph("S\u00e1bado", cellwb), Paragraph("Carrera + potencia", cellb), Paragraph("Rodaje/fartlek + saltos y lanzamiento (mantener) + <b>Abdominales A</b>", cell)],
    [Paragraph("Domingo", cellwb), Paragraph("Descanso", cellb), Paragraph("Descanso total.", cell)],
]
stt = Table(sdata, colWidths=[doc.width*0.13, doc.width*0.24, doc.width*0.63])
ssty = [("BACKGROUND",(0,0),(-1,0),AZUL),("BACKGROUND",(0,1),(0,-1),AZUL2),
    ("ROWBACKGROUNDS",(1,1),(-1,-1),[colors.white, GRISBG]),("BOX",(0,0),(-1,-1),0.6,GRISLN),
    ("INNERGRID",(0,0),(-1,-1),0.4,GRISLN),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6)]
for r in (4,7): ssty.append(("BACKGROUND",(0,r),(-1,r),GRISBG))
stt.setStyle(TableStyle(ssty))
story.append(stt); story.append(Spacer(1,4))
story.append(box([Paragraph("<b>Regla de oro:</b> si un d\u00eda vienes justo, se salta una carrera, <b>nunca los abdominales</b>. "
    "Y si la costilla molesta en el sit-up, para y pasa a plancha ese d\u00eda.", bodys)], bg=AMBARBG, border=AMBAR))

# CATALOGO
story.append(Paragraph("Cat\u00e1logo de sesiones", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=4))

def sesion(letra, titulo, color, items, nota=None):
    head = Table([[Paragraph(letra, S("l", fontName="Helvetica-Bold", fontSize=12, textColor=colors.white, alignment=TA_CENTER)),
                   Paragraph(titulo, S("st", fontName="Helvetica-Bold", fontSize=10.5, textColor=colors.white, leading=13))]],
                 colWidths=[9*mm, doc.width-9*mm])
    head.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),color),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(0,-1),0),("LEFTPADDING",(1,0),(1,-1),6)]))
    inner=[bullets(items, ex)]
    if nota:
        inner.append(Spacer(1,2)); inner.append(Paragraph(nota, S("n", fontName="Helvetica-Oblique", fontSize=8, textColor=GRIS, leading=11)))
    b = Table([[inner]], colWidths=[doc.width])
    b.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.white),("BOX",(0,0),(-1,-1),0.6,color),
        ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    return KeepTogether([head, b, Spacer(1,6)])

story.append(Spacer(1,4))
story.append(sesion("A", "Abdominales A \u2014 volumen (resistencia)", ROJO, [
    "Calentamiento: plancha cl\u00e1sica 2\u00d730\u2033 + plancha lateral 2\u00d715\u2033 (protege la costilla).",
    "Serie principal: crunch/sit-up controlado, <b>reps y series seg\u00fan la semana</b> (ver calendario), descanso 40-45\u2033.",
    "Ritmo constante, exhala al subir. No a tir\u00f3n. Estiramiento suave al final.",
], "Cuida la costilla: empieza con crunch parcial y sube a sit-up completo cuando no moleste."))
story.append(sesion("B", "Abdominales B \u2014 espec\u00edfico prueba + test", ROJO, [
    "T\u00e9cnica de la prueba: tumbado, rodillas flexionadas, pies juntos y sujetos, dedos entrelazados en la nuca; "
    "<b>codos tocan rodillas</b> al subir y <b>espalda al suelo</b> al bajar.",
    "Series a esa t\u00e9cnica (ver calendario) + <b>test de 1 minuto</b> los d\u00edas marcados: anota el n\u00famero.",
    "Objetivo de ritmo el d\u00eda de la prueba: ~1 rep cada 1,6\u2033 = 35+ en el minuto.",
], "El test de 1 min es tu term\u00f3metro semanal. Si la costilla avisa, ese d\u00eda solo t\u00e9cnica sin test."))
story.append(sesion("C", "Carrera continua \u2014 base aer\u00f3bica", VERDE, [
    "Calentamiento 10\u2032. Carrera continua a ritmo c\u00f3modo (poder hablar), <b>minutos seg\u00fan semana</b>. Descanso 2-3\u2032.",
    "Core al final: plancha cl\u00e1sica 2\u00d730\u2033 + plancha lateral 4\u00d715\u2033. Estiramientos 10\u2032.",
], "Mismo patr\u00f3n del Lunes de alpha50 Intermedio."))
story.append(sesion("D", "Series de velocidad \u2014 para el 50 m", AMBAR, [
    "Calentamiento 10\u2032 + progresivos 3\u00d740 m.",
    "Series cortas (ver calendario): salidas y aceleraciones limpias, recuperaci\u00f3n completa entre repes.",
    "Core: plancha 2\u00d730\u2033 + lateral 4\u00d715\u2033. Estiramientos.",
], "El 50 m lo pasas de sobra; esto es para no perder la chispa de salida a 100 kg."))
story.append(sesion("E", "Espec\u00edfico 1 km \u2014 asegurar el corte", AMBAR, [
    "Calentamiento 10\u2032 + progresivos 3\u00d740 m.",
    "Series a ritmo objetivo \u2264 4\u203250\u2033/km (= 1\u203256\u2033 por 400 m). Volumen seg\u00fan semana; un d\u00eda, <b>test de 1 km</b> completo.",
    "Vuelta a la calma trotando + estiramientos.",
], "Ritmos a afinar con tu test de 1 km. Con navette 6 en calor, el corte de 4\u203250\u2033 deber\u00eda quedar corto para ti."))
story.append(sesion("F", "Musculaci\u00f3n \u2014 sentadillas + flexiones (superseries)", AZUL2, [
    "Calentamiento 10\u2032. Superserie 1: flexiones de rodillas 4\u00d712 + media sentadilla 4\u00d715.",
    "Superserie 2: flexi\u00f3n normal 3\u00d78 + sentadilla normal 3\u00d715.",
    "Superserie 3: flexiones en 2 aperturas 4\u00d75 + sentadilla sumo 4\u00d710.",
    "Descanso intra 15\u2033 / entre superseries 1\u203230\u2033. Estiramientos 10\u2032.",
], "Copiado del Martes de alpha50 Intermedio S1. Mantiene salto y empuje del lanzamiento."))
story.append(sesion("G", "Saltos + lanzamiento \u2014 mantenimiento de potencia", AZUL2, [
    "Salto horizontal a pies juntos: 5-6 saltos m\u00e1ximos con recuperaci\u00f3n (t\u00e9cnica: brazos y bisagra de cadera).",
    "Lanzamiento de bal\u00f3n medicinal a dos manos: 6-8 lanzamientos m\u00e1ximos.",
], "Van pegados a la carrera del s\u00e1bado. Poco volumen: solo recordar el gesto, ya pasas ambos."))

# CALENDARIO
story.append(Paragraph("Calendario d\u00eda a d\u00eda", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=4))
story.append(Paragraph("Colores: <font color='#b03030'><b>\u25a0 abdominales/test</b></font>  "
    "<font color='#2e7d32'><b>\u25a0 carrera</b></font>  <font color='#e08a00'><b>\u25a0 velocidad/1 km</b></font>  "
    "<font color='#2e5c8a'><b>\u25a0 fuerza/potencia</b></font>  <font color='#54606e'><b>\u25a0 descanso</b></font>.", bodys))
KIND = {"abs":ROJOBG, "carrera":VERDEBG, "vel":AMBARBG, "fuerza":AZULBG, "descanso":GRISBG}

def semana(titulo, subt, filas):
    rows=[[Paragraph("D\u00eda", cellwb), Paragraph("Sesi\u00f3n", cellwb), Paragraph("Qu\u00e9 haces hoy", cellwb)]]
    styl=[("BACKGROUND",(0,0),(-1,0),AZUL),("BOX",(0,0),(-1,-1),0.6,GRISLN),("INNERGRID",(0,0),(-1,-1),0.4,GRISLN),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6)]
    for i,(dia,ses,det,k) in enumerate(filas, start=1):
        rows.append([Paragraph(dia,cellb),Paragraph(ses,cellb),Paragraph(det,cell)])
        styl.append(("BACKGROUND",(0,i),(-1,i),KIND[k]))
    tt=Table(rows, colWidths=[doc.width*0.19, doc.width*0.25, doc.width*0.56]); tt.setStyle(TableStyle(styl))
    return KeepTogether([Paragraph(titulo+"  <font size=8 color='#54606e'>"+subt+"</font>", h2), Spacer(1,2), tt, Spacer(1,6)])

story.append(Spacer(1,4))
story.append(semana("Semana 1 \u2014 arranque + referencias", "mi\u00e9 12 \u2013 dom 16 ago", [
    ("Mi\u00e9 12/08 (HOY)", "Hecho: navette", "Ya corriste navette (6 paliers, 34\u00b0C). Referencia tomada. Descansa.", "descanso"),
    ("Jue 13/08", "Test 1 km + Abs B", "<b>Test de 1 km</b> a tope (referencia). Suave. Luego Abs B: 4\u00d712 t\u00e9cnica + plancha 3\u00d730\u2033.", "abs"),
    ("Vie 14/08", "Carrera continua + Abs A", "Sesi\u00f3n C: continua 25-30\u2032 c\u00f3moda. Abs A: 4\u00d715 crunch, desc 45\u2033.", "carrera"),
    ("S\u00e1b 15/08", "Musculaci\u00f3n + Abs A", "Sesi\u00f3n F (sentadillas+flexiones). Abs A: 4\u00d715.", "fuerza"),
    ("Dom 16/08", "Descanso", "Descanso total.", "descanso"),
]))
story.append(semana("Semana 2 \u2014 volumen", "lun 17 \u2013 dom 23 ago  \u00b7  primer test de abs", [
    ("Lun 17/08", "Carrera continua + Abs A", "Continua 30\u2032. Abs A: 4\u00d716.", "carrera"),
    ("Mar 18/08", "Musculaci\u00f3n + Abs B", "Sesi\u00f3n F. Abs B: 5\u00d712 estilo prueba.", "fuerza"),
    ("Mi\u00e9 19/08", "Velocidad + Abs A", "Sesi\u00f3n D: progresivos + 5\u00d760 m. Abs A: 5\u00d716.", "vel"),
    ("Jue 20/08", "Descanso", "Movilidad. Abs suave opcional si costilla fina.", "descanso"),
    ("Vie 21/08", "1 km + Abs B", "Sesi\u00f3n E: 4\u00d7400 m a ritmo objetivo. <b>Abs B: test 1 min</b> (anota).", "abs"),
    ("S\u00e1b 22/08", "Carrera + potencia + Abs A", "Fartlek 25\u2032 + Sesi\u00f3n G (saltos+lanzamiento). Abs A: 5\u00d718.", "carrera"),
    ("Dom 23/08", "Descanso", "Descanso total.", "descanso"),
]))
story.append(semana("Semana 3 \u2014 pico", "lun 24 \u2013 dom 30 ago  \u00b7  segundo test de abs", [
    ("Lun 24/08", "Carrera continua + Abs A", "Continua 35\u2032. Abs A: 5\u00d720.", "carrera"),
    ("Mar 25/08", "Musculaci\u00f3n + Abs B", "Sesi\u00f3n F. Abs B: 5\u00d715 estilo prueba.", "fuerza"),
    ("Mi\u00e9 26/08", "Velocidad + Abs A", "Sesi\u00f3n D: progresivos + 6\u00d760 m r\u00e1pidos. Abs A: EMOM 10\u2032 (12 sit-ups/min).", "vel"),
    ("Jue 27/08", "Descanso", "Movilidad. Costilla a punto para el pico.", "descanso"),
    ("Vie 28/08", "1 km + Abs B", "Sesi\u00f3n E: 3\u00d7600 m a ritmo objetivo. <b>Abs B: 3\u00d7(1 min m\u00e1x)</b> desc 2\u2032 \u2014 apunta 30+.", "abs"),
    ("S\u00e1b 29/08", "Simulacro + potencia", "Mini-simulacro: 50 m + salto + lanzamiento + 1 km, en orden. Anota todo.", "vel"),
    ("Dom 30/08", "Descanso", "Descanso total.", "descanso"),
]))
story.append(semana("Semana 4 \u2014 afinar + tapering", "lun 31 ago \u2013 mi\u00e9 10 sep  \u00b7  bajar volumen, llegar fresco", [
    ("Lun 31/08", "Carrera suave + Abs A", "Continua 25\u2032 suave. Abs A: 4\u00d718.", "carrera"),
    ("Mar 01/09", "Musculaci\u00f3n ligera + Abs B", "Sesi\u00f3n F al 70%. Abs B: 4\u00d715 t\u00e9cnica.", "fuerza"),
    ("Mi\u00e9 02/09", "Velocidad corta + Abs A", "Progresivos + 4\u00d740 m. <b>Abs B: test 1 min</b> (\u00bfllegas a 35?).", "abs"),
    ("Jue 03/09", "Descanso", "Movilidad suave.", "descanso"),
    ("Vie 04/09", "Activaci\u00f3n 1 km + Abs suave", "Sesi\u00f3n E corta: 2\u00d7400 m. Abs: solo 3\u00d712 t\u00e9cnica, sin fallo.", "vel"),
    ("S\u00e1b 05/09", "Rodaje suave", "15-20\u2032 trote + 3-4 aceleraciones de 15\u2033. Piernas despiertas.", "carrera"),
    ("Dom 06/09", "Descanso", "Descanso total.", "descanso"),
    ("Lun 07/09", "Activaci\u00f3n", "15\u2032 trote + 3 aceleraciones. Movilidad. Nada exigente.", "carrera"),
    ("Mar 08/09", "PRUEBA CULTURAL", "Cultural 10:00 (Teatre municipal). Lleva bol\u00edgrafo. No entrenes fuerte.", "abs"),
    ("Mi\u00e9 09/09", "Descanso total", "Descanso o caminar 15\u2032. Sue\u00f1o e hidrataci\u00f3n. Piernas frescas.", "descanso"),
    ("Jue 10/09", "PRUEBA F\u00cdSICA", "10:00 (Zona Esportiva, Gran Vial 3). Certificado m\u00e9dico. Calienta bien. \u00a1A por los 5!", "abs"),
]))

# RECORDATORIOS
rec_head = Paragraph("No lo olvides (excluye igual)", h2)
rec = [
    Paragraph("\u2022 <b>Certificado m\u00e9dico oficial</b> el 10-sep: colegiado, sellado, emitido m\u00e1x. 3 meses antes, haciendo constar que est\u00e1s apto para las pruebas. Sin \u00e9l: exclusi\u00f3n autom\u00e1tica.", bodys),
    Paragraph("\u2022 <b>Ropa y calzado deportivo.</b> Bal\u00f3n medicinal de la prueba suele ser de 3 kg (entrenas con 4, mejor).", bodys),
    Paragraph("\u2022 <b>Abdominales:</b> un ayudante te sujeta los pies; repite hasta que suene el minuto. Es tu \u00fanica prueba en riesgo: no la descuides ni un d\u00eda.", bodys),
    Paragraph("\u2022 <b>Costilla flotante:</b> ante dolor puntual, cambia sit-up por plancha ese d\u00eda. El plan sube solo si la costilla lo permite.", bodys),
    Paragraph("\u2022 <b>Peso:</b> lo llevas con el plan de mentorizados de alpha50. Cada kg menos protege sprint, salto y 1 km (y la m\u00e9dica futura).", bodys),
]
story.append(KeepTogether([rec_head, Spacer(1,2), box(rec, bg=VERDEBG, border=VERDE)]))

doc.build(story)
print("OK ->", OUT)
