"""Une contactos de varias exportaciones en un Excel de revision (data/contactos_revision.xlsx).

Fuentes admitidas (se detectan por extension/contenido):
  .vcf   tarjetas vCard (iPhone/iCloud, Android, WhatsApp)
  .csv   exportacion CSV de Google Contactos
  .json  exportacion de Telegram Desktop (contacts.list)
Uso: python scripts/contactos_importar.py ARCHIVO [ARCHIVO ...] [--out ruta.xlsx]
Solo agrupa de forma automatica lo que comparte telefono o correo; los parecidos por nombre
van a la hoja 'Posibles duplicados' para decidir tu. Nada se escribe en la base de datos.
"""
import csv
import difflib
import json
import quopri
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "contactos_revision.xlsx"


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def norm_phone(raw: str) -> str:
    s = re.sub(r"[^\d+]", "", raw or "")
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        return s if len(s) >= 9 else ""
    if len(s) == 9 and s[0] in "6789":
        return "+34" + s
    if len(s) == 11 and s.startswith("34"):
        return "+" + s
    return s if len(s) >= 6 else ""


def norm_email(raw: str) -> str:
    s = (raw or "").strip().lower()
    return s if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s) else ""


def record(name="", emails=(), phones=(), telegram=(), instagram=(), org="", notes="", source=""):
    return {"name": re.sub(r"\s+", " ", name or "").strip(), "emails": [e for e in map(norm_email, emails) if e],
            "phones": [p for p in map(norm_phone, phones) if p], "telegram": list(telegram),
            "instagram": list(instagram), "org": org or "", "notes": notes or "", "source": source}


def parse_vcf(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"=\r?\n", "", text)
    text = re.sub(r"\r?\n[ \t]", "", text)
    out = []
    for card in re.findall(r"BEGIN:VCARD(.*?)END:VCARD", text, flags=re.S | re.I):
        fields = defaultdict(list)
        for line in card.strip().splitlines():
            if ":" not in line:
                continue
            head, value = line.split(":", 1)
            key = head.split(";")[0].split(".")[-1].upper()
            if "QUOTED-PRINTABLE" in head.upper():
                value = quopri.decodestring(value.encode()).decode("utf-8", errors="replace")
            fields[key].append(value.strip())
        name = (fields.get("FN") or [""])[0]
        if not name and fields.get("N"):
            parts = fields["N"][0].split(";")
            name = " ".join(p for p in (parts[1:2] + parts[0:1]) if p)
        insta = [u for u in fields.get("URL", []) + fields.get("X-SOCIALPROFILE", []) if "instagram" in u.lower()]
        out.append(record(name, fields.get("EMAIL", []), fields.get("TEL", []), instagram=insta,
                          org=(fields.get("ORG") or [""])[0].replace(";", " "), notes=" ".join(fields.get("NOTE", [])),
                          source=path.name))
    return out


def parse_google_csv(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            low = {(k or "").lower(): (v or "").strip() for k, v in row.items()}
            name = low.get("name") or " ".join(x for x in (low.get("first name") or low.get("given name"),
                                                           low.get("last name") or low.get("family name")) if x)
            name = name or low.get("nombre", "")
            split = lambda cols: [p.strip() for k, v in low.items() if v and any(c in k for c in cols) for p in v.split(":::")]
            out.append(record(name, split(["mail", "correo"]), split(["phone", "tel", "móvil", "movil"]),
                              org=low.get("organization name") or low.get("organization 1 - name") or low.get("empresa", ""),
                              notes=low.get("notes") or low.get("notas", ""), source=path.name))
    return out


def parse_telegram_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    contacts = (data.get("contacts") or {}).get("list") or []
    return [record(f"{c.get('first_name', '')} {c.get('last_name', '')}", phones=[c.get("phone_number", "")],
                   telegram=[norm_phone(c.get("phone_number", ""))], source=path.name) for c in contacts]


def load(paths: list[Path]) -> list[dict]:
    records = []
    for path in paths:
        suffix = path.suffix.lower()
        if suffix == ".vcf":
            records += parse_vcf(path)
        elif suffix == ".csv":
            records += parse_google_csv(path)
        elif suffix == ".json":
            records += parse_telegram_json(path)
        else:
            print(f"  ignorado (formato no admitido): {path.name}")
    return records


class Groups:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def cluster(records: list[dict]) -> list[list[int]]:
    groups, seen = Groups(len(records)), {}
    for i, rec in enumerate(records):
        for key in [("p", p) for p in rec["phones"]] + [("e", e) for e in rec["emails"]]:
            if key in seen:
                groups.union(i, seen[key])
            else:
                seen[key] = i
    members = defaultdict(list)
    for i in range(len(records)):
        members[groups.find(i)].append(i)
    return sorted(members.values(), key=lambda m: m[0])


def build_people(records, clusters):
    people = []
    for n, members in enumerate(clusters, 1):
        recs = [records[i] for i in members]
        by_norm = {}
        for r in recs:
            if r["name"] and norm_text(r["name"]) not in by_norm:
                by_norm[norm_text(r["name"])] = r["name"]
        names = sorted(by_norm.values(), key=len, reverse=True)
        uniq = lambda key: list(dict.fromkeys(v for r in recs for v in r[key] if v))
        person = {"id": n, "name": names[0] if names else "", "other_names": [x for x in names[1:] if norm_text(x) != norm_text(names[0])],
                  "emails": uniq("emails"), "phones": uniq("phones"), "telegram": uniq("telegram"), "instagram": uniq("instagram"),
                  "org": next((r["org"] for r in recs if r["org"]), ""), "notes": " | ".join(dict.fromkeys(r["notes"] for r in recs if r["notes"])),
                  "sources": list(dict.fromkeys(r["source"] for r in recs)), "n_records": len(recs)}
        flags = []
        if not person["name"]:
            flags.append("sin nombre")
        if not person["emails"] and not person["phones"]:
            flags.append("sin telefono ni correo")
        if person["other_names"]:
            flags.append("nombres distintos: " + "; ".join(person["other_names"]))
        if len(person["phones"]) > 3:
            flags.append("muchos telefonos")
        if any(not p.startswith("+") for p in person["phones"]):
            flags.append("telefono sin prefijo")
        person["flags"] = flags
        people.append(person)
    return people


def possible_duplicates(people):
    blocks = defaultdict(list)
    for p in people:
        tokens = norm_text(p["name"]).split()
        if tokens:
            blocks[tokens[0][:4]].append(p)
            if len(tokens) > 1:
                blocks[tokens[-1][:4]].append(p)
    pairs = {}
    for block in blocks.values():
        for i, a in enumerate(block):
            for b in block[i + 1:]:
                if a["id"] == b["id"]:
                    continue
                na, nb = norm_text(a["name"]), norm_text(b["name"])
                if na == nb:
                    reason = "mismo nombre"
                elif set(na.split()) == set(nb.split()):
                    reason = "mismas palabras en otro orden"
                elif difflib.SequenceMatcher(None, na, nb).ratio() >= 0.88:
                    reason = "nombre muy parecido"
                else:
                    continue
                pairs[tuple(sorted((a["id"], b["id"])))] = (a, b, reason)
    return [pairs[k] for k in sorted(pairs)]


def write_excel(people, dups, out: Path):
    wb = Workbook()
    font, head = Font(name="Arial", size=10), PatternFill("solid", start_color="1F3A5F")
    warn = PatternFill("solid", start_color="FDE9D9")

    def sheet(ws, headers, rows, widths, warn_col=None):
        ws.append(headers)
        for cell in ws[1]:
            cell.font, cell.fill = Font(name="Arial", size=10, bold=True, color="FFFFFF"), head
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        for row in rows:
            ws.append(row)
        for r in ws.iter_rows(min_row=2):
            for cell in r:
                cell.font, cell.alignment = font, Alignment(vertical="top", wrap_text=True)
            if warn_col is not None and r[warn_col].value:
                for cell in r:
                    cell.fill = warn
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    ws = wb.active
    ws.title = "Personas"
    third = lambda lst, i: lst[i] if len(lst) > i else ""
    rows = [[p["id"], p["name"], "", third(p["emails"], 0), third(p["emails"], 1), third(p["emails"], 2),
             third(p["phones"], 0), third(p["phones"], 1), third(p["phones"], 2), ", ".join(p["telegram"]),
             ", ".join(p["instagram"]), p["org"], p["notes"], ", ".join(p["sources"]), "; ".join(p["flags"]),
             "Mantener", ""] for p in people]
    sheet(ws, ["ID", "Nombre", "Apodo", "Correo 1", "Correo 2", "Correo 3", "Teléfono 1", "Teléfono 2", "Teléfono 3",
               "Telegram", "Instagram", "Empresa", "Notas", "Origen", "Avisos automáticos", "Acción", "Fusionar con ID"],
          rows, [6, 26, 14, 28, 24, 24, 16, 16, 16, 18, 22, 20, 30, 22, 34, 12, 12], warn_col=14)
    if people:
        action = DataValidation(type="list", formula1='"Mantener,Fusionar,Borrar"', allow_blank=False)
        ws.add_data_validation(action)
        action.add(f"P2:P{len(people) + 1}")

    ws2 = wb.create_sheet("Canales")
    chan = []
    for p in people:
        chan += [[p["id"], p["name"], "correo", v] for v in p["emails"]]
        chan += [[p["id"], p["name"], "teléfono", v] for v in p["phones"]]
        chan += [[p["id"], p["name"], "telegram", v] for v in p["telegram"]]
        chan += [[p["id"], p["name"], "instagram", v] for v in p["instagram"]]
    sheet(ws2, ["ID persona", "Nombre", "Tipo", "Valor"], chan, [10, 28, 12, 40])

    ws3 = wb.create_sheet("Posibles duplicados")
    drows = [[a["id"], a["name"], b["id"], b["name"], reason, "No"] for a, b, reason in dups]
    sheet(ws3, ["ID A", "Nombre A", "ID B", "Nombre B", "Motivo", "¿Fusionar? (Sí/No)"], drows, [8, 28, 8, 28, 28, 18])
    if dups:
        merge = DataValidation(type="list", formula1='"Sí,No"', allow_blank=False)
        ws3.add_data_validation(merge)
        merge.add(f"F2:F{len(dups) + 1}")

    ws4 = wb.create_sheet("Cómo revisar")
    for line in ["Cómo revisar los contactos", "",
                 "1. 'Personas' tiene una fila por persona. Ya se han unido las que compartían teléfono o correo.",
                 "2. Las filas naranjas tienen avisos (sin nombre, teléfonos sin prefijo, nombres distintos...).",
                 "3. 'Posibles duplicados' son parecidos solo por nombre: pon Sí donde sea la misma persona.",
                 "4. En 'Personas', Acción = Borrar para quitar una fila; Fusionar + 'Fusionar con ID' para unirla a otra.",
                 "5. 'Canales' es el detalle: cada teléfono/correo/Telegram/Instagram en su propia fila.",
                 "6. Nada se ha guardado todavía en la base de datos de Jarvis: el siguiente paso lee este Excel."]:
        ws4.append([line])
    ws4.column_dimensions["A"].width = 110
    ws4["A1"].font = Font(name="Arial", size=12, bold=True)
    out.parent.mkdir(exist_ok=True)
    wb.save(out)


def main():
    args = sys.argv[1:]
    out = DEFAULT_OUT
    if "--out" in args:
        i = args.index("--out")
        out = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    paths = [Path(a) for a in args]
    if not paths:
        sys.exit(__doc__)
    records = load(paths)
    clusters = cluster(records)
    people = build_people(records, clusters)
    dups = possible_duplicates(people)
    write_excel(people, dups, out)
    flagged = sum(1 for p in people if p["flags"])
    print(f"{len(records)} registros -> {len(people)} personas ({len(records) - len(people)} unidos por telefono/correo)")
    print(f"{flagged} con avisos | {len(dups)} posibles duplicados por nombre | Excel: {out}")


if __name__ == "__main__":
    main()
