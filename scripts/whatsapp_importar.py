"""Importa chats de WhatsApp EXPORTADOS por el usuario a Postgres (tabla mensajes_chat).

Admite .txt (Android o iPhone) y .zip (iPhone, con _chat.txt dentro), sueltos o en una carpeta.
Solo chats de 2 personas (los grupos se omiten). Cada chat se asigna a un contacto de la agenda por el
nombre del archivo; los que no se puedan asignar solos van a data/whatsapp_sin_asignar.csv, y puedes
resolverlos en data/whatsapp_mapa.csv (columnas: chat,contacto_id). Es idempotente: reimportar no duplica.
Uso: python scripts/whatsapp_importar.py RUTA [RUTA ...] [--yo "Tu nombre en WhatsApp"] [--simular]
Solo imprime recuentos, nunca nombres ni mensajes.
"""
import csv
import difflib
import re
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
UNASSIGNED = ROOT / "data" / "whatsapp_sin_asignar.csv"
MAPPING = ROOT / "data" / "whatsapp_mapa.csv"

SCHEMA = """
CREATE TABLE IF NOT EXISTS mensajes_chat (
    id SERIAL PRIMARY KEY,
    contacto_id INTEGER NOT NULL REFERENCES contactos(id) ON DELETE CASCADE,
    canal TEXT NOT NULL DEFAULT 'whatsapp',
    fecha TIMESTAMP NOT NULL,
    de_mi BOOLEAN NOT NULL,
    texto TEXT NOT NULL,
    es_multimedia BOOLEAN NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX IF NOT EXISTS mensajes_chat_unico ON mensajes_chat (contacto_id, canal, fecha, de_mi, (md5(texto)));
CREATE INDEX IF NOT EXISTS mensajes_chat_contacto_fecha ON mensajes_chat (contacto_id, fecha DESC);
"""

INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬  ﻿"), " ")
START = re.compile(
    r"^(?:\[(?P<d1>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<t1>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<p1>[ap])?\.?\s?m?\.?\]\s*"
    r"|(?P<d2>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<t2>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<p2>[ap])?\.?\s?m?\.?\s+-\s+)(?P<rest>.*)$",
    re.IGNORECASE,
)
MEDIA = re.compile(r"^<[^>]{3,45}>$|\((archivo adjunto|arxiu adjunt|fitxer adjunt|file attached)\)\s*$|(imagen|audio|v[ií]deo|sticker|gif|documento|imatge|[àa]udio) omit[ií]d[oa]s?$", re.IGNORECASE)
TITLE = re.compile(r"(?:Chat de WhatsApp con|Xat de WhatsApp amb|WhatsApp Chat with|WhatsApp Chat -|Conversa de WhatsApp amb)\s+(.+?)\s*$", re.IGNORECASE)


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def parse_when(date_s: str, time_s: str, pm: str | None) -> datetime | None:
    d, m, y = (int(x) for x in date_s.split("/"))
    y += 2000 if y < 100 else 0
    parts = [int(x) for x in time_s.split(":")]
    h, mi, s = parts[0], parts[1], parts[2] if len(parts) > 2 else 0
    if pm:
        h = h % 12 + (12 if pm.lower() == "p" else 0)
    try:
        return datetime(y, m, d, h, mi, s)
    except ValueError:
        return None


def parse_chat(text: str) -> list[dict]:
    messages = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.translate(INVISIBLE).strip()
        m = START.match(line)
        if m:
            when = parse_when(m.group("d1") or m.group("d2"), m.group("t1") or m.group("t2"), m.group("p1") or m.group("p2"))
            rest = m.group("rest")
            sender, sep, body = rest.partition(": ")
            if when and sep and 0 < len(sender) <= 60:
                messages.append({"when": when, "sender": sender.strip(), "text": body.strip()})
            else:
                messages.append({"when": when, "sender": None, "text": rest.strip()})
        elif messages and raw.strip():
            messages[-1]["text"] += "\n" + line.strip()
    return [x for x in messages if x["when"] and x["sender"] is not None]


def chat_title(path: Path) -> str:
    stem = path.stem
    m = TITLE.search(stem)
    return (m.group(1) if m else stem).strip()


def read_exports(paths: list[Path]):
    for path in paths:
        files = sorted(p for p in path.rglob("*") if p.suffix.lower() in (".txt", ".zip")) if path.is_dir() else [path]
        for f in files:
            if f.suffix.lower() == ".zip":
                with zipfile.ZipFile(f) as z:
                    names = [n for n in z.namelist() if n.lower().endswith(".txt")]
                    if names:
                        yield chat_title(f), z.read(names[0]).decode("utf-8", errors="replace")
            elif f.suffix.lower() == ".txt":
                yield chat_title(f), f.read_text(encoding="utf-8", errors="replace")


def who_is_me(title: str, senders: set[str], forced: str | None) -> set[str]:
    if forced:
        return {s for s in senders if norm(s) == norm(forced)}
    if len(senders) == 1:
        only = next(iter(senders))
        return set() if difflib.SequenceMatcher(None, norm(title), norm(only)).ratio() >= .6 else {only}
    ranked = sorted(senders, key=lambda s: difflib.SequenceMatcher(None, norm(title), norm(s)).ratio())
    return {ranked[0]}


def load_mapping() -> dict[str, int]:
    if not MAPPING.exists():
        return {}
    with MAPPING.open(encoding="utf-8-sig", newline="") as fh:
        return {norm(r["chat"]): int(r["contacto_id"]) for r in csv.DictReader(fh) if (r.get("contacto_id") or "").strip().isdigit()}


def assign_contact(title: str, mapping: dict[str, int]):
    from core.contacts import find
    if norm(title) in mapping:
        return mapping[norm(title)], []
    found = find(title)
    strong = [f for f in found if f["coincidencia"] >= .85]
    if strong and (len(strong) == 1 or strong[0]["coincidencia"] - strong[1]["coincidencia"] >= .1):
        return strong[0]["id"], []
    return None, [f["id"] for f in found[:3]]


def main():
    args = sys.argv[1:]
    forced_me = args[args.index("--yo") + 1] if "--yo" in args else None
    simulate = "--simular" in args
    paths = [Path(a) for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--yo")]
    if not paths:
        sys.exit(__doc__)

    from core.db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    if not simulate:
        cur.execute(SCHEMA)
        conn.commit()
    mapping = load_mapping()
    stats = {"chats": 0, "grupos": 0, "sin_asignar": 0, "mensajes": 0, "nuevos": 0, "multimedia": 0}
    unassigned = []
    for title, text in read_exports(paths):
        stats["chats"] += 1
        messages = parse_chat(text)
        senders = {m["sender"] for m in messages}
        if len(senders) > 2 or not messages:
            stats["grupos"] += 1
            continue
        contact_id, candidates = assign_contact(title, mapping)
        if contact_id is None:
            stats["sin_asignar"] += 1
            unassigned.append((title, ",".join(map(str, candidates))))
            continue
        me = who_is_me(title, senders, forced_me)
        rows = [(contact_id, "whatsapp", m["when"], m["sender"] in me, m["text"], bool(MEDIA.search(m["text"]))) for m in messages]
        stats["mensajes"] += len(rows)
        stats["multimedia"] += sum(1 for r in rows if r[5])
        if simulate:
            continue
        before = None
        cur.execute("SELECT count(*) FROM mensajes_chat WHERE contacto_id = %s", (contact_id,))
        before = cur.fetchone()[0]
        cur.executemany("INSERT INTO mensajes_chat (contacto_id, canal, fecha, de_mi, texto, es_multimedia) VALUES (%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (contacto_id, canal, fecha, de_mi, (md5(texto))) DO NOTHING", rows)
        cur.execute("SELECT count(*) FROM mensajes_chat WHERE contacto_id = %s", (contact_id,))
        stats["nuevos"] += cur.fetchone()[0] - before
        conn.commit()
    if unassigned:
        UNASSIGNED.parent.mkdir(exist_ok=True)
        with UNASSIGNED.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["chat", "contacto_id", "candidatos (ids)"])
            writer.writerows([(t, "", c) for t, c in unassigned])
    cur.close()
    conn.close()
    print(("SIMULACION " if simulate else "") + f"chats leidos: {stats['chats']} | grupos omitidos: {stats['grupos']} | sin asignar: {stats['sin_asignar']}"
          f" | mensajes: {stats['mensajes']} (multimedia {stats['multimedia']}) | nuevos en BD: {stats['nuevos']}")
    if unassigned:
        print(f"Asigna los chats sin contacto en {MAPPING.name} (copia {UNASSIGNED.name}, rellena contacto_id y renombra).")


if __name__ == "__main__":
    main()
