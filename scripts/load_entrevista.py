"""Carga data/entrevista_qa.json en la memoria (source='entrevista'), una memoria
por pregunta/respuesta. Idempotente: borra antes las memorias de ese source."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.db import get_connection
from core.rag import store_memory

SOURCE = "entrevista"
DATA = Path(__file__).resolve().parents[1] / "data" / "entrevista_qa.json"


def main():
    qa = json.loads(DATA.read_text(encoding="utf-8"))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM memories WHERE source = %s", (SOURCE,))
    print(f"borradas {cur.rowcount} memorias previas de '{SOURCE}'")
    conn.commit()
    cur.close()
    conn.close()

    for item in qa["preguntas"]:
        versiones = [("respuesta", item["respuesta"])]
        if item.get("variante"):
            versiones.append(("variante", item["variante"]))
        for tipo, texto in versiones:
            content = f"Pregunta de entrevista: {item['pregunta']}\nMi respuesta: {texto}"
            if item.get("nota"):
                content += f"\nEnfoque: {item['nota']}"
            mid = store_memory(content, source=SOURCE, metadata={"id": item["id"], "tipo": tipo})
            print(f"{item['id']} ({tipo}) -> id={mid}")
            if mid is None:
                sys.exit("embedding fallo (Ollama arrancado?)")


if __name__ == "__main__":
    main()
