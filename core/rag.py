"""
RAG: embed con nomic-embed-text, similitud coseno via pgvector nativo en Postgres.

(05/07/2026) Antes calculaba la similitud coseno en Python contra un float4[]
traido entero a memoria (comentario original: "Escala bien hasta ~10K memorias").
Decision de Juan Pablo: migrar a pgvector para que el calculo lo haga Postgres
(operador <=>, indice HNSW) en vez de traer cientos de vectores y hacer el
bucle aqui. REQUIERE haber ejecutado scripts/migrate_pgvector.sql contra la
DB ANTES de desplegar este archivo -- si la columna "embedding" todavia es
float4[] en vez de vector(768), las queries de abajo fallan con un error de
tipo de Postgres. Ver scripts/migrate_pgvector.sql para el orden de pasos.
"""
import json
import logging
import time
import requests
from functools import lru_cache

from config.settings import settings
from core.db import get_connection

log = logging.getLogger("jarvis.rag")

EMBED_MODEL = "nomic-embed-text"
MIN_SIMILARITY = 0.35


@lru_cache(maxsize=64)
def _embed_cached(text: str) -> tuple[float, ...] | None:
    """Caché LRU en memoria. Evita re-embeddings del mismo texto en la misma sesión."""
    try:
        t0 = time.perf_counter()
        r = requests.post(
            settings.OLLAMA_EMBED_URL,
            json={
                "model": EMBED_MODEL,
                "input": text,
                "keep_alive": "1h",   # mantiene el modelo cargado entre llamadas
            },
            timeout=30,
        )
        r.raise_for_status()
        elapsed = time.perf_counter() - t0
        if elapsed > 8:
            log.warning(f"embed tardó {elapsed:.1f}s (Ollama ocupado?)")
        return tuple(r.json()["embeddings"][0])
    except Exception as e:
        log.warning(f"embed failed: {e}")
        return None


def embed(text: str) -> list[float] | None:
    result = _embed_cached(text)
    return list(result) if result is not None else None


def _to_vector_literal(vec: list[float]) -> str:
    """pgvector acepta un literal de texto tipo '[0.1,0.2,...]' para el cast ::vector."""
    return "[" + ",".join(repr(x) for x in vec) + "]"


def store_memory(content: str, source: str = "conversation", metadata: dict | None = None) -> int | None:
    vec = embed(content)
    if vec is None:
        return None

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memories (content, embedding, source, metadata)
        VALUES (%s, %s::vector, %s, %s)
        RETURNING id
        """,
        (content, _to_vector_literal(vec), source, json.dumps(metadata or {})),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return row[0] if row else None


def search_memories(query: str, limit: int = 5) -> list[dict]:
    """
    FTS como pre-filtro (igual que antes) y, dentro de ese subconjunto, orden
    por distancia coseno pgvector (operador <=>, 0 = identico). Si el FTS no
    trae suficientes candidatos (query sin palabras clave claras), se
    completa con los mas recientes -- misma logica de antes, pero el ORDER BY
    y el calculo de similitud los hace Postgres, no un bucle en Python.
    """
    query_vec = embed(query)
    if query_vec is None:
        return []
    vec_literal = _to_vector_literal(query_vec)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, content, source, 1 - (embedding <=> %s::vector) AS similarity
        FROM memories
        WHERE embedding IS NOT NULL
          AND to_tsvector('spanish', content) @@ plainto_tsquery('spanish', %s)
        ORDER BY embedding <=> %s::vector
        LIMIT 400
        """,
        (vec_literal, query, vec_literal),
    )
    rows = cur.fetchall()

    if len(rows) < limit:
        # Complementar con los más recientes (por similitud) que no estén ya en el resultado
        seen_ids = {r[0] for r in rows}
        cur.execute(
            """
            SELECT id, content, source, 1 - (embedding <=> %s::vector) AS similarity
            FROM memories
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT 400
            """,
            (vec_literal, vec_literal),
        )
        for row in cur.fetchall():
            if row[0] not in seen_ids:
                rows.append(row)

    cur.close()
    conn.close()

    scored = [
        {"id": r[0], "content": r[1], "source": r[2], "similarity": r[3]}
        for r in rows if r[3] is not None and r[3] >= MIN_SIMILARITY
    ]
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]
