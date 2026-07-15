# Alpha50 IA — Punto de partida para Cowork

## Qué es este proyecto

Sistema de entrenamiento inteligente que fusiona el **Método Fitness Alpha50** (plan de
12 semanas) con los datos biométricos del **Garmin Forerunner 165**. Cada mañana decide
si entrenar, reducir intensidad o descansar según el estado de recuperación del usuario,
y manda el entreno del día por Telegram.

**Usuario:** Juan Pablo (cliente cero). Viudo, padre de Tanit y Arnau. Policía con fondo
técnico (PLC, bases de datos, bots de trading). Prefiere respuestas directas y eficientes.

**Contexto físico actual:** sobrepeso significativo (99 kg), arranca en Semana 1 nivel
Intermedio. Golpe reciente en el costado (posible fisura) — el sistema debe respetar el
semáforo de recuperación y no forzar.

---

## Lee primero estos dos contextos

1. **Skill `jarvis-context`** — toda la arquitectura de Jarvis (infra, relay, BD, reglas).
   CRÍTICO: el PC local es **Windows / PowerShell siempre**. El relay de Fígaro es Linux.
2. **`Alpha50_IA_Documentacion_v1.0.docx`** — documentación técnica completa del sistema.

---

## Arquitectura (ya funcionando end-to-end)

```
Telegram → relay Fígaro (Debian, systemd jarvis-relay) → JarvisAPI (Windows, NSSM, puerto 3000)
   → core/processor.py → alpha50_intent_handler() → 4 agentes → respuesta → relay → Telegram
```

**Componentes Alpha50** en `C:\Users\Usuario\jarvis\alpha50\`:
- `alpha50_plan.json` — 12 semanas × 5 días, nivel Intermedio (60 sesiones)
- `agente_cronologia.py` — semana/día actual + historial + repite semana si hay saltados
- `agente_plan.py` — devuelve entreno del día formateado
- `agente_metrica.py` — Garmin Connect + fallback manual + índice disposición (0-100)
- `agente_decisor.py` — cruza todo, ajuste quirúrgico por series/ciclos/tiempo, genera mensaje
- `scheduler.py` — disparo 07:00 + intent handler Telegram + comandos
- `alpha50_cronologia.db` — SQLite (cronología + métricas), se crea solo

**Servicio:** `Alpha50Scheduler` (NSSM, Windows). Programa iniciado en Semana 1 desde 2026-07-01.

---

## Lógica clave del sistema

**Calendario semanal:** L/X/S = cardio (carrera/bici/HIIT), M/V = musculación, J/D = descanso.
5 días de entreno. Todo es peso corporal, sin pesos.

**Día saltado:** el calendario avanza igual, pero la semana se REPITE completa la siguiente.

**Índice de disposición (0-100):** Body Battery 35% + sueño 25% + HRV 20% + FC reposo 10% + estrés 10%.

**Semáforo y ajustes:**
| Semáforo | Índice | Musculación | HIIT | Cardio continuo |
|----------|--------|-------------|------|-----------------|
| 🟢 Verde | 75-100 | 4 series × 4 SS | 4 ciclos | 100% |
| 🟡 Amarillo | 50-74 | -1 serie/ejercicio | 3 ciclos, +10" desc | -20% |
| 🟠 Naranja | 30-49 | 2 series × 2 SS | 2 ciclos, +20" desc | 20' suave |
| 🔴 Rojo | 0-29 | descanso activo | descanso activo | descanso activo |

**Comando Telegram:** se invoca SIN barra → `alpha50 ahora`, `alpha50 estado`, `alpha50 semana`,
`alpha50 tendencia`. (Con `/` Telegram lo trata como comando y el relay lo ignora porque solo
tiene CommandHandler para /audit y /aprende, no para /alpha50).
Respuestas de sesión: `A`/`B`/`C` (opción cardio), `hecho`, `parcial [detalle]`, `no pude`, `ok`.

---

## Historia importante de bugs resueltos (no repetir)

1. **`extra_forbidden` en Pydantic** — añadir variables al `.env` rompía el arranque entero de
   Jarvis. Resuelto añadiendo `extra = "ignore"` en `class Config` de `config/settings.py`.
   Esto causaba reinicios en bucle → cortes intermitentes del relay (WinError 10051).

2. **`process() got unexpected keyword 'rag_memories'`** — `api/openai_compat.py` y `api/main.py`
   llamaban `process(msg, rag_memories=...)` pero `core/processor.py` solo acepta `process(message)`
   y ya busca memorias internamente. Resuelto quitando el argumento sobrante en ambos archivos.

3. **`/alpha50` se evaporaba en el relay** — Telegram trata `/...` como comando; el MessageHandler
   del relay tiene `~filters.COMMAND`. Solución: invocar sin barra (`alpha50 ahora`). El handler
   ya reconoce ambas formas.

4. **`enviar_telegram()` no enviaba** — buscaba TELEGRAM_TOKEN directo en vez de usar el relay.
   Resuelto: ahora hace POST a `{RELAY_URL}/notify`.

---

## Pendientes (en orden de prioridad sugerido)

1. **Formato del tachado en Telegram** — los `_~~4~~_` se ven raros. Cambiar por algo limpio
   tipo `(3 series, antes 4)` en `agente_decisor.py` (funciones `_ajustar_series_muscu` y el
   formateo de mensajes).

2. **Garmin 429 (rate limit)** — de tanto reiniciar, Garmin bloqueó la IP. Añadir en
   `agente_metrica.py`: caché de la última lectura válida (para no depender de login cada vez)
   y reintentos con backoff. Verificar credenciales: GARMIN_EMAIL / GARMIN_PASSWORD en `.env`.

3. **Función catch-up** — si el PC arranca después de las 07:00, el flujo de ese día se pierde
   (schedule no recupera ejecuciones perdidas). Añadir en `scheduler.py`: al arrancar, comprobar
   si ya pasó la hora y no hay registro de hoy → disparar.

4. **Niveles adicionales** — añadir al JSON: Principiante, PrePrincipiante, Avanzado, Bestia.
   El usuario tiene acceso a todos los PDFs. La estructura `nivel → semana → día` ya lo soporta,
   solo hay que parsear los PDFs/Excel nuevos. Mismo proceso que se hizo con Intermedio.

5. **Dashboard web** — servir HTML estático desde Fígaro (como el Centro de Mando) leyendo de
   `alpha50_cronologia.db`: gráficas de Body Battery, FC reposo, peso, semáforos por día,
   correlaciones (con qué BB rinde mejor en HIIT vs musculación).

6. **Registrar `/alpha50` como CommandHandler propio en el relay** (cosmético) — para que salga
   en el menú de comandos de Telegram. Editar `/opt/jarvis-relay/relay.py` en Fígaro, añadir
   `app.add_handler(CommandHandler("alpha50", handle_alpha50))` y reenviar al endpoint.

---

## Reglas técnicas (de jarvis-context, no romper)

- Terminal PC local: **PowerShell siempre**. Relay Fígaro: bash/Linux.
- Reiniciar servicios: `nssm restart JarvisAPI` / `nssm restart Alpha50Scheduler` (Windows);
  `systemctl restart jarvis-relay` (Fígaro).
- Deploy a Fígaro: `scp archivo.py figaro:/ruta/`
- Python del venv: `C:\Users\Usuario\jarvis\.venv\Scripts\python.exe`
- Si tocas el `.env`, recuerda el `extra = "ignore"` ya está puesto.

---

## Estado a fecha 30/06/2026

✅ Sistema operativo end-to-end. `alpha50 ahora` por Telegram devuelve el entreno del día
correctamente ajustado por semáforo. Los 4 agentes funcionan. Cronología en Semana 1.
⚠️ Garmin rate-limited temporalmente (datos de hoy fueron parciales/caché).
⏳ Pendientes 1-6 arriba.
