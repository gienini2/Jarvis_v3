# ADR-0002: Autoampliación supervisada (Fase 3)

**Status:** Proposed
**Date:** 2026-08-13
**Deciders:** Juan Pablo
**Relacionado:** ADR-0001 (tool-calling), Action Item 5 — "Fase 3: autonomía sobre archivos propios"

## Context

ADR-0001 dejó a Jarvis como un agente de tool-calling con 19 herramientas fijas
(`core/tools.py`). Añadir una capacidad nueva sigue siendo un acto manual de Juan Pablo:
escribir la función, registrarla en `TOOLS` y `FUNCTIONS`, instalar dependencias a mano y
reiniciar el servicio. El propio código lo reconoce en la cabecera de `core/tools.py`:
"Fase 3 (autonomia sobre el propio codigo de Jarvis) todavia no esta aqui".

El detonante concreto: Juan Pablo pidió por Telegram que Jarvis leyera un PDF y creara
eventos de calendario. Jarvis respondió, correctamente, que no tenía herramienta de PDF y
que no podía instalar nada. La respuesta era honesta pero expone el techo: **Jarvis detecta
lo que le falta pero no puede cerrarlo por sí mismo.**

### Qué hay ya construido (punto de partida)

- `edit_code` (`core/tools.py:772`) ya edita código vía `aider` con un modelo fuerte
  (`groq/openai/gpt-oss-120b`) y hace **un commit de git reversible por cambio**.
- El acceso está restringido por whitelist: `auditor/allowed_paths.py` +
  `config/repo_aliases.json`. `edit_code` rechaza rutas fuera de proyectos conocidos.
- Cada cambio es reversible con `git revert <hash>` — condición ya exigida en ADR-0001.

### Qué falta para cerrar el bucle

El planificador (qué código escribir) es la parte fácil y ya resuelta por el modelo fuerte.
Lo que no existe son las **tres piezas de ejecución segura**:

1. **Instalar dependencias.** No hay tool que ejecute `pip install`. "Necesito `pypdf`" muere ahí.
2. **Recargar el servicio.** `TOOLS`/`FUNCTIONS` se cargan al arrancar. Una tool nueva escrita
   en caliente no se registra hasta reiniciar el servicio NSSM `JarvisAPI`.
3. **Validar y revertir.** No hay puerta que compruebe que el cambio no ha roto Jarvis antes
   de darlo por bueno. Un `tools.py` mal editado deja el servicio sin arrancar → Jarvis muerto
   hasta arreglarlo a mano.

### La propuesta inicial de Juan Pablo

"Pedimos a Groq (o al UI al mando) un plan de cambios y luego bajamos a local para que el
modelo local (qwen2.5:7b) siga esas instrucciones."

El reparto planificador-ejecutor es correcto, pero con una matización que este ADR recoge
como sub-decisión: **el modelo local no debe escribir el código** (ver Options, Trade-off).

### Restricciones

- Debe funcionar en el PC local Windows con el servicio bajo NSSM (`JarvisAPI`). El reinicio
  es el mecanismo real de recarga, no un hot-reload en proceso.
- Jarvis modificándose a sí mismo no puede tener como peor caso "servicio que no arranca sin
  intervención humana". El auto-revert no es opcional.
- Reutilizar lo que ya hay (`edit_code`, whitelist de `allowed_paths.py`, commits de git) en
  vez de construir un mecanismo paralelo.

## Decision

Añadir un **bucle de autoampliación supervisada**: el modelo fuerte planifica y escribe el
parche; el PC local lo aplica, instala dependencias, se reinicia y se autovalida, con
**auto-revert** si la validación falla. La autonomía se gana solo cuando el cambio demuestra
no haber roto nada.

```
1. Modelo fuerte (Groq/UI al mando) → PLAN DE CAMBIOS
      (qué tool, qué fichero nuevo en plugins/, qué dependencias)
      │
      ▼
2. edit_code (aider, modelo fuerte) aplica el parche → 1 commit git
      │
      ▼
3. pip_install de las dependencias declaradas (whitelist / aprobación)
      │
      ▼
4. Watchdog reinicia el servicio JarvisAPI
      │
      ▼
5. Smoke test:  GET /health  +  prueba mínima de la tool nueva
      ├─ OK   → confirmado; avisa por Telegram
      └─ FALLA → git revert automático + reinicia + avisa "revertí X porque…"
```

Dos decisiones estructurales que acompañan al bucle:

- **Carpeta `plugins/` con auto-registro.** Cada tool nueva es un fichero que se descubre solo
  al arrancar, en vez de que Jarvis edite `TOOLS` y `FUNCTIONS` en dos sitios. El parche que
  escribe el modelo es "crea un fichero nuevo" — mucho más seguro que "modifica el registro
  central" y sin riesgo de descuadrar la lista.
- **El modelo local no genera parches.** Queda para lo que exige privacidad/offline; la
  generación de código que modifica a Jarvis usa siempre el modelo fuerte.

## Options Considered

### Option A: Status quo — `edit_code` manual + Juan Pablo hace pip y reinicio

| Dimension | Assessment |
|-----------|------------|
| Complejidad | Cero — ya está |
| Autonomía | Nula — cada ampliación exige intervención humana en 3 de 4 pasos |
| Riesgo | Bajo — el humano es la puerta de validación |
| Coste | Cero adicional |

**Pros:** simple, seguro, ya funciona. **Cons:** no es autoampliación; el techo que motiva
este ADR sigue intacto. Jarvis detecta lo que le falta pero no lo cierra.

### Option B: Autonomía total con hot-reload en proceso (`importlib`)

| Dimension | Assessment |
|-----------|------------|
| Complejidad | Alta — recargar módulos en un FastAPI vivo es frágil (estado, imports cacheados) |
| Autonomía | Máxima — sin reinicio, cambios instantáneos |
| Riesgo | Alto — sin frontera de proceso, un módulo roto contamina el runtime vivo; difícil de revertir en caliente |
| Coste | Cero adicional |

**Pros:** el bucle más rápido, sin ventana de reinicio. **Cons:** `importlib.reload` sobre un
servicio en producción es una fuente conocida de fallos silenciosos (referencias viejas,
estado parcial). Un fallo no deja un estado limpio que revertir. Demasiado riesgo para un
asistente que se modifica a sí mismo.

### Option C: Bucle supervisado — cloud planifica y codifica, local aplica-valida-revierte (elegida)

| Dimension | Assessment |
|-----------|------------|
| Complejidad | Media — reutiliza `edit_code`+git; añade `pip_install`, watchdog de reinicio, smoke test, auto-revert |
| Autonomía | Alta pero acotada — cierra el bucle sin poder brickear el servicio |
| Riesgo | Controlado — frontera de proceso (reinicio) + validación + auto-revert |
| Coste | Gratis (Groq free tier para codegen); reinicio local sin coste |

**Pros:** cierra el bucle de verdad, con red de seguridad. La frontera de proceso (reiniciar
en vez de recargar) da un estado limpio para validar y, si falla, revertir. Reutiliza lo ya
construido. **Cons:** cada ampliación tiene una ventana de reinicio (segundos de indisponibilidad);
el bucle tiene más piezas que la Option B.

### Sub-opción rechazada: el modelo local (qwen2.5:7b) escribe los parches

La propuesta inicial de Juan Pablo. Rechazada como camino de generación de código: un 7B sin
fine-tuning específico de edición produce parches multi-fichero rotos con frecuencia, y aquí
un parche roto es Jarvis rompiéndose a sí mismo. El valor de "local" en este ADR no es *quién
escribe* sino *dónde se aplica y se valida* — eso sí es 100% local. El modelo local se reserva
para privacidad/offline, no para codegen de auto-modificación.

## Trade-off Analysis

La Option C es la única que da autoampliación real sin aceptar "servicio caído sin arranque"
como peor caso. El coste es operativo, no técnico: más piezas móviles (watchdog, smoke test)
y una ventana de reinicio por cada cambio.

El punto crítico es el **paso 5 (validación + auto-revert)**. Sin él, la autoampliación es una
forma elegante de brickear el asistente: basta un parche que deje `tools.py` (o cualquier
import de arranque) inválido para que `JarvisAPI` no vuelva. Con el `git revert` que
`edit_code` ya provee, media red está puesta; falta el disparador automático que la accione
cuando el `/health` post-reinicio no responde.

La instalación de dependencias (`pip_install`) es la segunda superficie de riesgo: un paquete
arbitrario es ejecución de código de terceros en el PC. Se acota con whitelist de paquetes o
aprobación explícita por Telegram antes de instalar, en la misma línea que `edit_code` acota
rutas con `allowed_paths.py`.

## Consequences

- Añadir una capacidad pasa de "Juan Pablo escribe la tool + pip + reinicio" a "Jarvis propone
  el plan, lo aplica, se valida y avisa" — cerrando el techo que motiva este ADR.
- Nueva superficie de riesgo: ejecución de `pip install` desde el propio agente. Mitigación:
  whitelist de paquetes o aprobación por Telegram; nunca instalación silenciosa de arbitrario.
- Nueva superficie de riesgo: reinicio automático del servicio. Mitigación: watchdog externo al
  proceso (no el propio proceso reiniciándose), con `/health` como criterio de vida y timeout.
- El auto-revert es la condición de aceptación, igual que el commit-por-cambio lo fue en
  ADR-0001. Si el smoke test no existe o no revierte solo, esta fase no se despliega.
- La carpeta `plugins/` con auto-registro cambia cómo se añaden tools de aquí en adelante: las
  nuevas van como fichero autodescubierto; `TOOLS`/`FUNCTIONS` centrales se congelan para las
  existentes. Requiere un pequeño cargador al arranque en `core/tools.py` (o `core/agent.py`).
- Ventana de indisponibilidad por reinicio: unos segundos por cada ampliación. Aceptable para un
  asistente de un solo usuario; a documentar en el aviso de Telegram ("me reinicio para cargar X").
- Empezar en modo "propone el plan, Juan Pablo confirma por Telegram" antes de autoejecutar el
  bucle completo, igual que se acordó para Fase 3 en ADR-0001.

## Action Items

1. [ ] `plugins/` con auto-registro: cargador al arranque que descubre cada tool-fichero y la
       añade a `TOOLS`/`FUNCTIONS` sin edición manual del registro central.
2. [ ] Tool `pip_install(paquete)` con whitelist de paquetes (o aprobación por Telegram),
       reutilizando el patrón de `allowed_paths.py` pero sobre nombres de paquete.
3. [ ] Watchdog de reinicio supervisado del servicio `JarvisAPI` (NSSM), externo al proceso,
       con `GET /health` como prueba de vida y timeout.
4. [ ] Smoke test post-reinicio: `/health` + una prueba mínima de la tool recién añadida
       (declarada en el plan de cambios).
5. [ ] Auto-revert: si el smoke test falla, `git revert` del commit del paso 2 + reinicio +
       aviso por Telegram con el motivo. Sin esto, la fase no se despliega.
6. [ ] Orquestador del bucle (¿`core/self_extend.py`?): encadena plan → `edit_code` →
       `pip_install` → reinicio → smoke test → (confirmar | revertir).
7. [ ] Modo "confirma primero": el plan de cambios se manda por Telegram y espera OK de Juan
       Pablo antes de aplicar, durante el periodo de validación inicial.
8. [ ] Validación de la primera capacidad real de punta a punta con este bucle: lectura de PDF
       (`pypdf`) + creación de eventos de calendario — el caso que detonó este ADR.
9. [ ] Confirmar que el modelo local queda excluido del codegen de auto-modificación (solo
       privacidad/offline); el parche siempre lo escribe el modelo fuerte vía `edit_code`.
