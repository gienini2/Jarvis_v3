"""Prepara frases de MASSIVE (Amazon, es-ES, CC BY 4.0) para el enrutador de temas.

Entrada : data/massive_es/massive-{train,validation,test}.parquet
          (https://huggingface.co/datasets/AmazonScience/massive, revision f039ed54a45079b32092f4af7ff2f9584e09403c)
Salida  : data/domain_examples_massive.json  ejemplos extra por tema (train + validation)
          data/massive_cases.json            casos de prueba (partición test, no usados como ejemplos)
Uso     : python scripts/import_massive.py [--cases] [--extra] [--per-domain=N]
"""
import collections
import json
import random
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "massive_es"
EXTRA_OUT = ROOT / "data" / "domain_examples_massive.json"
CASES_OUT = ROOT / "data" / "massive_cases.json"

# id numerico de la columna 'intent' -> tema. Verificado mirando ejemplos de cada id.
INTENT_TO_DOMAIN = {
    13: "tiempo",
    32: "calendario", 50: "calendario", 30: "calendario",
    44: "correo", 33: "correo",
    21: "tareas", 59: "tareas", 53: "tareas",
    5: "charla", 25: "charla",
    22: "web", 49: "web", 26: "web", 42: "web", 11: "web", 19: "web", 55: "web", 9: "web",
}
PER_DOMAIN = {"tiempo": 40, "calendario": 40, "correo": 40, "tareas": 40, "charla": 40, "web": 40}   # medido: mas ejemplos dañan a los temas sin MASSIVE
CASES_PER_DOMAIN = 40

WAKE_WORDS = re.compile(r"\b(olly|alexa|siri|(hey|oye|hola|ok) google)\b", re.IGNORECASE)


def clean(utt: str) -> str:
    return re.sub(r"\s+", " ", WAKE_WORDS.sub(" ", utt)).strip()


def load(partitions: list[str]) -> dict[str, list[tuple[int, str]]]:
    by_domain = collections.defaultdict(list)
    for part in partitions:
        rows = pq.read_table(SRC / f"massive-{part}.parquet", columns=["intent", "utt"]).to_pylist()
        for row in rows:
            domain = INTENT_TO_DOMAIN.get(int(row["intent"]))
            text = clean(row["utt"])
            if domain and 2 <= len(text.split()) <= 14:
                by_domain[domain].append((int(row["intent"]), text))
    return by_domain


def stratified(items: list[tuple[int, str]], limit: int, rng: random.Random) -> list[str]:
    buckets = collections.defaultdict(list)
    seen = set()
    for intent, text in items:
        key = text.lower()
        if key not in seen:
            seen.add(key)
            buckets[intent].append(text)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    out = []
    while len(out) < limit and any(buckets.values()):
        for bucket in buckets.values():
            if bucket and len(out) < limit:
                out.append(bucket.pop())
    return out


def main():
    rng = random.Random(42)
    want_cases = "--cases" in sys.argv or len(sys.argv) == 1
    want_extra = "--extra" in sys.argv or len(sys.argv) == 1

    train = load(["train", "validation"])
    train_texts = {t.lower() for items in train.values() for _, t in items}

    if want_cases:
        test = load(["test"])
        cases = []
        for domain, items in sorted(test.items()):
            fresh = [(i, t) for i, t in items if t.lower() not in train_texts]
            cases += [{"text": t, "expect": [domain]} for t in stratified(fresh, CASES_PER_DOMAIN, rng)]
        CASES_OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"casos de prueba: {len(cases)} -> {CASES_OUT.name}", dict(collections.Counter(c["expect"][0] for c in cases)))

    if want_extra:
        cap = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--per-domain=")), None)
        extra = {d: stratified(train[d], min(PER_DOMAIN[d], cap) if cap else PER_DOMAIN[d], rng) for d in PER_DOMAIN}
        EXTRA_OUT.write_text(json.dumps(extra, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"ejemplos extra: {sum(map(len, extra.values()))} -> {EXTRA_OUT.name}", {d: len(v) for d, v in extra.items()})


if __name__ == "__main__":
    main()
