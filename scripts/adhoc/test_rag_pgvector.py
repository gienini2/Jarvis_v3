"""Prueba post-migracion pgvector: store_memory + search_memories y limpieza."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.rag import store_memory, search_memories
from core.db import get_connection

MARCA = "PRUEBA-PGVECTOR-2026-07-07: el semaforo naranja del Alpha50 reduce la musculacion a 2 series"

mem_id = store_memory(MARCA, source="test_pgvector")
print(f"store_memory -> id={mem_id}")
assert mem_id is not None, "store_memory devolvio None"

resultados = search_memories("semaforo naranja Alpha50 series musculacion", limit=5)
print(f"search_memories -> {len(resultados)} resultados")
for r in resultados:
    print(f"  id={r['id']} sim={r['similarity']:.3f} src={r['source']} :: {r['content'][:70]}")

assert any(r["id"] == mem_id for r in resultados), "la memoria de prueba no aparece en la busqueda"

conn = get_connection()
cur = conn.cursor()
cur.execute("DELETE FROM memories WHERE id = %s", (mem_id,))
conn.commit()
cur.close()
conn.close()
print(f"fila de prueba id={mem_id} borrada. TODO OK")
