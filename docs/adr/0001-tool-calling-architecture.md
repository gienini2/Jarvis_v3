# ADR-0001: De clasificador de intents a tool-calling con LLM

**Status:** Proposed
**Date:** 2026-07-02
**Deciders:** Juan Pablo

## Context

Jarvis decide qué hacer con cada mensaje mediante `core/intent.py`: un clasificador ML
(TF-IDF + SVM) con fallback a ~40 patrones regex agrupados en 11 tipos de intent
(`complete_task`, `query_task`, `mando_add/update/delete_task`, `google_gmail/calendar/drive`,
`audit`, `remote_audit`, `memory_search`). `core/processor.py` despacha cada tipo a una
función fija mediante un `if/elif` de 12 ramas.

Esto funciona pero tiene techo:

- Cada capacidad nueva exige un patrón regex nuevo (o datos de entrenamiento nuevos) más una
  rama nueva en `processor.py`. No generaliza a frases no previstas.
- No encadena acciones — un mensaje resuelve exactamente un intent, no una secuencia
  ("audita tingbot y si hay bugs críticos créame una tarea").
- Dos de los once intents (`mando_update_task`, `mando_delete_task`) llevaban implementados
  a medias durante semanas: el regex capturaba los grupos pero `processor.py` los descartaba
  y devolvía "en construcción" — un síntoma directo de que añadir cada capacidad a mano es
  frágil y fácil de dejar a medias.

Juan Pablo quiere que Jarvis se comporte como un agente con tool-calling real: el LLM decide
qué función invocar y con qué parámetros, en vez de que un clasificador de reglas decida por
él. Ya tiene tres backends de LLM configurados (Groq, NVIDIA NIM, Ollama local) con fallback
en cascada en `core/llm.py`, y acceso gratuito a NVIDIA NIM.

**Restricciones:**
- Debe seguir funcionando sin internet (Ollama local, `qwen2.5:7b`, es el único backend que
  no depende de red).
- El motor de decisión de qué herramienta llamar debe usar NVIDIA (`llama-3.3-70b-instruct`,
  ya configurado y gratuito) como principal, con qwen2.5 local como fallback offline —
  decisión explícita de Juan Pablo, independiente del orden Groq→NVIDIA→Ollama que ya usa
  `generate()` para chat general.
- Autonomía completa: Jarvis podrá leer, editar y ejecutar sus propios archivos, al nivel de
  lo que hace Claude en Cowork — decisión explícita de Juan Pablo, con el riesgo que conlleva.

## Decision

Sustituir el clasificador de intents por un **tool-calling loop**: un registro de
herramientas con schema JSON (nombre, descripción, parámetros) que el LLM elige y rellena,
en vez de un `if/elif` fijo. El código existente en `core/tasks.py`, `core/dashboard.py`,
`connectors/*.py` y `auditor/` se reutiliza tal cual — son las funciones a exponer como
herramientas, no hay que reescribirlas.

Arquitectura nueva:

```
mensaje usuario
      │
      ▼
core/agent.py (nuevo)
  ├── construye lista de herramientas disponibles (JSON schema)
  ├── llama al LLM en modo tool-calling:
  │      1. NVIDIA (llama-3.3-70b-instruct) — principal
  │      2. Ollama local (qwen2.5:7b) — fallback offline/error
  ├── el LLM devuelve: (a) texto directo, o (b) una o mas tool_calls
  ├── por cada tool_call: valida args -> ejecuta la funcion real -> guarda resultado
  ├── si hubo tool_calls, vuelve a llamar al LLM con los resultados (loop, max N vueltas)
  └── devuelve la respuesta final
```

`core/intent.py` (regex + ML) no se borra todavia: queda como fallback si el tool-calling
falla o si no hay ningun backend con function-calling disponible (ver Consequences).

## Options Considered

### Option A: Mantener y ampliar el clasificador de reglas

| Dimension | Assessment |
|-----------|------------|
| Complejidad | Baja — es el patron ya usado, solo añadir mas regex/intents |
| Coste | Cero, todo local |
| Escalabilidad funcional | Mala — cada capacidad nueva es un regex + una rama nueva a mano |
| Familiaridad | Alta, Juan Pablo ya conoce el patron |

**Pros:** determinista, cero coste, cero dependencia de red, fácil de debuggear.
**Cons:** no generaliza, no encadena acciones, ya mostró huecos (los dos intents a medio
implementar). No es lo que Juan Pablo pidió.

### Option B: Tool-calling completo (elegida)

| Dimension | Assessment |
|-----------|------------|
| Complejidad | Media-alta — nuevo loop de decisión, schemas por herramienta, manejo de errores por tool_call |
| Coste | Gratis (NVIDIA NIM free tier), con fallback local sin coste |
| Escalabilidad funcional | Alta — nueva capacidad = registrar una función, no tocar el router |
| Familiaridad | Media — Juan Pablo conoce tool-calling desde fuera (lo usa a diario en Claude/Cowork), es nuevo implementarlo |

**Pros:** generaliza a frases no previstas, encadena acciones, una sola forma de añadir
capacidades (registrar la herramienta), reduce el codigo de `processor.py` con el tiempo.
**Cons:** depende de que el LLM elegido soporte function-calling de forma fiable — qwen2.5:7b
(7B, sin fine-tuning especifico para tools) falla mas que un modelo de 70B; requiere validar
argumentos antes de ejecutar (superficie de error nueva: el LLM puede alucinar un
`project_id` o un `mando_key` que no existe).

### Option C: Híbrido — LLM decide, pero solo entre los intents ya definidos

| Dimension | Assessment |
|-----------|------------|
| Complejidad | Media — reemplaza el clasificador ML/regex por una llamada LLM de clasificación, pero mantiene el `if/elif` de despacho |
| Coste | Gratis (NVIDIA) |
| Escalabilidad funcional | Media — mejor generalizacion en la clasificacion, pero sigue sin encadenar acciones ni añadir capacidades sin tocar `processor.py` |
| Familiaridad | Alta — cambio quirurgico sobre el sistema actual |

**Pros:** riesgo bajo, cambio pequeño, mejora la clasificacion de los casos borrosos de hoy.
**Cons:** no es tool-calling real, no resuelve el problema de fondo (añadir capacidades sigue
siendo manual), no es lo que Juan Pablo pidió ("que se comporte como tú").

## Trade-off Analysis

La opción B es la única que cumple el objetivo explícito ("que Jarvis se comporte como tú").
El riesgo real no es técnico (NVIDIA NIM con `llama-3.3-70b-instruct` soporta tool-calling
estilo OpenAI de forma nativa) sino operativo: un LLM eligiendo y ejecutando funciones sobre
datos reales (tareas del Centro de Mando, archivos, auditorías) puede equivocarse de forma
silenciosa si no se valida cada paso. Por eso el rollout es incremental (ver Action Items):
empezar con las herramientas de solo lectura y bajo riesgo, añadir escritura después de que
el loop de decisión demuestre ser fiable.

El fallback a qwen2.5:7b local para tool-calling es aceptable como red de seguridad offline,
no como camino principal — un modelo de 7B sin fine-tuning de tools falla más al formar
argumentos JSON válidos. Se debe medir la tasa de fallos del fallback local en la práctica.

## Consequences

- Añadir una capacidad nueva a Jarvis pasa de "escribir regex + rama en processor.py" a
  "registrar una función con su schema" — más rápido y menos propenso a implementaciones a medias.
- Nueva superficie de fallo: argumentos alucinados por el LLM. Cada herramienta que escribe
  datos (mando_add/update/delete_task, futuras herramientas de archivo) necesita validar
  antes de ejecutar, no solo confiar en el LLM.
- Autonomía completa sobre archivos propios (leer/editar/ejecutar) es la pieza de más riesgo
  de este ADR. Mitigación acordada: cada cambio que Jarvis haga sobre su propio código pasa
  por un commit de git individual (ya limpio y funcional tras la reorganización de hoy) —
  reversible con `git revert` si algo sale mal. Esto no es opcional, es la condición para
  aceptar el nivel de autonomía pedido.
- `core/intent.py` no se elimina en esta fase — queda como fallback si NVIDIA y Ollama fallan
  ambos, o mientras el tool-calling nuevo se valida en paralelo. Se revisará su retiro en un
  ADR posterior una vez el nuevo sistema lleve un tiempo estable.
- Habrá que medir coste de latencia: una llamada de tool-calling a NVIDIA NIM (~90s timeout
  configurado en `core/llm.py`) es más lenta que un regex instantáneo. Para intents triviales
  (completar una tarea evidente) puede notarse.

## Action Items

1. [ ] Definir el registro de herramientas (`core/tools.py`): schema JSON por función,
       reutilizando `core/tasks.py`, `core/dashboard.py`, `connectors/mando_tasks.py`,
       `connectors/google_tools.py`, `auditor/runner.py` tal cual (sin reescribirlas).
2. [ ] Implementar `core/agent.py`: loop de tool-calling contra NVIDIA NIM
       (`llama-3.3-70b-instruct`, ya soporta `tools=[...]` estilo OpenAI) con fallback a
       Ollama local si NVIDIA falla o no hay internet.
3. [ ] Fase 1 — solo lectura: exponer como herramientas `query_task`, `find_tasks_by_*`,
       `memory_search`, `google_gmail/calendar/drive` (consulta), `audit` (dispara pero no
       modifica nada fuera del propio auditor). Cero riesgo de escritura incorrecta.
4. [ ] Fase 2 — escritura sobre Centro de Mando: `mando_add/update/delete_task`, con
       validación explícita (el `project_id`/`mando_key` debe existir antes de ejecutar,
       si no, pedir confirmación en vez de fallar silenciosamente).
5. [ ] Fase 3 — autonomía sobre archivos propios: herramientas de lectura/edición/ejecución
       de código del propio Jarvis, cada una commiteando a git automáticamente. Empezar en
       modo "propone el diff, Juan Pablo confirma por Telegram" antes de autoejecutar.
6. [ ] Medir tasa de fallo del fallback local (qwen2.5:7b) en tool-calling real durante al
       menos 1-2 semanas antes de confiar en él sin supervisión.
7. [ ] Decidir en un ADR posterior si `core/intent.py` se retira o se queda como fallback
       permanente de bajo nivel.
