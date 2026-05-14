# Jarvis v2 — CLAUDE.md

## Qué es esto
Sistema de IA personal (asistente tipo Jarvis) para Juan Pablo.
Cerebro en PC local Windows, relay Telegram en Hetzner VPS.

## Stack
- **LLM local**: Ollama + qwen2.5:7b (principal), llama3:8b (fallback pesado)
- **Embeddings**: nomic-embed-text via Ollama (`http://localhost:11434`)
- **Memoria**: Mem0 con backend PostgreSQL local (graph memory)
- **API local**: FastAPI en puerto 3000 (≠ jarvis v1 que era :2000)
- **Telegram relay**: python-telegram-bot en Hetzner, tunnela a PC via Tailscale
- **Fallback**: Anthropic claude-haiku-4-5 si Ollama no responde en 5s
- **Tailscale IP del PC**: pendiente de instalar cliente Windows

## PostgreSQL local
- Host: localhost:5432
- DB: jarvis_v2
- User: jarvis_user
- Password: en .env → POSTGRES_PASSWORD
- Siempre conectar con `-h 127.0.0.1` (peer auth falla en socket)

## Convenciones
- Python 3.11+, async/await en todo FastAPI
- Imports absolutos desde raíz del proyecto
- .env nunca al repo. Usar `config/settings.py` (Pydantic BaseSettings)
- No heredocs en bash — corrupción de terminal conocida. Usar SCP o echo line-by-line
- Mem0 memory_id = "juan_pablo" (único usuario)

## Flujo de mensaje Telegram
1. Usuario escribe en Telegram
2. Bot en Hetzner recibe → POST a `http://{TAILSCALE_PC_IP}:3000/chat`
3. API local: busca memoria relevante (Mem0) → construye prompt → llama Ollama
4. Respuesta vuelta a Hetzner → Telegram
5. Mem0 guarda el intercambio como nueva memoria

## Migración de memorias
Script: `memory/migrate.py`
Fuente: Hetzner PG (`/opt/jarvis`, 2.573 memorias)
Destino: PC local PG + re-indexar en Mem0

## Contextos de proyecto detectados
1. tingbot — trading bot BTC/USDC
2. bitacola — software policial municipal
3. oposiciones — preparación oposiciones
4. entrenamiento — fitness/Garmin
5. acoso_laboral — expediente laboral
6. jarvis — meta-proyecto IA personal

## Archivos clave
- `core/router.py` — lógica de selección de modelo
- `core/memory.py` — toda interacción con Mem0
- `telegram/relay.py` — autenticación Tailscale + retry logic
- `memory/migrate.py` — ejecutar UNA sola vez para migrar

## Pendientes conocidos
- Instalar Tailscale cliente Windows y apuntar IP en .env
- Importar ZIP ChatGPT (pendiente de OpenAI)
- Garmin API integration (entrenamiento)
- Limpiar prefijos "Gemini ha dicho:" / "Has dicho:" en memorias migradas