# -*- coding: utf-8 -*-
"""Genera el PDF del plan de fisicas Montornes optimizado con datos Garmin+alpha50.
Castellano, con catalogo de sesiones (ejercicios exactos) y calendario dia a dia."""
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

# --- Paleta ---
AZUL   = colors.HexColor("#1f3a5f")
AZUL2  = colors.HexColor("#2e5c8a")
VERDE  = colors.HexColor("#2e7d32")
AMBAR  = colors.HexColor("#e08a00")
AMBARBG= colors.HexColor("#fbe9cf")
ROJO   = colors.HexColor("#b03030")
ROJOBG = colors.HexColor("#f6dcdc")
AZULBG = colors.HexColor("#dce8f4")
GRIS   = colors.HexColor("#54606e")
GRISBG = colors.HexColor("#eef2f6")
GRISLN = colors.HexColor("#d4dde6")

styles = getSampleStyleSheet()

def S(name, **kw):
    kw.setdefault("parent", styles["Normal"])
    return ParagraphStyle(name, **kw)

body   = S("body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=colors.HexColor("#1a1a1a"), spaceAfter=5)
bodys  = S("bodys", parent=body, fontSize=9, leading=12.5)
h1     = S("h1", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=AZUL, spaceBefore=6, spaceAfter=4)
h2     = S("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=AZUL2, spaceBefore=9, spaceAfter=3)
h3     = S("h3", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=AZUL, spaceBefore=4, spaceAfter=2)
lead   = S("lead", fontName="Helvetica", fontSize=10, leading=15, textColor=colors.HexColor("#222"), spaceAfter=6)
cell   = S("cell", fontName="Helvetica", fontSize=8.5, leading=11)
cellb  = S("cellb", fontName="Helvetica-Bold", fontSize=8.5, leading=11)
cellw  = S("cellw", parent=cell, textColor=colors.white)
cellwb = S("cellwb", parent=cellb, textColor=colors.white)
ex     = S("ex", fontName="Helvetica", fontSize=9, leading=12.5, textColor=colors.HexColor("#1a1a1a"))

def bullets(items, st=body):
    lf = [ListItem(Paragraph(it, st), value="square", bulletColor=AZUL2) for it in items]
    return ListFlowable(lf, bulletType="bullet", start="square", leftIndent=12,
                        bulletFontSize=5, spaceBefore=1, spaceAfter=1)

def header_footer(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(AZUL)
    canvas.rect(0, h-26*mm, w, 26*mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(18*mm, h-14*mm, "PLAN DE ENTRENAMIENTO \u2014 PRUEBA F\u00cdSICA")
    canvas.setFont("Helvetica", 9.5)
    canvas.drawString(18*mm, h-20*mm, "Polic\u00eda Local de Montorn\u00e8s del Vall\u00e8s  \u00b7  Prueba de aptitud f\u00edsica: 10 septiembre 2026")
    canvas.setFillColor(colors.HexColor("#bcd0e6"))
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawRightString(w-18*mm, h-15*mm, "Juan Pablo")
    canvas.setStrokeColor(GRISLN); canvas.setLineWidth(0.5)
    canvas.line(18*mm, 14*mm, w-18*mm, 14*mm)
    canvas.setFillColor(GRIS); canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18*mm, 9.5*mm, "Generado 12 ago 2026  \u00b7  Objetivo \u00fanico: course navette  \u00b7  Ajustar seg\u00fan sem\u00e1foro alpha50 y estado de la costilla")
    canvas.drawRightString(w-18*mm, 9.5*mm, "P\u00e1g. %d" % doc.page)
    canvas.restoreState()

doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                      topMargin=30*mm, bottomMargin=17*mm)
doc.addPageTemplates([PageTemplate(id="all",
    frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")],
    onPage=header_footer)])

def box(flowables, bg=GRISBG, border=GRISLN, pad=8):
    t = Table([[flowables]], colWidths=[doc.width])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),0.6,border),
        ("LEFTPADDING",(0,0),(-1,-1),pad),("RIGHTPADDING",(0,0),(-1,-1),pad),
        ("TOPPADDING",(0,0),(-1,-1),pad),("BOTTOMPADDING",(0,0),(-1,-1),pad),
    ]))
    return t

story = []

# ===== INTRO =====
story.append(Paragraph(
    "Este plan sustituye a la versi\u00f3n gen\u00e9rica. Est\u00e1 calibrado con tus datos reales de Garmin "
    "(VO<sub>2</sub>max, ritmos, frecuencia card\u00edaca, HRV, peso) y tu historial de alpha50. "
    "El objetivo \u00fanico es la <b>course navette</b>: es la \u00fanica prueba que te excluye. Banca (36 rep) y "
    "agilidad (19,5 s) ya las tienes resueltas \u2014 solo mantener.", lead))
story.append(box([
    Paragraph("<b>El n\u00famero que importa</b>", bodys),
    Paragraph("Suelo de exclusi\u00f3n: <b>7,5 paliers</b> (1 punto). Objetivo operativo: <b>9 paliers</b> "
              "para que tu suelo garantizado sea 8 \u2014 margen, no filo.", bodys),
], bg=AZULBG, border=AZUL2))
story.append(Spacer(1, 8))

# ===== DATOS =====
story.append(Paragraph("Lo que dicen tus datos (28 jul \u2013 12 ago)", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=6))
story.append(Paragraph("El motor es mejor de lo que tem\u00edamos", h2))
story.append(Paragraph(
    "Tu <b>VO<sub>2</sub>max de Garmin es 45</b> (lleg\u00f3 a marcar 47), estable. El 6 de agosto hiciste una "
    "carrera <b>real</b>: 4,32 km en 30 min a <b>7:00/km, FC media 145, FC m\u00e1x 168</b>. Eso corresponde a "
    "<b>palier ~8</b> en la tabla de L\u00e9ger. No arrancas en 4-5: arrancas cerca de 7. El 7,5 no es el problema; "
    "el 9 est\u00e1 a tiro.", body))
story.append(Paragraph("Dos banderas rojas que el plan gen\u00e9rico ignoraba", h2))
story.append(bullets([
    "<b>Casi nunca corres \u2014 caminas.</b> Tu historial alpha50 est\u00e1 lleno de 'parcial': "
    "\u00abcamin\u00e9 4,78 km\u00bb, \u00abcamin\u00e9 5,75 km\u00bb, \u00abhe caminado en vez de correr porque no pod\u00eda\u00bb (10 ago). "
    "Solo hay UNA carrera continua real en dos semanas. Tienes el motor pero no lo usas.",
    "<b>Tu recuperaci\u00f3n se est\u00e1 deteriorando</b> (no es opini\u00f3n, son tus n\u00fameros \u2014 tabla abajo).",
]))
data = [
    [Paragraph("M\u00e9trica", cellwb), Paragraph("Mediados de julio", cellwb),
     Paragraph("Ahora (5-12 ago)", cellwb), Paragraph("Lectura", cellwb)],
    [Paragraph("HRV", cellb), Paragraph("40-44 balanced", cell), Paragraph("32-36 <b>unbalanced/low</b>", cell), Paragraph("bajando", cell)],
    [Paragraph("FC reposo", cellb), Paragraph("47-49", cell), Paragraph("54-55", cell), Paragraph("subiendo", cell)],
    [Paragraph("Body Battery", cellb), Paragraph("86-100", cell), Paragraph("36-51", cell), Paragraph("bajando", cell)],
    [Paragraph("\u00cdndice disposici\u00f3n", cellb), Paragraph("78-88 (verde)", cell), Paragraph("57-65 (\u00e1mbar)", cell), Paragraph("bajando", cell)],
    [Paragraph("Peso", cellb), Paragraph("98,7 kg", cell), Paragraph("100,7-101,7 kg", cell), Paragraph("<b>+2-3 kg</b>", cell)],
]
t = Table(data, colWidths=[doc.width*0.24, doc.width*0.26, doc.width*0.30, doc.width*0.20])
t.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),AZUL),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, GRISBG]),
    ("BOX",(0,0),(-1,-1),0.6,GRISLN),("LINEBELOW",(0,0),(-1,-1),0.4,GRISLN),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
    ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
    ("TEXTCOLOR",(3,1),(3,-1),AMBAR),
]))
story.append(Spacer(1,3)); story.append(t); story.append(Spacer(1,4))
story.append(Paragraph(
    "HRV cayendo + FC reposo subiendo + peso subiendo = un cuerpo bajo estr\u00e9s que no recupera bien. Por eso el plan "
    "es de m\u00e1x. 2 sesiones duras/semana gobernadas por tu sem\u00e1foro, no machaque diario.", bodys))

# ===== PALANCAS =====
story.append(Paragraph("Las 3 palancas que priorizan tus datos", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=6))
for tit, txt in [
    ("1. Convertir caminatas en carreras",
     "No te falta volumen, te falta que lo que ya haces sea <b>correr</b>. Tienes fondo de sobra (caminas 5 km sin "
     "problema); el salto es trotar esos mismos minutos."),
    ("2. Bajar el peso",
     "Vas en direcci\u00f3n contraria (+3 kg). Correr la navette con 98 kg en vez de 101 son <b>paliers gratis</b>: la "
     "econom\u00eda de carrera depende del peso. Objetivo: <b>sub-98 para el 10-sep</b> (~0,5 kg/semana, d\u00e9ficit suave "
     "+ prote\u00edna). La palanca m\u00e1s barata que tienes."),
    ("3. Calidad sobre cantidad, gobernada por tu sem\u00e1foro",
     "Las sesiones duras SOLO en d\u00edas verde o \u00e1mbar-alto. Si FC reposo \u226555 y HRV &lt;35 tres d\u00edas seguidos, "
     "esa semana haces una sola sesi\u00f3n dura. Tus datos ya muestran fatiga: no negocies con esto."),
]:
    story.append(Paragraph(tit, h2)); story.append(Paragraph(txt, body))

# ===== ZONAS =====
story.append(Paragraph("Zonas a tus pulsaciones reales", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=6))
story.append(Paragraph("Calculadas con TUS n\u00fameros (FC reposo 54, FC m\u00e1x observada 168):", bodys))
zdata = [
    [Paragraph("Zona", cellwb), Paragraph("FC objetivo", cellwb), Paragraph("Ritmo aprox.", cellwb), Paragraph("Uso", cellwb)],
    [Paragraph("F\u00e1cil / base aer\u00f3bica (Z2)", cellb), Paragraph("125-140", cell), Paragraph("~9:00/km", cell), Paragraph("Rodajes: <b>trotar</b>, donde ahora caminas", cell)],
    [Paragraph("Tempo / umbral", cellb), Paragraph("150-160", cell), Paragraph("~6:45/km", cell), Paragraph("Tirada continua controlada", cell)],
    [Paragraph("Intervalos VO<sub>2</sub>max", cellb), Paragraph("160-170", cell), Paragraph("por sensaci\u00f3n", cell), Paragraph("Casi al l\u00edmite (tu m\u00e1x es 168)", cell)],
]
zt = Table(zdata, colWidths=[doc.width*0.30, doc.width*0.16, doc.width*0.17, doc.width*0.37])
zt.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),AZUL2),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, GRISBG]),
    ("BOX",(0,0),(-1,-1),0.6,GRISLN),("LINEBELOW",(0,0),(-1,-1),0.4,GRISLN),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
    ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
]))
story.append(Spacer(1,3)); story.append(zt); story.append(Spacer(1,6))

# ===== CATALOGO DE SESIONES =====
story.append(Paragraph("Cat\u00e1logo de sesiones (los ejercicios exactos)", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=4))
story.append(Paragraph("El calendario de abajo te dice cada d\u00eda qu\u00e9 sesi\u00f3n toca. Aqu\u00ed tienes el "
                       "desglose completo de cada una. Los ejercicios son a peso corporal (no tienes banca ni circuito).", bodys))

def sesion(letra, titulo, color, items, nota=None):
    head = Table([[Paragraph(letra, S("l", fontName="Helvetica-Bold", fontSize=13, textColor=colors.white, alignment=TA_CENTER)),
                   Paragraph(titulo, S("st", fontName="Helvetica-Bold", fontSize=10.5, textColor=colors.white, leading=13))]],
                 colWidths=[9*mm, doc.width-9*mm])
    head.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),color),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(0,-1),0),("LEFTPADDING",(1,0),(1,-1),6),
    ]))
    inner = [bullets(items, ex)]
    if nota:
        inner.append(Spacer(1,2)); inner.append(Paragraph(nota, S("n", fontName="Helvetica-Oblique", fontSize=8, textColor=GRIS, leading=11)))
    b = Table([[inner]], colWidths=[doc.width])
    b.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.white),("BOX",(0,0),(-1,-1),0.6,color),
        ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))
    return KeepTogether([head, b, Spacer(1,7)])

story.append(Spacer(1,4))
story.append(sesion("A", "Intervalos \u2014 motor / VO\u2082max  (la sesi\u00f3n reina)", AMBAR, [
    "<b>Calentamiento:</b> 10 min trote muy suave (FC &lt;140) + 5 min movilidad: rodillas al pecho, tal\u00f3n al gl\u00fateo, zancadas caminando, skipping suave.",
    "<b>Serie principal:</b> 30/30 \u2192 30\" corriendo fuerte (FC 160-170, \u00abcasi al l\u00edmite\u00bb) + 30\" trote muy suave. N\u00famero de repes seg\u00fan la semana (ver calendario).",
    "<b>Alternativa larga:</b> 4\u00d73 min fuerte (FC 160-168) con 2 min de trote entre series.",
    "<b>Vuelta a la calma:</b> 5-8 min caminando + estirar cu\u00e1driceps, gemelo, isquios.",
], "Es lo que m\u00e1s sube el motor en 4 semanas. Nunca dos d\u00edas seguidos con la sesi\u00f3n D."))
story.append(sesion("B", "Fuerza mantenimiento \u2014 cuerpo entero (solo mochila cargada)", AZUL2, [
    "Flexiones \u2014 4 \u00d7 m\u00e1ximas (o 12-15).",
    "Sentadilla peso corporal \u2014 4 \u00d7 20.",
    "Zancadas alternas caminando \u2014 3 \u00d7 12 por pierna.",
    "Remo inclinado con mochila cargada \u2014 4 \u00d7 12 (equilibra el hombro, sustituye al tir\u00f3n).",
    "Puente de gl\u00fateo \u2014 3 \u00d7 15.",
    "Plancha frontal \u2014 3 \u00d7 45\".",
    "Superman (lumbares) \u2014 3 \u00d7 15.",
], "Circuito, 60-90\" de descanso entre ejercicios, 3-4 vueltas. Flexiones SIN guantes: as\u00ed el empuje es como el d\u00eda de la banca."))
story.append(sesion("C", "Rodaje f\u00e1cil \u2014 base aer\u00f3bica", VERDE, [
    "25-35 min continuos <b>corriendo</b> a FC 125-140 (~9:00/km).",
    "Debes poder mantener una conversaci\u00f3n. Si la FC pasa de 140, baja el ritmo pero <b>NO camines</b>.",
], "Este es el d\u00eda que antes caminabas. Aqu\u00ed se construye el fondo. Trotar, aunque sea lento."))
story.append(sesion("D", "Navette espec\u00edfica + t\u00e9cnica de pivote", ROJO, [
    "<b>Calentamiento:</b> 10 min trote + movilidad de tobillo y cadera.",
    "<b>T\u00e9cnica de pivote (5-8 min):</b> marca 20 m. Haz 8-10 idas y vueltas practicando el giro: frena en 1 paso, pivota sobre el pie (NO giro circular), sal. Que sea autom\u00e1tico.",
    "<b>Bloques:</b> corre de un extremo a otro a ritmo creciente hasta el palier objetivo de la semana, descansa 3 min caminando, repite. Usa la app Course Navette para los pitidos.",
    "<b>Vuelta a la calma:</b> 5 min caminando + estiramientos.",
], "Media navette se juega en no resbalar y en pivotar bien. Zapatilla con buen agarre lateral."))
story.append(sesion("E", "Fuerza core + tobillo/gemelo \u2014 soporte para pivotes", GRIS, [
    "Gemelos de pie \u2014 4 \u00d7 20 (clave para pivotar sin lesionar el tobillo).",
    "Sentadilla isom\u00e9trica en pared \u2014 3 \u00d7 45\".",
    "Zancada b\u00falgara (pie atr\u00e1s en una silla) \u2014 3 \u00d7 10 por pierna.",
    "Plancha lateral \u2014 3 \u00d7 30\" por lado.",
    "Dead bug \u2014 3 \u00d7 12.",
    "Movilidad de cadera y tobillo \u2014 10 min.",
], "Circuito ligero, 3 vueltas. Prepara el tobillo para los frenazos de la navette."))

# ===== CALENDARIO DIA A DIA =====
story.append(Paragraph("Calendario d\u00eda a d\u00eda", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=4))
story.append(Paragraph("Cada d\u00eda con nombre y fecha. La columna 'Sesi\u00f3n' te remite al cat\u00e1logo de arriba; "
                       "el detalle es el ajuste concreto de esa semana. Colores: "
                       "<font color='#e08a00'><b>\u25a0 dura</b></font>  "
                       "<font color='#b03030'><b>\u25a0 navette/evento</b></font>  "
                       "<font color='#2e7d32'><b>\u25a0 rodaje</b></font>  "
                       "<font color='#2e5c8a'><b>\u25a0 fuerza</b></font>  "
                       "<font color='#54606e'><b>\u25a0 descanso</b></font>.", bodys))

KIND = {"dura":AMBARBG, "evento":ROJOBG, "rodaje":colors.HexColor("#e2f0e3"),
        "fuerza":AZULBG, "descanso":GRISBG}

def semana(titulo, subt, filas):
    rows = [[Paragraph("D\u00eda", cellwb), Paragraph("Sesi\u00f3n", cellwb), Paragraph("Qu\u00e9 haces hoy", cellwb)]]
    styl = [
        ("BACKGROUND",(0,0),(-1,0),AZUL),
        ("BOX",(0,0),(-1,-1),0.6,GRISLN),("INNERGRID",(0,0),(-1,-1),0.4,GRISLN),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
    ]
    for i,(dia, ses, det, kind) in enumerate(filas, start=1):
        rows.append([Paragraph(dia, cellb), Paragraph(ses, cellb), Paragraph(det, cell)])
        styl.append(("BACKGROUND",(0,i),(-1,i),KIND[kind]))
    tt = Table(rows, colWidths=[doc.width*0.20, doc.width*0.26, doc.width*0.54])
    tt.setStyle(TableStyle(styl))
    head = Paragraph(titulo + "  <font size=8 color='#54606e'>" + subt + "</font>", h2)
    return KeepTogether([head, Spacer(1,2), tt, Spacer(1,6)])

story.append(Spacer(1,4))
story.append(semana("Semana 1 \u2014 arranque + test", "mi\u00e9 12 \u2013 dom 16 ago  \u00b7  1 sesi\u00f3n dura (el propio test)", [
    ("Mi\u00e9 12/08 (HOY)", "Test navette", "Calienta 10 min. Corre el test navette <b>hasta el fallo</b> con la app. <b>Anota el palier exacto</b> \u2014 es tu l\u00ednea base.", "evento"),
    ("Jue 13/08", "Descanso", "Descanso o 15 min de movilidad suave.", "descanso"),
    ("Vie 14/08", "Sesi\u00f3n C", "Rodaje f\u00e1cil 25 min corriendo a FC 125-140. Primer rodaje de verdad: trotar, no caminar.", "rodaje"),
    ("S\u00e1b 15/08", "Sesi\u00f3n B", "Fuerza completa cuerpo entero (ver cat\u00e1logo B).", "fuerza"),
    ("Dom 16/08", "Descanso", "Descanso total.", "descanso"),
]))
story.append(semana("Semana 2 \u2014 volumen / construcci\u00f3n", "lun 17 \u2013 dom 23 ago  \u00b7  2 duras", [
    ("Lun 17/08", "Sesi\u00f3n A", "Intervalos 30/30 \u00d7 12.", "dura"),
    ("Mar 18/08", "Sesi\u00f3n B", "Fuerza completa cuerpo entero.", "fuerza"),
    ("Mi\u00e9 19/08", "Sesi\u00f3n C", "Rodaje f\u00e1cil 30 min a FC 125-140.", "rodaje"),
    ("Jue 20/08", "Descanso", "Descanso o movilidad 15 min.", "descanso"),
    ("Vie 21/08", "Sesi\u00f3n D", "Navette por bloques: hasta palier 6, descanso 3 min, \u00d7 3. + t\u00e9cnica de pivote.", "evento"),
    ("S\u00e1b 22/08", "Sesi\u00f3n E", "Core + gemelo/tobillo.", "fuerza"),
    ("Dom 23/08", "Descanso", "Descanso total.", "descanso"),
]))
story.append(semana("Semana 3 \u2014 pico", "lun 24 \u2013 dom 30 ago  \u00b7  2 duras + simulacro", [
    ("Lun 24/08", "Sesi\u00f3n A", "Intervalos 30/30 \u00d7 15 (o 4\u00d73 min).", "dura"),
    ("Mar 25/08", "Sesi\u00f3n B", "Fuerza completa cuerpo entero.", "fuerza"),
    ("Mi\u00e9 26/08", "Sesi\u00f3n C", "Rodaje f\u00e1cil 35 min a FC 125-140.", "rodaje"),
    ("Jue 27/08", "Descanso", "Descanso o movilidad 15 min.", "descanso"),
    ("Vie 28/08", "Sesi\u00f3n D", "Navette por bloques: hasta palier 7, descanso 3 min, \u00d7 3. + pivotes.", "evento"),
    ("S\u00e1b 29/08", "SIMULACRO", "D\u00eda real en orden: flexiones (banca) \u2192 20 min descanso \u2192 sprints+giros (agilidad) \u2192 20 min \u2192 <b>navette test #2</b>. Anota el palier, apunta a 8+.", "evento"),
    ("Dom 30/08", "Descanso", "Descanso total.", "descanso"),
]))
story.append(semana("Semana 4 \u2014 descarga / tapering", "lun 31 ago \u2013 dom 6 sep  \u00b7  bajar volumen, mantener intensidad", [
    ("Lun 31/08", "Sesi\u00f3n A", "Intervalos 30/30 \u00d7 10 (reducido, misma intensidad).", "dura"),
    ("Mar 01/09", "Sesi\u00f3n E", "Core + gemelo ligero.", "fuerza"),
    ("Mi\u00e9 02/09", "Sesi\u00f3n D", "Navette corta: hasta palier 7, \u00d7 2. <b>\u00daltima sesi\u00f3n exigente.</b>", "evento"),
    ("Jue 03/09", "Rodaje suave", "20 min muy suave (FC &lt;135) o descanso si notas fatiga.", "rodaje"),
    ("Vie 04/09", "Descanso", "Descanso o movilidad.", "descanso"),
    ("S\u00e1b 05/09", "Activaci\u00f3n", "15 min: trote suave + 4-5 aceleraciones cortas de 15\". Piernas despiertas, sin fatiga.", "rodaje"),
    ("Dom 06/09", "Descanso", "Descanso total.", "descanso"),
]))
story.append(semana("Semana 5 \u2014 semana de la prueba", "lun 7 \u2013 jue 10 sep  \u00b7  solo activaci\u00f3n, piernas frescas", [
    ("Lun 07/09", "Activaci\u00f3n", "15 min trote suave + 3 aceleraciones de 15\". Movilidad. Nada exigente.", "rodaje"),
    ("Mar 08/09", "PRUEBA CULTURAL", "Prueba cultural 10:00 (Teatre municipal). No entrenes fuerte. Caminar suave si acaso.", "evento"),
    ("Mi\u00e9 09/09", "Descanso", "<b>Descanso total</b> o caminar 15 min. Hidrataci\u00f3n y sue\u00f1o. Piernas frescas para ma\u00f1ana.", "descanso"),
    ("Jue 10/09", "PRUEBA F\u00cdSICA", "Prueba f\u00edsica 10:00 (Zona Esportiva, Gran Vial 3). Calienta bien antes de la navette. \u00a1A por el 9!", "evento"),
]))

# Regla de oro
story.append(box([
    Paragraph("<b>Regla de oro (tu sem\u00e1foro manda por encima del calendario)</b>", bodys),
    Paragraph("Cada ma\u00f1ana: si alpha50 da <b>verde / \u00e1mbar-alto</b> \u2192 la sesi\u00f3n del d\u00eda como toca. "
              "Si <b>\u00e1mbar-bajo / naranja</b> \u2192 convierte la sesi\u00f3n dura en rodaje f\u00e1cil o descanso. "
              "Si FC reposo \u226555 y HRV &lt;35 tres d\u00edas seguidos \u2192 esa semana <b>solo UNA</b> sesi\u00f3n dura. "
              "Y si la costilla avisa, para: ninguna sesi\u00f3n vale una reca\u00edda.", bodys),
], bg=AMBARBG, border=AMBAR))
story.append(Spacer(1,8))

# ===== RECORDATORIOS =====
rec_head = Paragraph("Recordatorios que tambi\u00e9n excluyen", h2)
rec = [
    Paragraph("\u2022 <b>El peso es la palanca m\u00e1s barata</b>, y va mal (+3 kg). -3 kg te dan navette sin correr un metro m\u00e1s. Prioridad diaria.", bodys),
    Paragraph("\u2022 <b>Certificado m\u00e9dico oficial</b> el d\u00eda 10 (firmado, colegiado, sello, emitido como m\u00e1x. 3 meses antes, que haga constar la altura). Sin \u00e9l: exclusi\u00f3n autom\u00e1tica.", bodys),
    Paragraph("\u2022 <b>Ropa y calzado deportivo</b>. Zapatilla con agarre lateral para los pivotes.", bodys),
    Paragraph("\u2022 <b>Banca:</b> sin guantes, sin magnesio (lo proh\u00edbe el decreto). Entrena las flexiones sin ellos.", bodys),
    Paragraph("\u2022 <b>Agilidad:</b> 2 intentos, vale el mejor. <b>Banca y navette:</b> un solo intento \u2014 por eso el simulacro del 29/08 importa tanto.", bodys),
    Paragraph("\u2022 <b>Material navette:</b> app 'Course Navette' / 'Test de L\u00e9ger' (gratis) + 20 m medidos con cinta en cualquier sitio llano.", bodys),
]
story.append(KeepTogether([rec_head, Spacer(1,2), box(rec, bg=colors.HexColor("#eef6ef"), border=VERDE)]))

doc.build(story)
print("OK ->", OUT)
