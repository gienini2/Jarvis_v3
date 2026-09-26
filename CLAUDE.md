# Jarvis — CLAUDE.md

> Fuente de verdad del proyecto para agentes y para Juan Pablo.
> Última revisión: 2026-08-25 (auditoría completa de estado).
> El mapa visual vivo del sistema está en `Jarvis/jarvis_dashboard.html` (ábrelo en el navegador).

## Qué es esto
Asistente de IA personal (tipo Jarvis) para Juan Pablo (Juanpa). Cerebro en PC
local Windows (FastAPI + GPU), accesible desde chat local, Telegram (relay en el
servidor Figaro) y una API OpenAI-compatible. Es **monousuario**.

## Cómo razona: cascada de LLMs (¡esto es lo que cambió respecto a docs viejos!)
NO es "Ollama local con fallback a Anthropic". La selección de modelo es
**config-driven** y multi-proveedor:

- **Configuración**: `config/providers.json` (lista de proveedores + modelos con
  roles, prioridad y capacidades — es EL json de datos de los modelos). El router
  `core/llm_router.py` puntúa por **potencia + disponibilidad**:
  `prioridad_proveedor + prioridad_modelo + bonus_capacidad + ajuste_disponibilidad`,
  y filtra por rol, tools, visión, contexto y salud (online) del proveedor.
- **Ponderación de disponibilidad** (bloque `scoring` en `providers.json`, tunable):
  `core/llm_health.py` mide en vivo latencia y una penalización blanda que sube con
  cada 429/error y **decae con cada respuesta buena**. Efecto: un modelo potente
  pero que raciona (Groq free tier da 429) baja y deja pasar a uno más disponible,
  y se recupera solo al volver a responder. `router.debug()` muestra el desglose
  `potencia + disponibilidad`.
- **Filosofía**: el modelo más potente y efectivo primero, y se va bajando en
  cascada hasta acabar en **local cuando no hay internet**. El router lo consigue
  con `prioridad_proveedor`: **Groq (100) → NVIDIA NIM (90) → Ollama local (50)**.
  Kimi/Moonshot (92) está implementado pero `enabled: false`.
- **Groq** = backend principal (cloud, rápido por LPU). Modelos vivos:
  `openai/gpt-oss-120b` (general/tools/reasoning), `openai/gpt-oss-20b`,
  `qwen/qwen3.8-27b` (code/visión; sustituye a qwen3.6-27b, retirado el 14/09/2026).
  gpt-oss-120b es lo más potente que Groq sirve a esta cuenta (no hay mejor allí).
- **Whisper (voz→texto)**: `core/transcribe.py` usa `whisper-large-v3-turbo` de
  Groq (`settings.GROQ_WHISPER_MODEL`). Enganchado a `core/attachments.py`: un
  adjunto de audio (ogg/opus/mp3/m4a/wav…) se transcribe a texto ANTES de llegar
  al LLM, igual que las imágenes con visión. Nota: por la web/API ya funciona;
  para notas de voz de **Telegram** falta que el relay de Figaro reenvíe el audio.
- **NVIDIA NIM** = fallback cloud. Modelos vivos y validados (con tool-calling):
  `meta/llama-3.3-70b-instruct`, `openai/gpt-oss-120b`,
  `nvidia/llama-3.3-nemotron-super-49b-v1.5`, `openai/gpt-oss-20b`,
  `meta/llama-3.2-11b-vision-instruct` (visión). OJO: el catálogo `/models` de
  NVIDIA lista modelos que luego dan 404 al llamarlos con esta cuenta — validar
  con una llamada real, no solo por presencia en el catálogo.
- **Ollama** (local, RTX 5050 8 GB) = fallback sin internet. Modelos (tags reales
  instalados): `qwen2.5:7b` (general/code/tools), `qwen2.5-coder:7b-instruct-q4_K_M`
  (code), `deepseek-r1:7b` (reasoning), `gemma3:latest` (general/**visión local**).
  Techo del portátil: 7-8B en Q4 (~5 GB) van en GPU; 14B ya no cabe.
- **El agente de tool-calling NO usa un modelo NVIDIA fijo**: enruta por
  `router.chat_tools()` como todo lo demás, así que su cerebro también sigue la
  cascada Groq→NVIDIA→Ollama. (`settings.NVIDIA_MODEL_*` quedó como legacy sin uso.)
- **NO hay ninguna llamada a Anthropic en el código.** `ANTHROPIC_API_KEY` en
  `.env`/`.env.example` es residuo histórico sin uso.
- `core/llm.py` es la fachada (`generate()`, `build_prompt()`, `SYSTEM_PROMPT`);
  la selección real vive en `core/llm_router.py`. El backend que respondió se
  etiqueta vía `core/backend_state.py` (`[groq]`/`[nvidia]`/`[qwen-local]`).

## Cómo decide qué hacer: agente de tool-calling (principal) + intents (fallback)
- **PRINCIPAL**: `core/agent.py` + `core/tools.py` (tool-calling estilo OpenAI).
  `core/processor.py` llama a `agent.run()` ANTES que a nada. Cubre las 3
  interfaces (Telegram, chat local, API). Ver `docs/adr/0001-tool-calling-architecture.md`.
- **FALLBACK**: `core/intent.py` + `core/intent_ml.py` (TF-IDF+SVM,
  `config/intent_model.pkl`, con red de regex). Solo se usa si el agente lanza
  excepción (p. ej. NVIDIA y Ollama caídos a la vez).
- Correcciones de clasificación vía endpoint `/aprende`.

## Memoria y RAG (no es Mem0)
- `core/rag.py` + `core/active_memory.py` + `core/memory.py`.
- Embeddings `nomic-embed-text` (768 dims) vía Ollama `/api/embed`, cache LRU.
- Almacén en PostgreSQL local con **pgvector** (operador `<=>`). Store en hilo
  daemon (no bloquea la respuesta HTTP).
- Cada turno se guarda solo, troceado a ~2000 chars (`store_memory_chunks`; el
  embedding de un bloque más largo solo representa el principio). Tool `remember`
  para "guarda esto en tu memoria" (source = tema) y `search_memory(source=...)`
  para filtrar. Respuestas de entrevista: `data/entrevista_qa.json` →
  `python scripts/load_entrevista.py` (source `entrevista`, idempotente).
- Historial migrado ya ingerido: ~8.500 memorias (Claude 277 + Gemini 913 +
  ChatGPT 7328) vía `scripts/ingest_all.py --source claude|gemini|chatgpt`.

## PostgreSQL local
- Host: `127.0.0.1:5432` — conectar SIEMPRE con `-h 127.0.0.1` (peer auth falla en socket).
- **DB real: `jarvis`** (no `jarvis_v2`; ese nombre solo existe en un script de
  creación no ejecutado y confunde — ojo).
- User: `jarvis_user`. Password en `.env` → `POSTGRES_PASSWORD`.
- Tablas: conversations, tasks, task_context, summaries, projects, intents,
  memories (FTS español + vector), mando_snapshots. Pool en `core/db.py`.
- El auditor tiene su propia SQLite aparte: `auditor/auditor.db`.

## Interfaces de entrada
1. **Telegram**: bot `python-telegram-bot` en **Figaro** (100.78.43.76, systemd
   `jarvis-relay`, NO pm2). Cola offline `queue.db` en `/opt/jarvis-relay/`.
   Reenvía a la PC (Tailscale 100.127.159.59) `:3000`. `/notify` para avisos.
2. **Chat local**: `Jarvis Chat.bat` → `scripts/chat.py` (usa `generate_stream()`).
3. **API OpenAI-compatible**: `api/openai_compat.py` bajo `/v1` (frontend OpenClaw
   usa a Jarvis como cerebro por aquí).
- La API `api/main.py` (FastAPI `:3000`) exige header `X-Jarvis-Key`
  (`ApiKeyMiddleware`) salvo `/health`. Servicio Windows NSSM `JarvisAPI`.
- **Adjuntos** (`core/attachments.py`): texto/PDF, imágenes (visión por el router)
  y audio/notas de voz (ogg, opus, mp3, m4a…) → texto con Whisper en Groq
  (`core/transcribe.py`, modelo `settings.GROQ_WHISPER_MODEL`).

## Dominios / capacidades
- **Centro de Mando** (tareas): `connectors/mando_tasks.py` + `mando_sync.py` →
  `mando-api` en Figaro (PM2, `:10003`), fuente `dashboard-data.json`.
- **Auditor de código**: `auditor/{scanner,batcher,runner,synthesizer}.py`, usa
  `core/llm.generate(intent='audit')`. Rutas validadas por `auditor/allowed_paths.py`
  contra `config/repo_aliases.json`.
- **Auditoría remota**: `connectors/remote_audit.py` (SSH a Figaro, solo lectura).
- **Google Suite**: `connectors/google_tools.py` (Gmail/Calendar/Drive, OAuth2,
  cuenta `jarvis.gienini2.1009@gmail.com`). Tools de lectura y de escritura
  (`send_email`, `create_calendar_event`).
- **Alpha50** (entrenamiento): `alpha50/*` + `connectors/garmin_workouts.py`.
  Scheduler propio NSSM `Alpha50Scheduler` (independiente de JarvisAPI). Estado en
  `alpha50_cronologia.db`. Tool `query_alpha50_history`.
- **Editor de código (aider)**: `core/tools.py: edit_code()` — un commit git
  reversible por cambio, solo en repos de `config/repo_aliases.json`.
- **Netscan** (`netscan/*`): descubre/identifica hosts LAN + CVE lookup + report.
- **Autoampliación supervisada**: `core/self_extend.py`, ver `docs/adr/0002-*`.

## Convenciones
- Python 3.11+, async/await en FastAPI. Imports absolutos desde la raíz.
- `.env` nunca al repo. Config vía `config/settings.py` (Pydantic BaseSettings).
- No heredocs en bash — corrupción de terminal conocida. Usar SCP o echo line-by-line.
- **No hardcodear IDs de modelo en scripts.** Leerlos de `config/providers.json`
  o de `config/settings.py` (ver `scripts/aider_review.ps1` y `core/tools.py`).

## Mantener los modelos al día (para que NO vuelva a pasar lo del modelo retirado)
Los proveedores cloud retiran modelos por email (p. ej. Groq `developer@groq.co`).
Si un ID configurado desaparece, el modelo deja de servir.

- **Guardián**: `python scripts/check_models.py` consulta en vivo los catálogos
  `/models` de Groq/NVIDIA/Kimi y `/api/tags` de Ollama y marca cada modelo de
  `providers.json` (+ los de `settings.py` que usa aider) como OK/FALTA. Exit 1 si
  falta alguno → apto para cron semanal.
- **Cuándo correrlo**: tras cada correo "model is being decommissioned" y, de
  forma preventiva, una vez por semana.
- Al retirar/reemplazar un modelo: editar `config/providers.json` (y
  `config/settings.py` si es `*_MODEL_*`); los scripts que leen de ahí se
  actualizan solos.

## Archivos clave (¡ojo, nombres reales!)
- `core/llm_router.py` — selección de modelo (NO `core/router.py`).
- `core/llm.py` — fachada + system prompt.
- `core/agent.py` + `core/tools.py` — agente de tool-calling (camino principal).
- `core/rag.py` / `core/active_memory.py` / `core/memory.py` — memoria (NO Mem0).
- `config/providers.json` — proveedores y modelos (fuente de verdad del router).
- `connectors/relay.py` / `connectors/relay_client.py` — Telegram/relay Figaro.
- `scripts/ingest_all.py` — ingesta de exports (NO `memory/migrate.py`).
- `scripts/check_models.py` — guardián de disponibilidad de modelos.

## Hardware local (Victus 15-fa2xxx) — techo de la cascada offline
- CPU Intel Core 7 240H (10c/16t), **16 GB RAM** (ajustado), Windows 11.
- GPU **RTX 5050 Laptop, 8 GB VRAM** (Blackwell, CUDA 12). Es el límite: modelos
  de 7-8B en Q4 (~5 GB) caben en GPU; 14B (phi4) ya no. Por eso el set local son
  qwen2.5 / qwen2.5-coder / deepseek-r1:7b / gemma3 (visión). `OLLAMA_NUM_CTX=4096`
  para no disparar la latencia. Flash Attention recomendado.

## Pendientes conocidos (2026-08-25)
- **RESUELTO** modelos retirados: NVIDIA (`deepseek-v4-pro`, `qwen3-235b-a22b`,
  `nemotron-ultra-253b` daba 404) y tags de Ollama corregidos a lo instalado. La
  cascada y la visión quedaron validadas con llamadas reales. Correr
  `python scripts/check_models.py` para reverificar tras cualquier cambio.
- **Kimi/Moonshot**: la clave `KIMI_API_KEY` está puesta y sus modelos existen
  (`kimi-k3`, `kimi-k2.7-code`, `moonshot-v1-*`), pero **la cuenta está suspendida**
  (429 "account is suspended") → sigue `enabled:false` en `providers.json`.
  Reactivar cuando se resuelva el billing de Moonshot y validar con `check_models.py`.
- **RESUELTO** limpieza de `.env` (2026-09-26): fuera `ANTHROPIC_API_KEY` y 11
  overrides de modelo con nombres que `settings.py` no leía (`NVIDIA_*_MODEL`
  mal nombrados, `GROQ_DEFAULT/CODE/REASONING_MODEL`, `OLLAMA_MODEL_*`,
  `KIMI_*_MODEL`). Se conservó `ALPHA50_HORA` (sí lo usa el scheduler). La verdad
  de modelos es `providers.json` + los campos reales de `settings.py`.
- Alinear `README.md` y `.env.example` con la realidad (siguen describiendo la
  arquitectura vieja "solo local + Anthropic"; DB puesta como `jarvis_v2`).
- `POSTGRES_PASSWORD` en texto plano; credenciales Garmin en `.env` en claro.
- Alpha50: rate-limit 429 de Garmin sin resolver.
- TLS de Fígaro: cert de Tailscale en `/etc/ssl/figaro-server.taild7b9e6.ts.net.crt`,
  servido por nginx (proxy a node `/opt/mando` `:10003`). Auto-renovación por cron
  semanal (`/etc/cron.d/tailscale-cert-renew`). Si falla TLS, revisar ese cron y
  `tailscale cert`.
