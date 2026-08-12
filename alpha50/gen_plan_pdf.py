# -*- coding: utf-8 -*-
"""Genera el PDF del plan de fisicas Montornes optimizado con datos Garmin+alpha50."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, ListFlowable, ListItem,
)

OUT = r"C:\Users\Usuario\Downloads\plan_fisiques_montornes.pdf"

# --- Paleta ---
AZUL   = colors.HexColor("#1f3a5f")   # azul marino cuerpo policial
AZUL2  = colors.HexColor("#2e5c8a")
VERDE  = colors.HexColor("#2e7d32")
AMBAR  = colors.HexColor("#e08a00")
ROJO   = colors.HexColor("#b03030")
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
h2     = S("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=AZUL2, spaceBefore=10, spaceAfter=4)
small  = S("small", fontName="Helvetica", fontSize=8, leading=10.5, textColor=GRIS)
lead   = S("lead", fontName="Helvetica", fontSize=10, leading=15, textColor=colors.HexColor("#222"), spaceAfter=6)
cell   = S("cell", fontName="Helvetica", fontSize=8.5, leading=11)
cellb  = S("cellb", fontName="Helvetica-Bold", fontSize=8.5, leading=11)
cellw  = S("cellw", parent=cell, textColor=colors.white)
cellwb = S("cellwb", parent=cellb, textColor=colors.white)
tag    = S("tag", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=colors.white, alignment=TA_CENTER)

def bullets(items, st=body, bullet_color=AZUL2):
    lf = []
    for it in items:
        lf.append(ListItem(Paragraph(it, st), value="square", bulletColor=bullet_color))
    return ListFlowable(lf, bulletType="bullet", start="square", leftIndent=12,
                        bulletFontSize=5, spaceBefore=1, spaceAfter=1)

# --- Documento con header/footer ---
def header_footer(canvas, doc):
    canvas.saveState()
    w, h = A4
    # franja superior
    canvas.setFillColor(AZUL)
    canvas.rect(0, h-26*mm, w, 26*mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(18*mm, h-14*mm, "PLA D'ENTRENAMENT \u2014 PROVA FISICA")
    canvas.setFont("Helvetica", 9.5)
    canvas.drawString(18*mm, h-20*mm, "Policia Local de Montornes del Valles  \u00b7  Prova d'aptitud fisica: 10 setembre 2026")
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.setFillColor(colors.HexColor("#bcd0e6"))
    canvas.drawRightString(w-18*mm, h-14*mm, "Juan Pablo")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w-18*mm, h-20*mm, "Optimitzat amb dades Garmin + alpha50")
    # pie
    canvas.setStrokeColor(GRISLN)
    canvas.setLineWidth(0.5)
    canvas.line(18*mm, 14*mm, w-18*mm, 14*mm)
    canvas.setFillColor(GRIS)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18*mm, 9.5*mm, "Generat 12 ago 2026  \u00b7  4 setmanes fins la prova  \u00b7  Ajustar segons semafor alpha50 i estat de la costella")
    canvas.drawRightString(w-18*mm, 9.5*mm, "Pag. %d" % doc.page)
    canvas.restoreState()

doc = BaseDocTemplate(OUT, pagesize=A4,
                      leftMargin=18*mm, rightMargin=18*mm,
                      topMargin=30*mm, bottomMargin=17*mm)
frame = Frame(doc.leftMargin, doc.bottomMargin,
              doc.width, doc.height, id="main")
doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=header_footer)])

def chip(text, color):
    t = Table([[Paragraph(text, tag)]], colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),color),
        ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
        ("ROUNDEDCORNERS",[3,3,3,3]),
    ]))
    return t

def box(flowables, bg=GRISBG, border=GRISLN, pad=8):
    t = Table([[flowables]], colWidths=[doc.width])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),bg),
        ("BOX",(0,0),(-1,-1),0.6,border),
        ("LEFTPADDING",(0,0),(-1,-1),pad),("RIGHTPADDING",(0,0),(-1,-1),pad),
        ("TOPPADDING",(0,0),(-1,-1),pad),("BOTTOMPADDING",(0,0),(-1,-1),pad),
    ]))
    return t

story = []

# ===== INTRO =====
story.append(Paragraph(
    "Aquest pla substitueix la versio generica. Esta calibrat amb les teves dades reals de Garmin "
    "(VO<sub>2</sub>max, ritmes, freq. cardiaca, HRV, pes) i el teu historial d'alpha50. "
    "L'objectiu unic es la <b>course navette</b>: es l'unica prova que t'exclou. Banca (36 rep) i agilitat (19,5 s) "
    "ja les tens resoltes \u2014 nomes mantenir.", lead))

# Cuadro objetivo
obj = [
    Paragraph("<b>El numero que importa</b>", bodys),
    Paragraph("Sostre d'exclusio: <b>7,5 paliers</b> (1 punt). Objectiu operatiu: <b>9 paliers</b> "
              "perque el teu terra garantit sigui 8 \u2014 marge, no fil.", bodys),
]
story.append(box(obj, bg=colors.HexColor("#eaf1f8"), border=AZUL2))
story.append(Spacer(1, 8))

# ===== LO QUE DICEN TUS DATOS =====
story.append(Paragraph("El que diuen les teves dades (28 jul \u2013 12 ago)", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=6))

story.append(Paragraph("El motor \u00e9s millor del que t\u00e9miem", h2))
story.append(Paragraph(
    "El teu <b>VO<sub>2</sub>max de Garmin \u00e9s 45</b> (va marcar 47), estable. El 6 d'agost vas fer una carrera "
    "<b>real</b>: 4,32 km en 30 min a <b>7:00/km, FC mitjana 145, FC max 168</b>. Aixo correspon a "
    "<b>palier ~8</b> a la taula de Leger. No arrenques a 4-5: arrenques a prop de 7. El 7,5 no es el problema; "
    "el 9 esta a l'abast.", body))

story.append(Paragraph("Dues banderes vermelles que el pla generic ignorava", h2))
story.append(bullets([
    "<b>Gairebe no corres \u2014 camines.</b> El teu historial alpha50 esta ple de 'parcial': "
    "\u00abcamine 4,78 km\u00bb, \u00abcamine 5,75 km\u00bb, \u00abhe caminado en vez de correr porque no podia\u00bb (10 ago). "
    "Nomes hi ha UNA carrera continua real en dues setmanes. Tens el motor pero no l'uses.",
    "<b>La teva recuperacio s'esta deteriorant</b> (no es opinio, son els teus numeros \u2014 taula a sota).",
]))

# Tabla de tendencia de recuperación
data = [
    [Paragraph("Metrica", cellwb), Paragraph("Mitjans de juliol", cellwb),
     Paragraph("Ara (5-12 ago)", cellwb), Paragraph("Lectura", cellwb)],
    [Paragraph("HRV", cellb), Paragraph("40-44 balanced", cell),
     Paragraph("32-36 <b>unbalanced/low</b>", cell), Paragraph("baixant", cell)],
    [Paragraph("FC repos", cellb), Paragraph("47-49", cell),
     Paragraph("54-55", cell), Paragraph("pujant", cell)],
    [Paragraph("Body Battery", cellb), Paragraph("86-100", cell),
     Paragraph("36-51", cell), Paragraph("baixant", cell)],
    [Paragraph("Index disposicio", cellb), Paragraph("78-88 (verd)", cell),
     Paragraph("57-65 (ambre)", cell), Paragraph("baixant", cell)],
    [Paragraph("Pes", cellb), Paragraph("98,7 kg", cell),
     Paragraph("100,7-101,7 kg", cell), Paragraph("<b>+2-3 kg</b>", cell)],
]
t = Table(data, colWidths=[doc.width*0.24, doc.width*0.26, doc.width*0.30, doc.width*0.20])
t.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),AZUL),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, GRISBG]),
    ("LINEBELOW",(0,0),(-1,-1),0.4,GRISLN),
    ("BOX",(0,0),(-1,-1),0.6,GRISLN),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
    ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
    ("TEXTCOLOR",(3,1),(3,-1),AMBAR),
]))
story.append(Spacer(1,3))
story.append(t)
story.append(Spacer(1,4))
story.append(Paragraph(
    "HRV caient + FC repos pujant + pes pujant = un cos sota estres que no recupera be. El \u00abno podia correr\u00bb "
    "del dia 10 pot ser la costella o fatiga acumulada. <b>Si a sobre li fico 4\u00d74 a maquina dues vegades per "
    "setmana, no millores: et sobreentrenes i arrisques la costella.</b>", bodys))

# ===== PALANCAS =====
story.append(Paragraph("Les 3 palanques que les teves dades prioritzen", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=6))
palancas = [
    ("1. Convertir caminades en carreres",
     "No et falta volum, et falta que el que ja fas sigui <b>correr</b>. Tens fons de sobra (camines 5 km sense "
     "problema); el salt es trotar aquests mateixos minuts."),
    ("2. Baixar el pes",
     "Vas en direccio contraria (+3 kg). Correr la navette amb 98 kg en lloc de 101 son <b>paliers gratis</b>: "
     "l'economia de carrera depen del pes. Objectiu: <b>sub-98 per al 10-set</b> (~0,5 kg/setmana, deficit suau + proteina). "
     "La palanca mes barata que tens."),
    ("3. Qualitat sobre quantitat, governada pel teu semafor",
     "Ja tens l'index de disposicio automatitzat. Les sessions dures NOMES en dies verd o ambre-alt. En ambre-baix/taronja, "
     "recuperes. Menys sessions dures pero de veritat."),
]
for tit, txt in palancas:
    story.append(Paragraph(tit, h2))
    story.append(Paragraph(txt, body))

story.append(Spacer(1,4))

# ===== ZONAS =====
story.append(Paragraph("El teu pla \u2014 4 setmanes a les teves pulsacions reals", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=6))
story.append(Paragraph("Zones calculades amb els TEUS numeros (FC repos 54, FC max observada 168):", bodys))

zdata = [
    [Paragraph("Zona", cellwb), Paragraph("FC objectiu", cellwb), Paragraph("Ritme aprox.", cellwb), Paragraph("Us", cellwb)],
    [Paragraph("Facil / base aerobica (Z2)", cellb), Paragraph("125-140", cell), Paragraph("~9:00/km", cell),
     Paragraph("Rodatges: <b>trotar</b>, on ara camines", cell)],
    [Paragraph("Tempo / llindar", cellb), Paragraph("150-160", cell), Paragraph("~6:45/km", cell),
     Paragraph("Tirada continua controlada", cell)],
    [Paragraph("Intervals VO<sub>2</sub>max", cellb), Paragraph("160-170", cell), Paragraph("per sensacio", cell),
     Paragraph("Gairebe al limit (el teu max es 168)", cell)],
]
zt = Table(zdata, colWidths=[doc.width*0.30, doc.width*0.16, doc.width*0.17, doc.width*0.37])
zt.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),AZUL2),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, GRISBG]),
    ("BOX",(0,0),(-1,-1),0.6,GRISLN),
    ("LINEBELOW",(0,0),(-1,-1),0.4,GRISLN),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
    ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
]))
story.append(Spacer(1,3))
story.append(zt)
story.append(Spacer(1,8))

# ===== ESTRUCTURA SEMANAL =====
story.append(Paragraph("Estructura setmanal (4-5 dies, max 2 dures, \u226548 h entre elles)", h2))
sdata = [
    [Paragraph("Dia", cellwb), Paragraph("Sessio", cellwb), Paragraph("Detall", cellwb)],
    [Paragraph("Dura 1", cellwb), Paragraph("Intervals VO<sub>2</sub>max", cellb),
     Paragraph("30/30 (30\" fort / 30\" trot) \u00d712-15, o 4\u00d73 min a FC 160-170. El que mes puja el motor en 4 setmanes.", cell)],
    [Paragraph("Facil", cellwb), Paragraph("Rodatge Z2 <b>corrent</b>", cellb),
     Paragraph("25-35 min a FC 130 / 9:00. Trotar, NO caminar. Aqui es construeix el fons.", cell)],
    [Paragraph("Dura 2", cellwb), Paragraph("Navette especifica", cellb),
     Paragraph("Blocs: corre fins palier 6-7, descansa 3 min, repeteix \u00d73. + tecnica de pivot (frenar en 1 pas, pivotar, sortir).", cell)],
    [Paragraph("Forca", cellwb), Paragraph("Manteniment", cellb),
     Paragraph("Flexions + motxilla carregada. Banca ja al maxim (36 rep): nomes mantenir.", cell)],
    [Paragraph("Opcional", cellwb), Paragraph("Mobilitat / caminar", cellb),
     Paragraph("Nomes recuperacio activa.", cell)],
]
scol = [doc.width*0.12, doc.width*0.24, doc.width*0.64]
st = Table(sdata, colWidths=scol)
st.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),AZUL),
    ("BACKGROUND",(0,1),(0,-1),AZUL2),
    ("ROWBACKGROUNDS",(1,1),(-1,-1),[colors.white, GRISBG]),
    ("BOX",(0,0),(-1,-1),0.6,GRISLN),
    ("INNERGRID",(0,0),(-1,-1),0.4,GRISLN),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
]))
story.append(st)
story.append(Spacer(1,7))

# Regla de oro
regla = [
    Paragraph("<b>Regla d'or (el teu semafor mana)</b>", bodys),
    Paragraph("Cada mati: si alpha50 dona <b>verd / ambre-alt</b> \u2192 sessio dura com toca. "
              "Si <b>ambre-baix / taronja</b> \u2192 conversio a rodatge facil o descans. "
              "Si FC repos \u226555 i HRV &lt;35 tres dies seguits \u2192 aquella setmana <b>nomes UNA</b> sessio dura. "
              "No negociar: les teves dades ja mostren fatiga.", bodys),
]
story.append(box(regla, bg=colors.HexColor("#fff4e2"), border=AMBAR))
story.append(Spacer(1,10))

# ===== CALENDARIO =====
story.append(Paragraph("Calendari clavat a les teves dates", h1))
story.append(HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=6))
cal = [
    [Paragraph("Setmana", cellwb), Paragraph("Focus", cellwb), Paragraph("Objectiu", cellwb)],
    [Paragraph("Sem 1  (12-17 ago)", cellb),
     Paragraph("Test navette honest. Comences a correr els facils de veritat. 1 dura.", cell),
     Paragraph("Mesura el palier real (aposto 7\u00b10,5)", cell)],
    [Paragraph("Sem 2  (18-24 ago)", cellb),
     Paragraph("2 dures: intervals + navette per blocs.", cell),
     Paragraph("Tocar 8 en test parcial", cell)],
    [Paragraph("Sem 3  (25-31 ago)", cellb),
     Paragraph("Pic. Simulacre el mateix dia en ordre real (banca \u2192 agilitat \u2192 navette amb fatiga).", cell),
     Paragraph("Test #2: apuntar a 8+", cell)],
    [Paragraph("Sem 4  (1-9 set)", cellb),
     Paragraph("Tapering. Ultima dura <b>dc 3 o dj 4</b>. Cultural el 8, <b>descans total el 9</b>, fisiques el 10.", cell),
     Paragraph("Cames fresques el dia 10", cell)],
]
ct = Table(cal, colWidths=[doc.width*0.20, doc.width*0.52, doc.width*0.28])
ct.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),AZUL),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, GRISBG]),
    ("BOX",(0,0),(-1,-1),0.6,GRISLN),
    ("INNERGRID",(0,0),(-1,-1),0.4,GRISLN),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
    ("TEXTCOLOR",(0,1),(0,-1),AZUL2),
]))
story.append(ct)
story.append(Spacer(1,10))

# ===== DOS RECORDATORIOS =====
rec_head = Paragraph("Dos recordatoris finals", h2)
rec = [
    Paragraph("\u2022 <b>La dada que mes val ara mateix es el pes</b>, i va malament. Si nomes poguessis arreglar "
              "una cosa, es aquesta: -3 kg et donen navette sense correr un metre mes.", bodys),
    Paragraph("\u2022 <b>Corre el test aquesta setmana i dona'm el palier real.</b> Amb aixo afino els intervals "
              "al teu fons de veritat, no a l'estimacio.", bodys),
    Paragraph("\u2022 <b>Material navette:</b> app 'Course Navette' / 'Test de Leger' (gratis) pels xiulets oficials "
              "+ 20 m mesurats amb cinta en qualsevol lloc pla. Sabata amb agafada lateral pels pivots.", bodys),
    Paragraph("\u2022 <b>No oblidis</b> el certificat medic oficial (max 3 mesos, amb l'alcada), roba i calcat esportiu, "
              "banca sense guants ni magnesi.", bodys),
]
story.append(KeepTogether([rec_head, Spacer(1,2), box(rec, bg=colors.HexColor("#eef6ef"), border=VERDE)]))

doc.build(story)
print("OK ->", OUT)
