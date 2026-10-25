"""Indexa tus PROPIOS mensajes de WhatsApp (embeddings locales con Ollama) para que Jarvis imite tu forma de escribir.
Solo mensajes tuyos, de texto, de 12 a 300 caracteres. Es idempotente: solo indexa los que faltan.
Uso: python scripts/indexar_estilo.py [--limite N]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.db import get_connection
from core.rag import _to_vector_literal, embed

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS estilo_mensajes (
    mensaje_id INTEGER PRIMARY KEY REFERENCES mensajes_chat(id) ON DELETE CASCADE,
    embedding vector(768) NOT NULL
);
"""


def main():
    limit = int(sys.argv[sys.argv.index("--limite") + 1]) if "--limite" in sys.argv else None
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SCHEMA)
    conn.commit()
    cur.execute("SELECT m.id, m.texto FROM mensajes_chat m LEFT JOIN estilo_mensajes e ON e.mensaje_id = m.id "
                "WHERE m.de_mi AND NOT m.es_multimedia AND length(m.texto) BETWEEN 12 AND 300 AND e.mensaje_id IS NULL ORDER BY m.fecha DESC")
    pending = cur.fetchall()[:limit]
    print(f"{len(pending)} mensajes por indexar")
    done = 0
    for i, (message_id, text) in enumerate(pending, 1):
        vector = embed(text)
        if vector:
            cur.execute("INSERT INTO estilo_mensajes (mensaje_id, embedding) VALUES (%s, %s::vector) ON CONFLICT DO NOTHING",
                        (message_id, _to_vector_literal(vector)))
            done += 1
        if i % 200 == 0:
            conn.commit()
            print(f"  {i}/{len(pending)}", flush=True)
    conn.commit()
    print(f"Indexados {done} mensajes tuyos")


if __name__ == "__main__":
    main()
