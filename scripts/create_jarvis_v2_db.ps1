# scripts/create_jarvis_v2_db.ps1
# Crea la base de datos "jarvis_v2" en Postgres y le copia todo el contenido
# de la DB actual "jarvis" -- REQUIERE superusuario de Postgres (normalmente
# el rol "postgres"). No puedo ejecutar esto por ti: no tengo conexion a tu
# Postgres local desde esta sesion, solo acceso a los archivos del proyecto.
#
# OJO: "jarvis_v2" (esta DB) NO tiene nada que ver con la carpeta jarvis_v2/
# de ingesta que ya existe en tu disco -- coincide el nombre, son cosas distintas.
#
# ORDEN RECOMENDADO:
#   1. Ejecuta primero scripts/migrate_pgvector.sql contra "jarvis" (para que
#      la columna embedding ya sea vector(768) antes de copiar -- si copias
#      antes, el dump igualmente arrastra el tipo float4[] viejo).
#   2. Reinicia JarvisAPI y confirma que el RAG sigue funcionando bien con pgvector.
#   3. Solo entonces ejecuta este script.
#
# USO (PowerShell, con psql/pg_dump en el PATH -- vienen con la instalacion de
# PostgreSQL para Windows, normalmente en C:\Program Files\PostgreSQL\<version>\bin):

# --- 1. Crear la DB nueva, mismo owner que la actual ------------------------
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE jarvis_v2 OWNER jarvis_user;"

# --- 2. Copiar TODO el contenido de 'jarvis' a 'jarvis_v2' ------------------
#     (esquema + datos + la extension vector si ya la instalaste en el paso 1
#      de arriba -- pg_dump incluye el "CREATE EXTENSION IF NOT EXISTS vector"
#      automaticamente si la extension esta en la DB de origen)
pg_dump -U jarvis_user -h 127.0.0.1 jarvis | psql -U jarvis_user -h 127.0.0.1 -d jarvis_v2

# --- 3. Comprobacion rapida: los contadores deben coincidir -----------------
Write-Host "--- Verificando recuento de filas (deben coincidir) ---"
psql -U jarvis_user -h 127.0.0.1 -d jarvis     -c "SELECT count(*) FROM memories;"
psql -U jarvis_user -h 127.0.0.1 -d jarvis_v2  -c "SELECT count(*) FROM memories;"

# --- 4. Pasos manuales que te quedan (no automatizables desde aqui) ---------
Write-Host ""
Write-Host "Siguiente:"
Write-Host "  1. Edita .env y cambia POSTGRES_DB=jarvis  ->  POSTGRES_DB=jarvis_v2"
Write-Host "  2. Reinicia el servicio: sc.exe stop JarvisAPI && sc.exe start JarvisAPI"
Write-Host "  3. Prueba un par de mensajes que toquen memoria/RAG para confirmar que lee de jarvis_v2"
Write-Host "  4. Deja 'jarvis' (la vieja) sin tocar unos dias como respaldo antes de borrarla"
