# Jarvis — Asistente de IA personal (report técnico / portfolio)

Proyecto personal full-stack: un asistente de IA **local-first, multi-LLM y
multi-canal** que orquesta modelos cloud y locales, con memoria propia, un agente
de *tool-calling* y una docena larga de capacidades reales sobre la vida y los
proyectos del usuario.

---

## 1. Resumen ejecutivo
Jarvis es un asistente tipo "Iron Man" autoalojado. El cerebro corre en un PC
(FastAPI), decide con qué LLM responder mediante una **cascada con puntuación por
potencia y disponibilidad** (Groq → NVIDIA → Ollama local), mantiene **memoria
persistente** (PostgreSQL + pgvector), y actúa sobre el mundo real a través de un
**agente de tool-calling** con 21 herramientas: tareas, Gmail/Calendar/Drive,
auditoría de código, escaneo de red, entrenamiento deportivo, visión y voz.
Accesible por chat web, Telegram y una API compatible con OpenAI.

---

## 2. Funcionalidades (todo lo que hace)

### Conversación e inteligencia
- **Cascada multi-LLM con routing inteligente**: selección de modelo por rol
  (general / código / razonamiento / visión / tools) y por **potencia +
  disponibilidad medida en vivo** (latencia y penalización por rate-limit que
  decae con los aciertos). Caída automática a modelo local sin internet.
- **Agente de tool-calling** (estilo OpenAI function-calling) como camino
  principal, con clasificador de intents (TF-IDF + SVM) como *fallback*.
- **Optimización de tokens**: dos ramas de herramientas por intent (−84 % de
  tokens de entrada en el caso común) para esquivar límites de rate y latencia.
- **Modo código**: `/code` (modelo especializado de la cascada) y `/code!`
  (modelo local *uncensored* dolphin3, offline).

### Memoria
- **RAG** con embeddings `nomic-embed-text` (768d) y **pgvector** (búsqueda por
  coseno en PostgreSQL), con pre-filtro full-text en español y troceado de textos
  largos. ~8.500 conversaciones históricas ingeridas (Claude/Gemini/ChatGPT).
- Herramienta `remember` para memoria explícita y filtrado por origen.

### Acciones reales (herramientas del agente)
- **Centro de Mando**: CRUD de tareas de múltiples proyectos, sincronizado con un
  servidor remoto.
- **Google Suite** (OAuth2): leer y **enviar** correos, leer y **crear** eventos
  de calendario, buscar en Drive.
- **Auditoría de código**: análisis de repos **locales y remotos (por SSH)** y
  **edición de código real** con *aider* (un commit git reversible por cambio).
- **Escáner de red**: descubrimiento de hosts de la LAN, *fingerprinting*,
  **búsqueda de CVEs** y report con notificación por Telegram.
- **Alpha50**: coach de entrenamiento integrado con **Garmin Connect** (report propio en
  [Alpha50-core](https://github.com/gienini2/Alpha50-core/blob/main/docs/PORTFOLIO.md)).
- **Notificaciones proactivas** a Telegram.

### Multimodal
- **Visión**: describe imágenes por la misma cascada (Groq / NVIDIA / gemma3 local).
- **Voz**: *speech-to-text* con **Whisper** (notas de voz) y *text-to-speech* en la
  UI; modo de conversación hablada en el navegador.

### Interfaces
- **UI web** propia (SPA en vanilla JS): chat con streaming, adjuntos, pestañas de
  tareas/entreno/red, chuleta de comandos, iconos por LLM y **tema claro/oscuro
  según la hora del sistema**.
- **Telegram** (relay en servidor remoto con cola offline).
- **API OpenAI-compatible** (`/v1/chat/completions`) para que otros sistemas usen
  a Jarvis como cerebro.

### Fiabilidad y operación
- *Guardián* de modelos (`check_models.py`) que valida en vivo que los modelos
  configurados siguen existiendo (los proveedores cloud los retiran).
- Servicios Windows (NSSM), *health checks*, reintentos y *fallbacks* en cadena.
- Autoampliación supervisada del propio código (ADR documentado).

---

## 3. Cómo funciona (arquitectura)
```
Telegram (relay en servidor Debian, cola SQLite) ─┐
Chat web / API OpenAI-compatible ─────────────────┤ (Tailscale / localhost)
                                                   ▼
                        FastAPI :3000  (PC, servicio NSSM)
                                   │
          ┌────────────────────────┼─────────────────────────┐
     Agente tool-calling     Memoria + RAG            Router LLM (config-driven)
     (21 tools)              (pgvector, embeddings)   potencia + disponibilidad
          │                        │                         │
   Google · Tareas · Auditor       PostgreSQL          Groq → NVIDIA → Ollama
   Netscan · Alpha50 · aider                           (+ Whisper, visión, dolphin)
```
- **Config-driven**: proveedores y modelos en un JSON; el router puntúa y filtra
  por rol, capacidades, contexto y salud.
- **Local-first**: siempre hay un modelo local (Ollama) como red de seguridad sin
  internet; lo cloud se prefiere por velocidad/capacidad.

---

## 4. Stack tecnológico (lo que se ha tocado)

**Lenguajes:** Python 3.11+, JavaScript (vanilla), HTML/CSS, SQL, PowerShell, Bash.

**Backend / API:** FastAPI, async/await, Pydantic (settings), Uvicorn, middleware
de autenticación propio, API REST + API compatible con OpenAI.

**IA / LLMs:**
- Cloud: **Groq** (gpt-oss-120b/20b, qwen3.8-27b, **Whisper** STT), **NVIDIA NIM**
  (llama-3.3-70b, nemotron-super-49b), **Moonshot/Kimi** (integrado).
- Local (**Ollama**): qwen2.5, qwen2.5-coder, deepseek-r1, **gemma3** (visión),
  **dolphin3** (uncensored).
- Técnicas: **tool/function-calling**, **RAG**, **embeddings** (nomic-embed-text),
  *prompt engineering*, multimodal (visión + STT/TTS), *model routing* y *fallback*.

**Datos:** PostgreSQL, **pgvector** (búsqueda vectorial), full-text search en
español, SQLite, *connection pooling* (psycopg2), sin ORM.

**ML clásico:** scikit-learn (TF-IDF + SVM) para clasificación de intents.

**Integraciones / APIs externas:** Telegram Bot API, **Google OAuth2**
(Gmail/Calendar/Drive), **Garmin Connect**, **aider** (edición de código asistida),
*scraping*/parseo de PDF (pdfplumber).

**Infra / DevOps:** Windows + **NSSM** (servicios), servidor **Debian**, **Tailscale**
(VPN mesh), **systemd**, **PM2**, **nginx** (reverse proxy + TLS), **SSH**, **cron**,
**git**, auto-renovación de certificados.

**Seguridad:** autenticación por API key, prevención de *path traversal* y de
*command injection* (shlex), *whitelisting* de rutas, conciencia de *prompt
injection*, gestión de secretos fuera del repo.

**Redes / seguridad ofensiva-defensiva:** escaneo de red (nmap/NSE), *fingerprinting*
de dispositivos, correlación de **CVEs**.

---

## 5. Retos técnicos resueltos (lo interesante)
- **Routing LLM consciente de disponibilidad**: no basta con elegir el modelo más
  potente; se pondera latencia y rate-limits en vivo, con penalización que decae,
  para que un proveedor saturado ceda el paso y se recupere solo.
- **Optimización de coste/latencia**: recorte del 84 % de tokens de entrada
  cargando solo las herramientas relevantes por intención, con *escape* a set
  completo bajo demanda.
- **Ciclo de vida de modelos**: guardián que detecta modelos retirados por los
  proveedores antes de que rompan producción.
- **IA en hardware modesto**: modelos de 7-8B cuantizados corriendo en una GPU de
  8 GB, con el techo de VRAM gestionado (modelo local + visión + voz sin pelearse).
- **Resiliencia**: cascada cloud→local con *health checks*, reintentos y cola
  offline, para que el asistente responda aun con proveedores caídos o sin internet.

---

## 6. Escala del proyecto
- ~112 ficheros · ~70 commits · 21 herramientas del agente.
- 3 proveedores LLM cloud + 5 modelos locales, selección dinámica.
- ~8.500 memorias conversacionales indexadas vectorialmente.
- 3 interfaces (web, Telegram, API) sobre un único núcleo.

---

## 7. Bullets listos para el CV
- Diseñé y construí un **asistente de IA full-stack local-first** que orquesta
  múltiples LLMs (Groq, NVIDIA NIM, Ollama) con un *router* propio que pondera
  **potencia y disponibilidad en tiempo real**.
- Implementé un **agente de tool-calling** con 21 herramientas (Google API, tareas,
  auditoría de código, escaneo de red, Garmin) y un sistema de **memoria RAG** con
  **PostgreSQL + pgvector** sobre ~8.500 conversaciones.
- Reduje un **84 % los tokens de entrada** por petición con carga de herramientas
  por intención, y añadí capacidades **multimodales** (visión y voz con Whisper/TTS).
- Monté la **infraestructura self-hosted** (FastAPI, servicios Windows/NSSM, Debian,
  Tailscale, nginx, PM2, SSH) y una **API compatible con OpenAI** para integrarlo
  con otros sistemas.
- Apliqué **buenas prácticas de seguridad** (auth por API key, prevención de
  *path traversal*/*command injection*, gestión de secretos) y de **fiabilidad**
  (health checks, *fallbacks* en cascada, cola offline).

**Tecnologías (una línea):** Python · FastAPI · PostgreSQL/pgvector · LLMs (Groq,
NVIDIA NIM, Ollama) · RAG & embeddings · tool-calling · Whisper/visión · scikit-learn ·
Google OAuth2 · Telegram Bot API · Garmin · aider · Tailscale · nginx · NSSM ·
JavaScript/HTML/CSS · SQL · Bash/PowerShell · git.
