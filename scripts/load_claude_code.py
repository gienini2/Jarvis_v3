"""Carga data/claude_code_memorias.json en la memoria (source='claude_code'), una
memoria por entrada con incluir=true. Idempotente: borra antes las de ese source."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.db import get_connection
from core.rag import store_memory

SOURCE = "claude_code"
DATA = Path(__file__).resolve().parents[1] / "data" / "claude_code_memorias.json"


def main():
    items = [m for m in json.loads(DATA.read_text(encoding="utf-8"))["memorias"] if m["incluir"]]

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM memories WHERE source = %s", (SOURCE,))
    print(f"borradas {cur.rowcount} memorias previas de '{SOURCE}'")
    conn.commit()
    cur.close()
    conn.close()

    for item in items:
        mid = store_memory(item["contenido"], source=SOURCE, metadata={"id": item["id"], "tema": item["tema"]})
        print(f"{item['id']} -> id={mid}")
        if mid is None:
            sys.exit("embedding fallo (Ollama arrancado?)")
    print(f"cargadas {len(items)} memorias")


if __name__ == "__main__":
    main()
