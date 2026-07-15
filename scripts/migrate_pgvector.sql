-- scripts/migrate_pgvector.sql
-- Migracion de core/rag.py de similitud coseno en Python a pgvector nativo.
--
-- IMPORTANTE -- ORDEN DE EJECUCION (05/07/2026):
--   1. Instalar el binario de pgvector en el servidor Postgres si no esta ya
--      (en Windows: descargar el release precompilado de pgvector para tu
--      version de Postgres, o compilarlo con Visual Studio Build Tools --
--      ver https://github.com/pgvector/pgvector#windows).
--   2. Ejecutar este script COMPLETO contra la DB 'jarvis' (la que usa Jarvis
--      hoy) ANTES de tocar core/rag.py o reiniciar JarvisAPI:
--         psql -U jarvis_user -h 127.0.0.1 -d jarvis -f scripts/migrate_pgvector.sql
--   3. Verificar con la query de comprobacion (mas abajo) que NO hay filas
--      huerfanas antes de continuar.
--   4. Solo entonces: sc.exe stop JarvisAPI && sc.exe start JarvisAPI
--      (core/rag.py ya viene actualizado para usar la columna vector nueva).
--   5. Cuando lleves unos dias sin problemas, borra la columna de respaldo
--      (paso opcional al final de este archivo, comentado a proposito).
--
-- Este script es idempotente en los pasos 1-4 (usa IF NOT EXISTS / WHERE
-- embedding_vec IS NULL) para poder relanzarlo si algo falla a medias.

-- 1. Extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Columna nueva tipo vector (768 dims = nomic-embed-text)
ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding_vec vector(768);

-- 3. Copiar los datos existentes (float4[] -> vector). Solo las filas que
--    todavia no se hayan migrado, para poder relanzar el script sin repetir trabajo.
UPDATE memories
SET embedding_vec = embedding::vector(768)
WHERE embedding IS NOT NULL
  AND embedding_vec IS NULL;

-- 4. COMPROBACION -- ejecutar a mano y confirmar que devuelve 0 antes de seguir:
--    SELECT count(*) FROM memories WHERE embedding IS NOT NULL AND embedding_vec IS NULL;

-- 5. Renombrar: la columna vieja se queda como respaldo (embedding_old_float4),
--    la nueva pasa a llamarse "embedding" para que core/rag.py no tenga que
--    saber el nombre distinto.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'embedding'
          AND data_type = 'ARRAY'
    ) THEN
        ALTER TABLE memories RENAME COLUMN embedding TO embedding_old_float4;
        ALTER TABLE memories RENAME COLUMN embedding_vec TO embedding;
    END IF;
END $$;

-- 6. Indice HNSW para busqueda aproximada por similitud coseno (no necesita
--    tuning de "lists" como ivfflat, funciona bien desde pocas filas hasta millones).
CREATE INDEX IF NOT EXISTS memories_embedding_hnsw_idx
    ON memories USING hnsw (embedding vector_cosine_ops);

-- 7. OPCIONAL -- una vez confirmado que Jarvis funciona bien varios dias con
--    pgvector, borra la columna de respaldo para liberar espacio:
-- ALTER TABLE memories DROP COLUMN embedding_old_float4;
