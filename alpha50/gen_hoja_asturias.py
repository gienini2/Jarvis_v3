# -*- coding: utf-8 -*-
"""Hoja imprimible de 1 pagina para los dias en Asturias: rutina sin material,
protocolo legal de abdominales y hueco para el test de 1 km."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, ListFlowable, ListItem,
)

OUT = r"C:\Users\Usuario\Downloads\hoja_asturias.pdf"

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
MORADO = colors.HexColor("#5b4b8a")
NOCHEBG= colors.HexColor("#e6e2f0")

styles = getSampleStyleSheet()
def S(name, **kw):
    kw.setdefault("parent", styles["Normal"]); return ParagraphStyle(name, **kw)

body  = S("body", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=colors.HexColor("#1a1a1a"))
h2    = S("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=12, textColor=AZUL2, spaceBefore=4, spaceAfter=2)
cell  = S("cell", fontName="Helvetica", fontSize=8, leading=10)
cellb = S("cellb", fontName="Helvetica-Bold", fontSize=8, leading=10)
cellwb= S("cellwb", parent=cellb, textColor=colors.white)
ex    = S("ex", fontName="Helvetica", fontSize=8, leading=10.5)

def bullets(items, st=ex):
    lf=[ListItem(Paragraph(it, st), value="square", bulletColor=AZUL2) for it in items]
    return ListFlowable(lf, bulletType="bullet", start="square", leftIndent=10, bulletFontSize=4.5, spaceBefore=0.5, spaceAfter=0.5)

def header(canvas, doc):
    canvas.saveState(); w,h=A4
    canvas.setFillColor(AZUL); canvas.rect(0, h-16*mm, w, 16*mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white); canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(14*mm, h-10*mm, "HOJA ASTURIAS \u2014 sin material")
    canvas.setFont("Helvetica", 8.5); canvas.setFillColor(colors.HexColor("#bcd0e6"))
    canvas.drawRightString(w-14*mm, h-10*mm, "17-24 ago \u00b7 Asturias + noches \u00b7 prueba 10-sep")
    canvas.setFillColor(GRIS); canvas.setFont("Helvetica", 7)
    canvas.drawString(14*mm, 8*mm, "Foco: abdominales legales. El sem\u00e1foro de Garmin manda: si da naranja/rojo, baja a suave o solo abs t\u00e9cnica.")
    canvas.restoreState()

doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=19*mm, bottomMargin=11*mm)
doc.addPageTemplates([PageTemplate(id="all",
    frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="m")], onPage=header)])

def box(flow, bg=GRISBG, border=GRISLN, pad=6, width=None):
    t=Table([[flow]], colWidths=[width or doc.width])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),0.6,border),
        ("LEFTPADDING",(0,0),(-1,-1),pad),("RIGHTPADDING",(0,0),(-1,-1),pad),
        ("TOPPADDING",(0,0),(-1,-1),pad),("BOTTOMPADDING",(0,0),(-1,-1),pad)]))
    return t

story=[]
story.append(Paragraph("El viaje no te frena: esta prueba no necesita gimnasio. Lo innegociable son los <b>abdominales cada d\u00eda</b> "
    "(tu \u00fanico test en riesgo). Solo Mar 18 y Mi\u00e9 19 son d\u00edas buenos de entreno; el resto (viajes y "
    "<b>noches vie-dom</b>) es mantenimiento: abs cortos y proteger el sue\u00f1o. Retomas fuerte el lunes 24.", body))
story.append(Spacer(1,4))

# PROTOCOLO ABDOMINALES
story.append(Paragraph("Protocolo de abdominales LEGAL (lo m\u00e1s importante)", h2))
tec = [
    Paragraph("<b>T\u00e9cnica (as\u00ed cuenta en la prueba):</b>", ex),
    bullets([
        "Tumbado, rodillas ~90\u00b0, pies juntos y <b>anclados</b> (bajo un sof\u00e1/cama/mueble, o que alguien te los sujete).",
        "Dedos <b>entrelazados en la nuca</b>, codos abiertos. NO tirar del cuello ni impulsar con los brazos.",
        "Subir hasta que los <b>codos tocan las rodillas</b>; bajar hasta que la <b>espalda toca el suelo</b>. Exhala al subir.",
        "Solo cuenta la completa: <b>mejor 12 buenas que 22 a medias</b>.",
    ]),
    Spacer(1,2),
    Paragraph("<b>Progresi\u00f3n</b> (si no completas la serie, haz las que salgan legales; anota siempre):", ex),
    bullets([
        "<b>D\u00eda volumen (A):</b> 4 \u00d7 12-15 legales, descanso 45\u2033. + plancha 3\u00d730\u2033 (protege la costilla).",
        "<b>D\u00eda test (B):</b> 1 minuto al m\u00e1ximo legal \u2192 <b>an\u00f3talo</b>. Luego 3\u00d710 de t\u00e9cnica sin fallo.",
        "<b>Complemento (casi diario):</b> crunch inverso 3\u00d712 + dead bug 3\u00d710 \u2014 suman core sin cargar la costilla.",
    ]),
    Spacer(1,1),
    Paragraph("<b>Costilla flotante:</b> si molesta al hacer el sit-up, ese d\u00eda solo plancha + crunch inverso. El plan sube solo si la costilla lo permite.", S("n", fontName="Helvetica-Oblique", fontSize=7.5, textColor=GRIS, leading=10)),
]
story.append(box(tec, bg=ROJOBG, border=ROJO))
story.append(Spacer(1,5))

# RUTINA DIAS
story.append(Paragraph("Rutina de los d\u00edas en Asturias", h2))
KIND={"abs":ROJOBG,"carrera":VERDEBG,"vel":AMBARBG,"fuerza":AZULBG,"descanso":GRISBG,"noche":NOCHEBG}
filas=[
    ("Lun 17/08","Viaje + descanso","8 h de coche a Asturias + entrevista coach 18h. Descanso total (ven\u00edas de naranja). Estira al llegar.","descanso"),
    ("Mar 18/08","Abs baseline","Asentar. <b>Test 1 min LEGAL</b> fresco (pies anclados, sin impulso) \u2192 anota. Luego 3\u00d712 t\u00e9cnica + movilidad.","abs"),
    ("Mi\u00e9 19/08","TEST 1 KM + Abs","Por la ma\u00f1ana (fresco): calienta 10\u2032, <b>test de 1 km</b> a tope en tramo llano \u2192 anota. Abs A: 4\u00d712.","vel"),
    ("Jue 20/08","Viaje de vuelta","8 h de coche de regreso. Descanso. Camina y estira en las paradas.","descanso"),
    ("Vie 21/08","Noche 19-04 \u00b7 Abs","Trabajas de noche (sales ~18h). <b>Solo abs 10\u2032</b> (4\u00d712 legales + plancha) cuando est\u00e9s despierto. Duerme de d\u00eda.","noche"),
    ("S\u00e1b 22/08","Noche 19-04 \u00b7 Abs","Igual: abs cortos + crunch inverso. Nada de carrera dura. Prioriza dormir y comer bien.","noche"),
    ("Dom 23/08","Noche 19-04 \u00b7 Abs","\u00daltimo de noches. Abs 10\u2032. Descanso real el lunes de d\u00eda.","noche"),
    ("Lun 24/08","Retomas plan","Fin de noches. Vuelves al plan normal (Semana 3 \u00b7 pico), ya con tus 2 n\u00fameros para ajustar.","carrera"),
]
rows=[[Paragraph("D\u00eda",cellwb),Paragraph("Sesi\u00f3n",cellwb),Paragraph("Qu\u00e9 haces",cellwb)]]
sty=[("BACKGROUND",(0,0),(-1,0),AZUL),("BOX",(0,0),(-1,-1),0.6,GRISLN),("INNERGRID",(0,0),(-1,-1),0.4,GRISLN),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5)]
for i,(d,s,det,k) in enumerate(filas,start=1):
    rows.append([Paragraph(d,cellb),Paragraph(s,cellb),Paragraph(det,cell)])
    sty.append(("BACKGROUND",(0,i),(-1,i),KIND[k]))
tt=Table(rows,colWidths=[doc.width*0.15,doc.width*0.24,doc.width*0.61]); tt.setStyle(TableStyle(sty))
story.append(tt)
story.append(Spacer(1,5))

# FUERZA + ANOTA en 2 columnas
fuerza=[
    Paragraph("<b>Noches (vie-dom): modo mantenimiento</b>", ex),
    bullets([
        "El turno + dormir de d\u00eda te hunden el HRV: <b>nada de sesiones duras</b>, ser\u00eda contraproducente.",
        "Mant\u00e9n solo los <b>abdominales (10\u2032)</b> y protege el sue\u00f1o diurno y la comida.",
        "Fuerza cuerpo <b>opcional</b> (si un d\u00eda en Asturias sobra energ\u00eda): flexiones + sentadillas, 3 superseries.",
    ]),
]
anota=[
    Paragraph("<b>Anota (ll\u00e9vatelo apuntado)</b>", ex),
    Paragraph("Test 1 km: fecha ______ tiempo ______  <font color='#54606e'>(objetivo \u2264 4\u203250\u2033)</font>", ex),
    Spacer(1,3),
    Paragraph("Abs baseline legal: fecha ______ n\u00ba ______  <font color='#54606e'>(objetivo 35)</font>", ex),
    Spacer(1,3),
    Paragraph("Peso / notas: __________________________", ex),
]
_cw=doc.width*0.5-2
two=Table([[box(fuerza, bg=AZULBG, border=AZUL2, width=_cw), box(anota, bg=VERDEBG, border=VERDE, width=_cw)]],
          colWidths=[_cw, _cw])
two.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),
    ("RIGHTPADDING",(0,0),(0,0),4),("LEFTPADDING",(1,0),(1,0),4),("RIGHTPADDING",(1,0),(-1,-1),0)]))
story.append(two)

doc.build(story)
print("OK ->", OUT)
