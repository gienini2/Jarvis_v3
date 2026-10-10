# Integrar Jarvis en otros proyectos — brief para agentes

> Para otro hilo de Claude (o cualquier dev) que trabaje en los **otros proyectos
> de Juan Pablo** (Bitácola/DRAG-AI, TingBot, Figaro…) y quiera **usar Jarvis** como
> cerebro / memoria / notificador, o simplemente tenerlo en cuenta.
> Detalle técnico interno completo: [`CLAUDE.md`](../CLAUDE.md).

## Qué es Jarvis
Asistente personal **local-first y monousuario** de Juan Pablo. Cerebro en su PC
(Windows, FastAPI en `:3000`), con **cascada multi-LLM** (Groq → NVIDIA → Ollama,
selección por potencia + disponibilidad), memoria RAG, agente de *tool-calling* y
varios dominios (tareas, Google, auditoría, red, entrenamiento, voz).
**Es privado**: se accede por `localhost` o por la **tailnet (Tailscale)**, nunca por internet.

## Cómo llamarlo (superficie de integración)
- **Base URL**: `http://127.0.0.1:3000` (misma máquina) o
  `http://100.127.159.59:3000` (PC por Tailscale, p. ej. desde Figaro).
- **Auth**: cabecera `X-Jarvis-Key: <JARVIS_API_KEY>` en todo **salvo** `/health`.
  La clave es la compartida del `.env` de Jarvis (no la pongas en claro en repos).

### A) OpenAI-compatible — recomendada para integrar
`POST /v1/chat/completions` con el formato de la API de OpenAI. Cualquier proyecto o
SDK que ya hable OpenAI puede usar a Jarvis como modelo (así lo hace OpenClaw).
También `GET /v1/models`.
```bash
curl -s http://127.0.0.1:3000/v1/chat/completions \
  -H "X-Jarvis-Key: $JARVIS_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"jarvis","messages":[{"role":"user","content":"hola"}]}'
```

### B) Simple
`POST /chat` → body `{"message":"..."}` → `{"response":"...","intent":"..."}`.
Pasa por el agente (memoria, tareas, Google, código, etc.) con cascada y fallback.
```bash
curl -s http://127.0.0.1:3000/chat \
  -H "X-Jarvis-Key: $JARVIS_API_KEY" -H "Content-Type: application/json" \
  -d '{"message":"qué tengo pendiente en bitacola"}'
```

### C) Adjuntos (PDF / imagen / audio → texto)
`POST /extract` → `{name, content_b64}` → `{text}`. Imágenes por visión, audio por
Whisper. Útil si tu proyecto quiere que Jarvis "lea" un archivo.

### D) Notificar a Juan Pablo por Telegram
El **relay en Figaro** expone `POST /notify` → `{message}` (cabecera `X-Relay-Key`).
`RELAY_URL = http://100.78.43.76:10004`. Cualquier proyecto puede empujar avisos a
su Telegram por aquí (lo usan el auditor y Alpha50).

### Otros endpoints
`GET /health` (sin auth) · `GET /commands` (chuleta) · `GET /tasks`,
`GET /mando/tasks`, `POST /mando/task/complete|delete` (Centro de Mando) ·
`GET /results/audit`, `GET /results/alpha50`, `GET /netscan/last`.

## Qué sabe hacer (para tenerlo en cuenta)
- **Memoria** RAG (PostgreSQL + pgvector), ~8.500 conversaciones + tool `remember`.
- **Tareas** del Centro de Mando (los proyectos reales de Juan Pablo; fuente en Figaro).
- **Google**: Gmail / Calendar / Drive (lectura y escritura real).
- **Auditoría de código** (local y remota por SSH), **netscan** de la LAN con CVEs,
  **Alpha50** (entrenamiento con Garmin).
- **Modo código**: `/code` (cascada) y `/code!` (dolphin3 local, sin censura).
- **Voz**: Whisper (oído) + TTS del navegador (habla) en la UI web.

## Cosas a tener en cuenta al integrar
- **Monousuario y privado.** No lo expongas a internet; usa `localhost`/Tailscale.
- **Tier gratis de Groq (8.000 tokens/min).** No le mandes prompts enormes en bucle;
  manda mensajes razonables. El router ya cae a NVIDIA/local si Groq raciona.
- **No dupliques memoria**: el agente ya inyecta contexto/memoria; deja que él lo haga.
- Si tu proyecto necesita que Jarvis **actúe** (mandar correo, crear tarea, avisar),
  basta con pedírselo en lenguaje natural por `/chat`.
- **No subir secretos** de Jarvis a otros repos (la `X-Jarvis-Key` es compartida).

## Contexto: proyectos del usuario
Bitácola (software policial, clientes Figueró/L'Arboç), TingBot (trading BTC/USDC),
infra en Figaro (Debian + Tailscale) y Hetzner. Jarvis puede ser el **cerebro y el
notificador común** de todos ellos.

---
Repo actual: **https://github.com/gienini2/Jarvis_v3** · interno: [`CLAUDE.md`](../CLAUDE.md).
