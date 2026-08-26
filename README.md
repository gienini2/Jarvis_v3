# Jarvis — Personal AI Assistant

A self-hosted, local-first AI assistant. The brain runs on a Windows PC with an
NVIDIA GPU; conversations arrive via a Telegram relay, a local chat, or an
OpenAI-compatible API. Model selection is a config-driven cascade across cloud
and local providers, with a local model as the offline fallback.

> Detailed, always-current architecture lives in [`CLAUDE.md`](CLAUDE.md).

## What it does

- Answers questions and holds conversations with persistent memory (PostgreSQL + pgvector)
- Decides actions with a tool-calling agent (falls back to an ML/regex intent classifier)
- Injects only relevant context into each prompt — not a full memory dump
- Manages tasks across multiple active projects, synced from a personal dashboard
- Routes each request through a provider cascade: **Groq → NVIDIA NIM → Ollama (`qwen2.5:7b`, local/offline)**

## Architecture

```
Telegram relay (Figaro server) ─┐
Local chat (chat.py) ───────────┤  POST /chat  (Tailscale tunnel / localhost)
OpenAI-compatible API (/v1) ────┘
        ▼
FastAPI  :3000  (Windows PC)
        │
        ├── Tool-calling agent  (core/agent.py + core/tools.py)  ← primary
        │         └── fallback: ML/regex intent classifier (core/intent*.py)
        │
        ├── Active memory + RAG  (core/rag.py, pgvector, nomic-embed-text)
        │
        └── LLM router  (core/llm_router.py, config/providers.json)
                   Groq (gpt-oss-120b) → NVIDIA NIM → Ollama (qwen2.5:7b, offline)
```

## Tech stack

| Layer | Choice |
|---|---|
| API | FastAPI (async) |
| LLM inference | Cascade: Groq (cloud) → NVIDIA NIM (cloud) → Ollama `qwen2.5:7b` (local) |
| Model selection | `config/providers.json` + `core/llm_router.py` (role/health scoring) |
| GPU | NVIDIA RTX 5050, CUDA (Blackwell) — runs Ollama + embeddings |
| Memory & RAG | PostgreSQL + pgvector, `nomic-embed-text` embeddings |
| Conversation relay | python-telegram-bot on the Figaro server (systemd) |
| Networking | Tailscale (relay → PC tunnel) |
| Config | Pydantic BaseSettings + `.env` |

## Project structure

```
api/
  main.py          — FastAPI routes (/chat, /tasks, /health)
core/
  llm.py           — Ollama client, prompt builder
  intent.py        — Regex intent classifier + project alias map
  active_memory.py — Context injection: summaries + tasks + recent turns
  memory.py        — Conversation persistence (PostgreSQL)
  tasks.py         — Task CRUD, Centro de Mando sync
  dashboard.py     — Dashboard data loader
  summarizer.py    — Periodic conversation summarizer
  db.py            — psycopg2 connection helper
config/
  settings.py      — Pydantic settings (reads .env)
connectors/
  mando_sync.py    — Sync tasks from external dashboard JSON
scripts/
  migrate_db.py    — Database schema setup
  sync_mando.py    — One-shot task import
  summarize.py     — Manual summary trigger
  chat.py          — CLI test client
```

## Design decisions

**Tool-calling agent as the primary path.** A tool-calling agent (`core/agent.py` + `core/tools.py`) decides what to do — query tasks, send email, edit code, etc. An ML/regex intent classifier (`core/intent*.py`) remains as a deterministic fallback for when the agent's providers are all down. (Earlier versions ran the classifier as the main path; it is now the safety net.)

**Selective context injection.** Rather than dumping all memory into the prompt, `active_memory.py` extracts keywords from the user message and fetches only matching tasks and a single consolidated summary. The prompt stays under 4K tokens while still being context-aware.

**Local-first, not local-only.** The router prefers cloud providers (Groq, NVIDIA) for speed and capability, but always keeps a local Ollama model as the offline fallback so the assistant still answers with no internet. The Telegram relay only forwards text; it never runs the LLM.

**Flat database schema.** Tasks, conversations, summaries, and intent logs each have their own table. No ORM — direct psycopg2 for simplicity and control.

## Setup

### Requirements

- Python 3.11+
- PostgreSQL 16 running locally
- [Ollama](https://ollama.com) with `qwen2.5:7b` pulled
- (Optional) Tailscale for the Telegram relay

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/jarvis.git
cd jarvis
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials
```

### 3. Create the database schema

```bash
python scripts/migrate_db.py
```

### 4. Pull the model

```bash
ollama pull qwen2.5:7b
```

### 5. Run

```bash
uvicorn api.main:app --port 3000
```

Test it:
```bash
curl -X POST http://localhost:3000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
```

### GPU note (NVIDIA)

Ollama offloads all model layers to GPU by default when CUDA is available. For better throughput enable Flash Attention before starting Ollama:

**Windows:**
```
setx OLLAMA_FLASH_ATTENTION 1
```
Then restart Ollama from the system tray.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/chat` | Main chat endpoint |
| `GET` | `/tasks` | List tasks (filter by `project`, `keyword`, `status`) |
| `POST` | `/tasks/sync` | Re-import tasks from dashboard JSON |
| `POST` | `/tasks/context` | Attach a note/link/decision to a task |
| `GET` | `/health` | Liveness check |

## Environment variables

See `.env.example`. The only required variables are the PostgreSQL connection details. Everything else has a default.
