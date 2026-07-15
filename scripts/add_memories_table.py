"""
Migración: crea tabla memories para RAG.
Idempotente — se puede volver a ejecutar sin romper nada.
No requiere extensiones externas: usa FLOAT4[] para embeddings.
Cuando pgvector esté instalado, ejecutar upgrade_to_pgvector.py.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import get_connection


def run():
    conn = get_connection()
    cur = conn.cursor()

    print("Creando tabla memories...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id          SERIAL PRIMARY KEY,
            content     TEXT NOT NULL,
            embedding   FLOAT4[],
            source      TEXT DEFAULT 'conversation',
            metadata    JSONB DEFAULT '{}',
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Índice FTS para búsqueda híbrida (primer filtro antes de coseno)
    print("Creando índice full-text search...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS memories_fts_idx
        ON memories
        USING gin(to_tsvector('spanish', content))
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Tabla memories lista.")


if __name__ == "__main__":
    run()
