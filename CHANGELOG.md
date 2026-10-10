# Changelog — Jarvis

Registro de las actualizaciones. Fechas y hashes de los commits reales.

## [2026-10-10] UI: iconos por LLM, tema por hora y comandos
- **Iconos por LLM en el chat** (`web/chat.html`): la respuesta muestra qué backend
  contestó como icono (⚡ Groq, 🟢 NVIDIA, 🐬 dolphin local, 🏠 qwen local, 🌙 Kimi,
  💻 local) en vez del texto `[groq]`. No se lee en voz alta. — `77c199a`
- **Tema claro/oscuro por la HORA del sistema** (noche ≥19h o <7h → oscuro),
  aplicado antes de pintar (sin parpadeo) + re-chequeo cada 10 min. — `77c199a`
- **Pestaña «Comandos»**: chuleta de atajos editable en `config/commands.json`,
  leída en vivo por el endpoint `/commands`; el comando resalta en color acento. — `57f816f`, `77c199a`

## [2026-10-10] Eficiencia de tokens: ramas de herramientas
- **Agente con dos ramas** (`core/agent.py`, `core/tools.py`): según `classify()`,
  la charla/recuerdo/consulta carga solo `search_memory`/`remember`/`query_tasks`
  (~540 tok) en vez de las 23 tools (~3600 tok) → **−84 % de tokens de entrada**
  por ronda, menos 429 del tier gratis de Groq y menos latencia. Tool de escape
  `usar_herramientas` recarga el set completo si hay que actuar. — `57f816f`

## [2026-09-26] Voz, multimodal y memoria
- **Notas de voz → texto con Whisper en Groq** (`core/transcribe.py`,
  `core/attachments.py`): un adjunto de audio se transcribe antes de llegar al LLM. — `c18f005`
- **Modo voz en la UI web**: micro (MediaRecorder → Whisper) y lectura de
  respuestas (speechSynthesis del navegador). 0 VRAM. — `web/chat.html`
- **Memoria mejorada** (`core/rag.py`, `core/tools.py`, `core/agent.py`): tool
  `remember`, troceado de turnos largos (`store_memory_chunks`), filtro por
  `source`, historial completo al agente, loader de entrevista. — `c926be8`
- Docs al día: `CLAUDE.md`, dashboard. — `0fc735c`, `a6daf28`

## [2026-08-26 → 09-02] Gestión de modelos y cascada LLM
- **Saneo de modelos retirados**: Groq `llama-3.3-70b-versatile` (16/08) y
  `qwen3.6-27b → qwen3.8-27b` (14/09); NVIDIA fuera `deepseek-v4-pro`,
  `qwen3-235b-a22b`, `nemotron-ultra-253b` (404); tags de Ollama corregidos a lo
  instalado. Todo validado con llamadas reales. — `ab74471`, `6dc26b3`
- **Router con ponderación potencia + disponibilidad** (`core/llm_router.py`,
  `core/llm_health.py`): además de la potencia (prioridad + capacidad), pondera
  disponibilidad en vivo (latencia + penalización por 429 que decae con éxitos).
  Un proveedor degradado cede el puesto y se recupera solo. — `ab74471`
- **Guardián `scripts/check_models.py`**: verifica en vivo que los modelos
  configurados sigan existiendo (Groq/NVIDIA/Kimi + Ollama). Apto para cron. — `ab74471`
- **Set local adaptado al Victus** (RTX 5050, 8 GB): qwen2.5 / qwen2.5-coder /
  deepseek-r1:7b / gemma3 (visión). — `ab74471`
- **Limpieza de `.env`**: fuera `ANTHROPIC_API_KEY` (sin uso) y 11 overrides de
  modelo muertos. La verdad de modelos es `config/providers.json`.

---
Colaboración Juan Pablo + Claude (Opus). Detalle técnico vivo en `CLAUDE.md`.
