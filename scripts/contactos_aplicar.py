"""Carga en Postgres el Excel de contactos ya revisado (data/contactos_revision.xlsx).

Decisiones que respeta: Acción = Borrar / Fusionar (+ 'Fusionar con ID'), hoja 'Posibles duplicados'
con ¿Fusionar? = Sí, y cualquier celda que hayas editado en 'Personas'. Filas sin ID = borradas.
Uso:
  python scripts/contactos_aplicar.py              simulacion (no escribe nada)
  python scripts/contactos_aplicar.py --aplicar    crea las tablas y carga (si estan vacias)
  python scripts/contactos_aplicar.py --aplicar --reemplazar   borra lo anterior y vuelve a cargar
Solo imprime recuentos, nunca nombres ni numeros.
"""
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contactos_importar import norm_email, norm_phone, norm_text  # noqa: E402

EXCEL = Path(__file__).resolve().parent.parent / "data" / "contactos_revision.xlsx"

SCHEMA = """
CREATE TABLE IF NOT EXISTS contactos (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    apodo TEXT,
    empresa TEXT,
    notas TEXT,
    busqueda TEXT NOT NULL,
    origen TEXT,
    creado TIMESTAMPTZ DEFAULT now(),
    actualizado TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS canales (
    id SERIAL PRIMARY KEY,
    contacto_id INTEGER NOT NULL REFERENCES contactos(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('correo', 'telefono', 'telegram', 'instagram', 'whatsapp')),
    valor TEXT NOT NULL,
    valor_norm TEXT NOT NULL,
    preferido BOOLEAN DEFAULT false,
    origen TEXT,
    ultimo_contacto TIMESTAMPTZ,
    UNIQUE (tipo, valor_norm)
);
CREATE INDEX IF NOT EXISTS canales_contacto_idx ON canales (contacto_id);
"""


def clean(v) -> str:
    return str(v).strip() if v not in (None, "") else ""


def read_excel():
    wb = load_workbook(EXCEL)
    people = {}
    for r in wb["Personas"].iter_rows(min_row=2, values_only=True):
        if r[0] in (None, ""):
            continue
        pid = int(r[0])
        channels = [("correo", clean(v)) for v in r[3:6] if clean(v)] + [("telefono", clean(v)) for v in r[6:9] if clean(v)]
        channels += [("telegram", clean(v)) for v in clean(r[9]).split(",") if clean(v)]
        channels += [("instagram", clean(v)) for v in clean(r[10]).split(",") if clean(v)]
        people[pid] = {"id": pid, "name": clean(r[1]), "nick": clean(r[2]), "org": clean(r[11]), "notes": clean(r[12]),
                       "origin": clean(r[13]), "action": clean(r[15]) or "Mantener", "merge_into": clean(r[16]),
                       "channels": channels}
    overflow = 0
    for r in wb["Canales"].iter_rows(min_row=2, values_only=True):
        if r[0] in (None, "") or int(r[0]) not in people:
            continue
        p = people[int(r[0])]
        kind = {"teléfono": "telefono"}.get(clean(r[2]), clean(r[2]))
        full = sum(1 for t, _ in p["channels"] if t == kind) >= 3
        if full and (kind, clean(r[3])) not in p["channels"]:
            p["channels"].append((kind, clean(r[3])))
            overflow += 1
    pairs = [(int(a), int(c)) for a, _, c, _, _, f in wb["Posibles duplicados"].iter_rows(min_row=2, values_only=True)
             if a not in (None, "") and clean(f).lower() in ("sí", "si")]
    return people, pairs, overflow


dropped_ids: list[int] = []


def resolve(people, pairs):
    parent = {pid: pid for pid in people}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    unions = 0
    for a, b in pairs:
        if a in people and b in people and find(a) != find(b):
            parent[find(a)] = find(b)
            unions += 1
    for p in people.values():
        if p["action"].lower() == "fusionar" and p["merge_into"].isdigit() and int(p["merge_into"]) in people:
            if find(p["id"]) != find(int(p["merge_into"])):
                parent[find(p["id"])] = find(int(p["merge_into"]))
                unions += 1
    groups = defaultdict(list)
    for pid, p in people.items():
        if p["action"].lower() != "borrar":
            groups[find(pid)].append(p)
    final, dropped = [], 0
    dropped_ids.clear()
    for members in groups.values():
        names = sorted({m["name"] for m in members if m["name"]}, key=len, reverse=True)
        channels = {}
        for m in members:
            for kind, raw in m["channels"]:
                norm = norm_phone(raw) if kind in ("telefono", "whatsapp") else norm_email(raw) if kind == "correo" else raw.strip().lower().lstrip("@")
                if norm and (kind, norm) not in channels:
                    channels[(kind, norm)] = raw if kind != "telefono" else norm
        if not names:
            dropped += 1
            dropped_ids.extend(m["id"] for m in members)
            continue
        final.append({"name": names[0], "nick": next((m["nick"] for m in members if m["nick"]), ""),
                      "org": next((m["org"] for m in members if m["org"]), ""),
                      "notes": " | ".join(dict.fromkeys(m["notes"] for m in members if m["notes"])),
                      "origin": ", ".join(dict.fromkeys(m["origin"] for m in members if m["origin"])),
                      "channels": [(k, v, n) for (k, n), v in channels.items()]})
    return final, unions, dropped


def main():
    people, pairs, overflow = read_excel()
    deleted = sum(1 for p in people.values() if p["action"].lower() == "borrar")
    final, unions, dropped = resolve(people, pairs)
    kinds = defaultdict(int)
    for p in final:
        for k, _, _ in p["channels"]:
            kinds[k] += 1
    print(f"Excel: {len(people)} personas con ID | borradas: {deleted} | fusiones aplicadas: {unions} | sin nombre (descartadas): {dropped}")
    print(f"Resultado: {len(final)} contactos, {sum(kinds.values())} canales {dict(kinds)} | canales extra recuperados de 'Canales': {overflow}")
    shared = defaultdict(list)
    for i, p in enumerate(final):
        for k, _, n in p["channels"]:
            shared[(k, n)].append(i)
    repeated = {key: idx for key, idx in shared.items() if len(idx) > 1}
    print(f"Descartados por no tener nombre (IDs del Excel): {sorted(dropped_ids)}")
    print(f"Canales repetidos entre 2+ contactos distintos: {len(repeated)}")
    if "--aplicar" not in sys.argv:
        print("SIMULACION: no se ha escrito nada. Usa --aplicar para cargar.")
        return

    from core.db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SCHEMA)
    cur.execute("SELECT count(*) FROM contactos")
    existing = cur.fetchone()[0]
    if existing and "--reemplazar" not in sys.argv:
        conn.rollback()
        sys.exit(f"Ya hay {existing} contactos. Usa --reemplazar para borrarlos y recargar.")
    if existing:
        cur.execute("TRUNCATE canales, contactos RESTART IDENTITY CASCADE")
    skipped = 0
    for p in final:
        cur.execute("INSERT INTO contactos (nombre, apodo, empresa, notas, busqueda, origen) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                    (p["name"], p["nick"] or None, p["org"] or None, p["notes"] or None,
                     norm_text(f'{p["name"]} {p["nick"]} {p["org"]}'), p["origin"] or None))
        cid = cur.fetchone()[0]
        for kind, raw, norm in p["channels"]:
            cur.execute("INSERT INTO canales (contacto_id, tipo, valor, valor_norm, origen) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tipo, valor_norm) DO NOTHING",
                        (cid, kind, raw, norm, p["origin"] or None))
            skipped += cur.rowcount == 0
    conn.commit()
    cur.execute("SELECT (SELECT count(*) FROM contactos), (SELECT count(*) FROM canales)")
    print("Cargado en Postgres: contactos, canales =", cur.fetchone(), "| canales repetidos omitidos:", skipped)
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
