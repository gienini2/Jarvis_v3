"""
core/tools.py
Registro de herramientas para el tool-calling loop (core/agent.py).

Fase 1 (ADR-0001): herramientas de lectura -- query_tasks, search_memory, Gmail,
Calendar, Drive, start_audit. No modifican nada.

Fase 2 (ADR-0001): herramientas de escritura sobre el Centro de Mando --
add_task, update_task, delete_task. Cada una valida contra datos reales antes
de ejecutar (resuelve el proyecto/tarea primero) en vez de confiar ciegamente
en lo que el LLM cree que existe. Si hay ambiguedad (varias tareas coinciden,
o el proyecto no se reconoce), la tool devuelve la lista de candidatos como
error para que el LLM se lo pregunte a Juan Pablo en vez de adivinar.

Fase 3 (autonomia sobre el propio codigo de Jarvis) todavia no esta aqui.
"""
from core.tasks import find_tasks_by_project, find_tasks_by_keyword, find_all_pending, sync_tasks_from_json
from core.rag import search_memories, store_memory_chunks
from connectors.google_tools import (
    get_recent_emails,
    search_emails,
    get_upcoming_events,
    list_drive_files,
    search_drive_files,
    send_email as _send_email,
    create_event as _create_event,
    find_events as _find_events,
    delete_event as _delete_event,
)
from connectors.mando_tasks import (
    add_task as _mando_add_task,
    update_task as _mando_update_task,
    delete_task as _mando_delete_task,
    find_project_id,
)
from connectors.relay_client import send_telegram_message as _send_telegram_message

# ---------------------------------------------------------------------------
# Schemas (formato tools de OpenAI/NVIDIA/Ollama)
# NOTA: sin la clave "default" en los schemas -- Ollama /api/chat devuelve
# 400 Bad Request con algunos JSON schemas que la incluyen. Los defaults
# reales viven en las firmas de las funciones Python de abajo.
# ---------------------------------------------------------------------------

TOOLS = [
    # ---- Fase 1: solo lectura ------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "query_tasks",
            "description": (
                "Consulta tareas pendientes del Centro de Mando. Sin argumentos devuelve "
                "TODAS las pendientes (para 'que tengo pendiente / esta semana'); con "
                "'project' filtra por proyecto y con 'keyword' por texto. Solo lectura."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Nombre o id del proyecto, ej. 'tingbot', 'jarvis', 'bitacola'. Vacio si no aplica.",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Palabra clave a buscar en el texto de la tarea. Vacio si no aplica.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Busca en el historial de conversaciones pasadas de Juan Pablo (PostgreSQL "
                "+ embeddings). Usar cuando pregunte 'de que hablamos', 'recuerdas cuando', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Que buscar en la memoria"},
                    "limit": {"type": "integer", "description": "Maximo de resultados, por defecto 4 si se omite"},
                    "source": {
                        "type": "string",
                        "description": "Opcional: limitar a un tema guardado con remember, ej. 'entrevista'. Vacio = todo.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Guarda informacion en la memoria persistente de Jarvis (PostgreSQL + embeddings) "
                "para recuperarla despues con search_memory. Usar cuando Juan Pablo diga 'recuerda', "
                "'guarda esto en tu memoria', 'tenlo en memoria'. NO es el Centro de Mando."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Texto completo a recordar, sin resumir"},
                    "topic": {"type": "string", "description": "Etiqueta corta del tema, ej. 'entrevista', 'preferencias'"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_emails",
            "description": "Lista los correos mas recientes de Gmail. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "por defecto 5 si se omite"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_gmail",
            "description": "Busca correos en Gmail por texto. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto a buscar"},
                    "max_results": {"type": "integer", "description": "por defecto 5 si se omite"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_calendar_events",
            "description": "Lista los proximos eventos de Google Calendar. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "por defecto 10 si se omite"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files_drive",
            "description": "Busca archivos en Google Drive por nombre. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto a buscar en el nombre del archivo"},
                    "max_results": {"type": "integer", "description": "por defecto 10 si se omite"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_audit",
            "description": (
                "Lanza una auditoria de codigo sobre un repositorio local. Es asincrono: "
                "devuelve un job_id, el resultado llega despues por Telegram. No modifica "
                "el repositorio auditado, solo lo analiza."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta absoluta del repositorio a auditar"},
                },
                "required": ["path"],
            },
        },
    },
    # ---- Fase 2: escritura sobre Centro de Mando -----------------------------
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": (
                "Marca una tarea existente como completada (checkbox hecho). Distinto de "
                "delete_task -- esto NO borra la tarea, solo la marca como hecha. Se "
                "identifica por una palabra clave de su texto, no por indice. Si hay varias "
                "coincidencias, devuelve la lista en vez de marcar la que no toca."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ref": {"type": "string", "description": "Palabra clave que identifica la tarea a completar"},
                },
                "required": ["task_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": (
                "Anade una tarea nueva a un proyecto del Centro de Mando. Usar cuando "
                "el usuario pida crear/anadir/apuntar una tarea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Nombre o id del proyecto, ej. 'tingbot', 'jarvis'"},
                    "text": {"type": "string", "description": "Texto de la tarea"},
                    "priority": {"type": "string", "description": "'high', 'mid' o 'low'. Si no se sabe, usar 'mid'."},
                },
                "required": ["project", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": (
                "Modifica el texto y/o la prioridad de una tarea existente. Se identifica "
                "la tarea por una palabra clave de su texto actual, no por indice. Si hay "
                "varias tareas que coinciden, la herramienta devuelve la lista para que "
                "se lo preguntes a Juan Pablo en vez de adivinar cual es."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ref": {"type": "string", "description": "Palabra clave que identifica la tarea a modificar"},
                    "text": {"type": "string", "description": "Nuevo texto de la tarea. Omitir si no cambia."},
                    "priority": {"type": "string", "description": "Nueva prioridad: 'high', 'mid' o 'low'. Omitir si no cambia."},
                },
                "required": ["task_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": (
                "Elimina una tarea existente. Se identifica por una palabra clave de su "
                "texto, no por indice. Si hay varias coincidencias, devuelve la lista en "
                "vez de borrar la que no toca."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ref": {"type": "string", "description": "Palabra clave que identifica la tarea a eliminar"},
                },
                "required": ["task_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_project_tasks",
            "description": (
                "Borra de golpe TODAS las tareas de un proyecto entero. Usar cuando el "
                "usuario pida vaciar/limpiar/borrar todo un proyecto (ej. 'borra todo lo de "
                "Calafell', 'estoy fuera de esa oposicion, quitala'). Una sola llamada en "
                "vez de muchas delete_task, no hace falta identificar cada tarea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Nombre o id del proyecto a vaciar, ej. 'calafell', 'opos-mataro'"},
                },
                "required": ["project"],
            },
        },
    },
    # ---- Fase 2.5 (05/07/2026): acciones reales con efecto fuera de Jarvis ---
    # A diferencia de Fase 1/2, estas tools mandan mensajes/correos reales o
    # modifican archivos de codigo con commit automatico. No hay paso de
    # confirmacion previo -- decision explicita de Juan Pablo (05/07/2026).
    {
        "type": "function",
        "function": {
            "name": "send_telegram_message",
            "description": (
                "Manda un mensaje de Telegram a Juan Pablo AHORA MISMO, fuera del turno de "
                "chat actual (ej: 'avisame cuando termines', 'mandame esto por telegram'). "
                "No usar para responder al mensaje actual -- para eso ya vale la respuesta "
                "normal del chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Texto del mensaje a enviar"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Envia un correo real desde Gmail (cuenta jarvis.gienini2.1009@gmail.com). "
                "Usar solo cuando el usuario pida explicitamente enviar/mandar un correo y "
                "haya dado destinatario, asunto y cuerpo (si falta algo, preguntalo antes de "
                "llamar a esta tool, no inventes el contenido)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Direccion de correo del destinatario"},
                    "subject": {"type": "string", "description": "Asunto del correo"},
                    "body": {"type": "string", "description": "Cuerpo del correo en texto plano"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": (
                "Crea un evento nuevo en el Google Calendar de Juanpa. Usar cuando "
                "el usuario pida crear/agendar/apuntar un evento o cita."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Titulo del evento"},
                    "start": {
                        "type": "string",
                        "description": "Fecha y hora de inicio en ISO8601 con zona horaria, ej. 2026-07-10T17:00:00+02:00",
                    },
                    "end": {
                        "type": "string",
                        "description": "Fecha y hora de fin en ISO8601. Vacio para usar start + 1 hora.",
                    },
                    "description": {"type": "string", "description": "Descripcion opcional. Vacio si no aplica."},
                },
                "required": ["summary", "start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_calendar_events",
            "description": (
                "Busca eventos en el Google Calendar de Juanpa por texto (titulo, "
                "descripcion o ubicacion) y devuelve su id. Usar como paso previo para "
                "borrar o identificar un evento concreto. Solo lectura."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto a buscar, ej. 'reunion con Luis'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event",
            "description": (
                "Borra un evento del Google Calendar de Juanpa dado su event_id. "
                "Obtener el event_id antes con find_calendar_events. Accion irreversible: "
                "usar solo cuando el usuario pida explicitamente eliminar/borrar un evento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "ID del evento a borrar (de find_calendar_events)"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_alpha50_history",
            "description": (
                "Consulta el historial de entrenamientos de Alpha50 (metodo Fitness 12 "
                "semanas) fuera del flujo especifico de Alpha50 -- usar cuando pregunten "
                "por entrenamientos pasados, si se hizo tal dia, la semana actual del "
                "programa, o el nivel/progreso. Solo lectura."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha": {
                        "type": "string",
                        "description": "Fecha concreta YYYY-MM-DD a consultar. Vacio para traer los ultimos dias.",
                    },
                    "dias": {
                        "type": "integer",
                        "description": "Cuantos dias recientes traer si no se da fecha. Por defecto 14.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repaso_entrenos",
            "description": (
                "Repaso de las metricas REALES de Garmin del entrenamiento: km corridos, "
                "FC media, VO2max, sesiones de fuerza, series y reps, comparando el periodo "
                "actual con el anterior para ver tendencia. Usar cuando pregunten como van "
                "de forma, cuanto han corrido/entrenado, si mejoran, o pidan un repaso. "
                "Complementa a query_alpha50_history (que da el plan/estados). Solo lectura."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dias": {
                        "type": "integer",
                        "description": "Tamano del periodo a repasar en dias (se compara con el periodo previo de igual duracion). Por defecto 7.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_code",
            "description": (
                "Edita codigo de un repositorio conocido de Juan Pablo usando aider (mismo "
                "motor que scripts/aider_review.ps1, pero en modo escritura). Cada llamada "
                "hace UN commit de git independiente y reversible con 'git revert' -- nunca "
                "auto-commits desactivado. Usar solo cuando el usuario pida explicitamente "
                "modificar/arreglar/refactorizar un archivo, dando la ruta y la instruccion "
                "de que cambiar. Nunca usar para ejecutar comandos arbitrarios."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Ruta absoluta del archivo o carpeta a editar (debe ser un repo conocido, ver config/repo_aliases.json)",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "Instruccion concreta de que cambiar, en el mismo estilo que se le daria a aider",
                    },
                },
                "required": ["path", "instruction"],
            },
        },
    },
    # ---- Fase 3 (ADR-0002): autoampliacion supervisada ----------------------
    {
        "type": "function",
        "function": {
            "name": "self_extend",
            "description": (
                "Pone en PRODUCCION un cambio del propio codigo de Jarvis de forma segura: "
                "instala dependencias, reinicia Jarvis para cargar el codigo nuevo y valida "
                "que sigue vivo, con AUTO-REVERT del commit si algo falla. Usar SIEMPRE "
                "DESPUES de edit_code (que ya deja el cambio como un commit) cuando el cambio "
                "sea una capacidad nueva de Jarvis que requiera reiniciar o instalar un paquete "
                "(p.ej. una tool nueva). No usar para editar otros repos de Juan Pablo -- eso "
                "es solo edit_code. Es asincrono: Jarvis se reinicia y avisa por Telegram del "
                "resultado. Si un paquete no esta permitido, esta tool lo dice al momento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Dependencias pip que el codigo nuevo necesita, ej. ['pypdf']. "
                            "Vacio si no hace falta instalar nada. Deben estar en la whitelist."
                        ),
                    },
                    "smoke_tool": {
                        "type": "string",
                        "description": (
                            "Nombre de la tool nueva a ejecutar como prueba real tras reiniciar. "
                            "Si falla, se revierte. Vacio para validar solo que Jarvis arranca."
                        ),
                    },
                    "smoke_args": {
                        "type": "object",
                        "description": "Argumentos para smoke_tool. Vacio si no aplica.",
                    },
                    "label": {
                        "type": "string",
                        "description": "Nombre corto del cambio para el aviso, ej. 'lector de PDF'.",
                    },
                    "repo": {
                        "type": "string",
                        "description": (
                            "Ruta del repo a poner en produccion. Vacio = el propio Jarvis "
                            "(lo normal). Debe ser un repo conocido."
                        ),
                    },
                },
            },
        },
    },
    # ---- Ciberseguridad (08/07/2026): auditoria DEFENSIVA de red propia ------
    {
        "type": "function",
        "function": {
            "name": "start_netscan",
            "description": (
                "Auditoria DEFENSIVA de la red local: descubre e identifica dispositivos y "
                "cruza sus servicios con CVEs (no explota nada). Asincrona: el informe llega "
                "por Telegram. Usar para escanear/auditar la red o buscar vulnerabilidades. "
                "Si el usuario no da subred, llamar con subnet='' para autodetectar. Mapear "
                "lenguaje natural: vulnerabilidades->nse_scripts='vuln,safe', UDP->with_udp, "
                "SO->with_os, ruta/saltos->with_traceroute, rapido->fast, a fondo->"
                "host_discovery='aggressive'. Solo para su red o redes autorizadas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subnet": {
                        "type": "string",
                        "description": "Subred CIDR ej. '192.168.1.0/24'. Vacio para autodetectar la red local.",
                    },
                    "fast": {
                        "type": "boolean",
                        "description": "true para escaneo rapido (menos puertos). Por defecto false.",
                    },
                    "nse_scripts": {
                        "type": "string",
                        "description": (
                            "Scripts NSE defensivos separados por coma. Usar 'vuln,safe' cuando pida "
                            "buscar vulnerabilidades. Permitidos: safe, default, vuln, discovery, "
                            "version, broadcast. Vacio si no lo pide."
                        ),
                    },
                    "with_udp": {
                        "type": "boolean",
                        "description": "true para escanear tambien puertos UDP (DNS, SNMP, NTP, mDNS). Por defecto false.",
                    },
                    "host_discovery": {
                        "type": "string",
                        "description": (
                            "Estrategia de descubrimiento: 'default', 'arp', 'tcp_syn', 'tcp_ack', "
                            "'icmp', 'aggressive', 'none'. Usar 'aggressive' si pide algo a fondo."
                        ),
                    },
                    "timing": {
                        "type": "integer",
                        "description": "Timing nmap 0-5 (0=sigiloso, 4=normal, 5=insane). Por defecto 4.",
                    },
                    "with_traceroute": {
                        "type": "boolean",
                        "description": "true para incluir traceroute (ruta/saltos hasta cada host). Por defecto false.",
                    },
                    "with_os": {
                        "type": "boolean",
                        "description": "true para detectar el sistema operativo. Por defecto false (requiere admin en Windows).",
                    },
                },
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Implementaciones -- Fase 1 (envuelven funciones ya existentes, solo lectura)
# ---------------------------------------------------------------------------


def _project_tasks(term: str, fuzzy: bool) -> list[dict] | None:
    """Tareas del proyecto que denota `term`, o None si `term` no parece un
    proyecto (para que el llamador caiga a busqueda por palabra clave).
    'bitacola'/'acoso'/'jarvis' no son project_id (los ids reales son
    'dragai-tech', 'acoso-laboral'...): se resuelven por alias.
    fuzzy=True permite ademas coincidencia parcial (find_project_id); fuzzy=False
    solo acepta id exacto o alias conocido, para no confundir una palabra clave
    normal ('servidor') con un proyecto."""
    from core.intent import PROJECT_ALIASES
    tasks = find_tasks_by_project(term)          # id exacto
    if tasks:
        return tasks
    pid = PROJECT_ALIASES.get(term.lower())
    if not pid and fuzzy:
        pid = find_project_id(term)
    if pid:
        return find_tasks_by_project(pid)        # [] si el proyecto existe pero no tiene pendientes
    return None                                  # term no es un proyecto conocido


def query_tasks(project: str = "", keyword: str = "") -> list[dict]:
    # El Centro de Mando remoto es la fuente de verdad. Sin este sync, el
    # agente podia responder con una tabla local vacia o antigua tras arrancar.
    try:
        sync_tasks_from_json()
    except Exception:
        # Si Figaro no esta disponible, conservar la ultima copia local sigue
        # siendo mas util que fallar toda la consulta.
        pass
    if not project and not keyword:
        # "que tengo pendiente / que tengo esta semana" sin proyecto concreto.
        return _compact_tasks(find_all_pending())
    tasks = None
    if project:
        tasks = _project_tasks(project, fuzzy=True)
        if tasks is None:                        # el proyecto no existe -> keyword
            tasks = find_tasks_by_keyword(project)
    if not tasks and keyword:
        # El modelo a veces mete el nombre del proyecto en 'keyword'. Si es un
        # proyecto conocido, devolver sus tareas; si no, busqueda por palabra clave.
        tasks = _project_tasks(keyword, fuzzy=False)
        if not tasks:
            tasks = find_tasks_by_keyword(keyword)
    return _compact_tasks(tasks or [])


def _compact_tasks(tasks: list[dict]) -> list[dict]:
    """Solo lo que el agente necesita para responder. Los 7 campos completos
    (id, mando_key, project_id, status...) hacian que 12 tareas pasaran de 2500
    chars y el resultado se truncara -> el modelo creia que no habia tareas."""
    return [{"prioridad": t["priority"], "proyecto": t["project"], "tarea": t["title"]} for t in tasks]


def search_memory(query: str, limit: int = 4, source: str = "") -> list[dict]:
    # Recuerdos enteros (sin recortar): el cap va en numero de resultados.
    mems = search_memories(query, limit=min(limit, 6), source=source or None)
    return [{"recuerdo": m["content"], "similitud": round(m.get("similarity", 0), 2)} for m in mems]


def remember(content: str, topic: str = "nota") -> dict:
    ids = store_memory_chunks(content, source=topic, metadata={"tool": "remember"})
    if not ids or not all(ids):
        return {"error": "No pude guardar (embedding o Postgres no disponible)."}
    return {"ok": True, "memorias_guardadas": len(ids), "topic": topic}


def list_recent_emails(max_results: int = 5) -> list[dict]:
    return get_recent_emails(max_results)


def search_gmail(query: str, max_results: int = 5) -> list[dict]:
    return search_emails(query, max_results)


def list_calendar_events(max_results: int = 10) -> list[dict]:
    return get_upcoming_events(max_results)


def search_files_drive(query: str, max_results: int = 10) -> list[dict]:
    return search_drive_files(query, max_results)


def start_audit(path: str) -> dict:
    from auditor.runner import start_audit_thread
    from auditor.allowed_paths import is_path_allowed, allowed_roots_str

    if not is_path_allowed(path):
        return {
            "error": (
                f"Ruta no permitida: '{path}'. Solo puedo auditar proyectos "
                f"conocidos (config/repo_aliases.json): {allowed_roots_str()}"
            )
        }
    job_id = start_audit_thread(path)
    return {"job_id": job_id, "path": path, "status": "started"}


# ---------------------------------------------------------------------------
# Implementaciones -- Fase 2 (escritura, con validacion antes de ejecutar)
# ---------------------------------------------------------------------------


def _resolve_single_task(task_ref: str) -> dict:
    """Busca la tarea por keyword. Lanza ValueError con la lista de candidatos
    si hay 0 o mas de 1 -- el llamador debe convertir eso en un resultado que
    el LLM pueda leer y usar para preguntar, no para adivinar."""
    # El indice de la tarea (mando_key = 'project_id_idx') es una posicion de
    # array: si el remoto cambio desde el ultimo sync, update/delete tocarian
    # OTRA tarea. Sincronizar aqui antes de resolver reduce esa ventana al
    # minimo (la cache de 30s de load_data).
    try:
        sync_tasks_from_json()
    except Exception:
        pass
    matches = find_tasks_by_keyword(task_ref)
    if not matches:
        # El modelo suele pasar el NOMBRE DEL PROYECTO ('Bitacola') como si fuera
        # la tarea. No casa con ningun titulo -> antes daba "no encontre" y ahi se
        # atascaba. Si es un proyecto, devolver sus tareas para que elija cual.
        proj = _project_tasks(task_ref, fuzzy=True)   # None si no es un proyecto
        if proj:
            titulos = " | ".join(f"'{t['title']}'" for t in proj[:8])
            raise ValueError(
                f"'{task_ref}' es un proyecto con {len(proj)} tarea(s) pendiente(s): {titulos}. "
                f"Para completar/modificar una, usa una palabra de SU texto, no el nombre del proyecto."
            )
        raise ValueError(f"No encontre ninguna tarea pendiente con '{task_ref}'.")
    if len(matches) > 1:
        opciones = [f"[{m['priority']}] {m['project']} -- {m['title']}" for m in matches[:5]]
        raise ValueError(
            f"Hay {len(matches)} tareas que coinciden con '{task_ref}', hace falta mas "
            f"detalle para saber cual: " + " | ".join(opciones)
        )
    return matches[0]


def complete_task(task_ref: str) -> dict:
    from core.tasks import complete_task as _complete_task_db
    try:
        t = _resolve_single_task(task_ref)
    except ValueError as e:
        return {"error": str(e)}
    ok = _complete_task_db(t["mando_key"])
    if not ok:
        return {"error": "No pude marcar la tarea como completada."}
    return {"ok": True, "completada": t["title"], "project": t["project"]}


def add_task(project: str, text: str, priority: str = "mid") -> dict:
    if priority not in ("high", "mid", "low"):
        priority = "mid"
    # find_project_id resuelve tanto nombres naturales ('bitacola') como ids
    # reales ('dragai-tech') -- devuelve el id si el texto coincide con id o
    # titulo. Antes solo se resolvia cuando el nombre no tenia '-'/'_', asi que
    # 'acoso_laboral' se colaba como id literal y el POST daba 404.
    from core.intent import PROJECT_ALIASES
    project_id = PROJECT_ALIASES.get(project.lower()) or find_project_id(project)
    if not project_id:
        return {"error": f"No reconozco el proyecto '{project}'. Dime el nombre exacto del Centro de Mando."}
    result = _mando_add_task(project_id, text, priority)
    sync_tasks_from_json()
    return {"ok": True, "project_id": project_id, "text": text, "priority": priority, "mando_key": result.get("mando_key")}


def update_task(task_ref: str, text: str = None, priority: str = None) -> dict:
    if not text and not priority:
        return {"error": "No hay nada que cambiar -- falta el nuevo texto o la nueva prioridad."}
    try:
        t = _resolve_single_task(task_ref)
    except ValueError as e:
        return {"error": str(e)}
    if priority and priority not in ("high", "mid", "low"):
        priority = None
    project_id, idx = t["mando_key"].rsplit("_", 1)
    _mando_update_task(project_id, int(idx), text=text, priority=priority)
    sync_tasks_from_json()
    return {"ok": True, "titulo_anterior": t["title"], "nuevo_texto": text, "nueva_prioridad": priority}


def delete_task(task_ref: str) -> dict:
    try:
        t = _resolve_single_task(task_ref)
    except ValueError as e:
        return {"error": str(e)}
    project_id, idx = t["mando_key"].rsplit("_", 1)
    _mando_delete_task(project_id, int(idx))
    sync_tasks_from_json()
    return {"ok": True, "eliminada": t["title"], "project": t["project"]}


def delete_project_tasks(project: str) -> dict:
    """Borra de golpe TODAS las tareas de un proyecto. Evita tener que encadenar
    N llamadas a delete_task (que agotaban las vueltas del agente). Borra por
    indice descendente para que quitar una no descuadre los indices menores."""
    from core.intent import PROJECT_ALIASES
    pid = PROJECT_ALIASES.get(project.lower()) or find_project_id(project)
    if not pid:
        return {"error": f"No reconozco el proyecto '{project}'. Dime el nombre exacto del Centro de Mando."}
    tasks = find_tasks_by_project(pid, exclude_done=False)
    if not tasks:
        return {"ok": True, "eliminadas": 0, "project": pid, "nota": "El proyecto no tenia tareas."}
    titulos = [t["title"] for t in tasks]
    # DESC: borrar el indice mas alto primero para no desplazar los menores
    idxs = sorted((int(t["mando_key"].rsplit("_", 1)[1]) for t in tasks), reverse=True)
    for idx in idxs:
        _mando_delete_task(pid, idx)
    sync_tasks_from_json()
    return {"ok": True, "eliminadas": len(idxs), "project": pid, "titulos": titulos}


# ---------------------------------------------------------------------------
# Implementaciones -- Fase 2.5 (05/07/2026): acciones reales fuera de Jarvis
# ---------------------------------------------------------------------------


def send_telegram_message(text: str) -> dict:
    if not text or not text.strip():
        return {"error": "El mensaje esta vacio."}
    ok = _send_telegram_message(text)
    if not ok:
        return {"error": "No se pudo mandar el mensaje -- ver logs de connectors/relay_client.py."}
    return {"ok": True, "enviado": text}


def send_email(to: str, subject: str, body: str) -> dict:
    if not to or "@" not in to:
        return {"error": f"'{to}' no parece una direccion de correo valida."}
    if not subject or not body:
        return {"error": "Falta asunto o cuerpo del correo -- no se envia nada a medias."}
    ok = _send_email(to, subject, body)
    if not ok:
        return {"error": "Gmail rechazo el envio -- ver logs de connectors/google_tools.py."}
    return {"ok": True, "to": to, "subject": subject}


def create_calendar_event(summary: str, start: str, end: str = "", description: str = "") -> dict:
    from datetime import datetime, timedelta

    if not summary or not start:
        return {"error": "Falta el titulo o la fecha de inicio del evento."}
    if not end:
        try:
            start_dt = datetime.fromisoformat(start)
            end = (start_dt + timedelta(hours=1)).isoformat()
        except ValueError:
            return {"error": f"No pude interpretar la fecha de inicio '{start}' (se espera ISO8601 con zona horaria)."}
    ok = _create_event(summary=summary, start=start, end=end, description=description)
    if not ok:
        return {"error": "Google Calendar rechazo la creacion del evento."}
    return {"ok": True, "summary": summary, "start": start, "end": end}


def find_calendar_events(query: str) -> dict:
    if not query:
        return {"error": "Falta el texto de busqueda."}
    try:
        events = _find_events(query)
    except Exception as e:
        return {"error": f"No pude buscar eventos: {e}"}
    if not events:
        return {"ok": True, "events": [], "msg": f"No hay eventos que coincidan con '{query}'."}
    return {"ok": True, "events": events}


def delete_calendar_event(event_id: str) -> dict:
    if not event_id:
        return {"error": "Falta el event_id del evento a borrar."}
    try:
        _delete_event(event_id)
    except Exception as e:
        return {"error": f"Google Calendar rechazo el borrado: {e}"}
    return {"ok": True, "deleted": event_id}


def query_alpha50_history(fecha: str = "", dias: int = 14) -> dict:
    from alpha50.history_reader import get_historial
    return get_historial(fecha=fecha, dias=dias)


def repaso_entrenos(dias: int = 7) -> dict:
    try:
        from alpha50.garmin_actividades import repaso
    except Exception as e:
        return {"error": f"No puedo cargar el modulo de actividades Garmin: {e}"}
    try:
        return repaso(dias=max(1, min(int(dias or 7), 90)))
    except Exception as e:
        return {"error": f"Fallo al hacer el repaso de entrenos: {e}"}


def start_netscan(
    subnet: str = "",
    fast: bool = False,
    nse_scripts: str = "",
    with_udp: bool = False,
    host_discovery: str = "default",
    timing: int = 4,
    with_traceroute: bool = False,
    with_os: bool = False,
) -> dict:
    """Lanza el escaneo de red defensivo en un hilo aparte (como start_audit) y
    devuelve enseguida. El informe completo se manda por Telegram al terminar.
    No explota vulnerabilidades: descubre, identifica y cruza con CVEs."""
    import threading
    from netscan import report as _netscan_report

    sub = subnet.strip() or None
    scripts = nse_scripts.strip() or None
    threading.Thread(
        target=lambda: _netscan_report.run_scan(
            subnet=sub, fast=fast, with_cve=True, notify=True,
            nse_scripts=scripts, with_udp=with_udp,
            host_discovery=host_discovery, timing=timing,
            with_traceroute=with_traceroute, with_os=with_os,
        ),
        daemon=True,
    ).start()
    modos = [m for m, on in (
        ("vuln/NSE", bool(scripts)), ("UDP", with_udp),
        ("OS", with_os), ("traceroute", with_traceroute),
        ("rapido", fast),
    ) if on]
    return {
        "status": "started",
        "subnet": subnet or "auto",
        "opciones": modos or ["estandar"],
        "nota": "Escaneo en curso; el informe llegara por Telegram en 1-3 minutos.",
    }


def edit_code(path: str, instruction: str) -> dict:
    """Invoca aider en modo escritura (auto-commits activo) sobre una ruta
    conocida. Cada llamada = un commit de git independiente, reversible con
    'git revert <hash>'. Reutiliza el mismo whitelist que start_audit (Fase 1)
    para no permitir que el LLM edite una ruta arbitraria del disco."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    from config.settings import settings
    from auditor.allowed_paths import is_path_allowed, allowed_roots_str

    if not is_path_allowed(path):
        return {
            "error": (
                f"Ruta no permitida: '{path}'. Solo puedo editar proyectos "
                f"conocidos (config/repo_aliases.json): {allowed_roots_str()}"
            )
        }
    target = Path(path)
    if not target.exists():
        return {"error": f"La ruta '{path}' no existe."}
    if not instruction or not instruction.strip():
        return {"error": "Falta la instruccion de que cambiar."}

    repo_root = target if target.is_dir() else target.parent
    try:
        head_before = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        head_before = None
    if not head_before:
        return {
            "error": (
                f"'{repo_root}' no parece un repositorio git (o git no esta disponible). "
                "edit_code exige que cada cambio sea un commit reversible -- no se ejecuta sin git."
            )
        }

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "aider",
                # Modelos desde settings (.env / defaults), no hardcodeados: si Groq
                # retira uno, se cambia en un solo sitio y edit_code lo sigue.
                "--model", f"groq/{settings.GROQ_MODEL_GENERAL}",
                "--editor-model", f"groq/{settings.GROQ_MODEL_CODE}",
                # Sin interfaz interactiva: Jarvis corre aider como servicio (sin
                # consola) y prompt_toolkit reventaba ("expecting a Windows console").
                "--no-pretty",
                "--no-fancy-input",
                "--no-stream",
                "--yes",
                "--auto-commits",
                "--message", instruction,
                str(target),
            ],
            cwd=str(repo_root),
            capture_output=True, text=True, timeout=300,
            # aider (litellm) lee GROQ_API_KEY del ENTORNO; Jarvis la tiene en
            # settings (.env via Pydantic), no en os.environ -> hay que inyectarla.
            # PYTHONUTF8/IOENCODING: aider imprime Unicode (▶, emojis) y el cp1252
            # de Windows lo reventaba con UnicodeEncodeError.
            env={
                **os.environ,
                "GROQ_API_KEY": settings.GROQ_API_KEY,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )
    except subprocess.TimeoutExpired:
        return {"error": "aider tardo mas de 300s -- probablemente colgado, revisar a mano."}
    except FileNotFoundError:
        return {"error": "No se encontro el modulo aider en este entorno (pip install aider-chat)."}

    head_after = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()

    committed = bool(head_after) and head_after != head_before
    output_tail = (result.stdout or "")[-2000:]

    if result.returncode != 0 and not committed:
        return {
            "error": f"aider fallo (returncode {result.returncode}) y no hizo commit.",
            "output": output_tail,
        }
    if not committed:
        return {
            "ok": False,
            "mensaje": "aider corrio sin error pero no hizo ningun cambio (nada que commitear).",
            "output": output_tail,
        }
    return {
        "ok": True,
        "commit": head_after,
        "revert_con": f"git revert {head_after}",
        "output": output_tail,
    }


def self_extend(
    packages: list = None,
    smoke_tool: str = "",
    smoke_args: dict = None,
    label: str = "cambio",
    repo: str = "",
    commit: str = "",
) -> dict:
    """Lanza el bucle de autoampliacion supervisada (ADR-0002) sobre un commit ya
    hecho por edit_code. Reusa la whitelist de rutas de start_audit/edit_code y
    pre-chequea la whitelist de paquetes AQUI para que el LLM reciba el fallo al
    instante (el proceso detached solo avisa por Telegram)."""
    import subprocess
    from pathlib import Path
    from auditor.allowed_paths import is_path_allowed, allowed_roots_str
    from core import self_extend as se

    repo = repo or str(Path(__file__).resolve().parent.parent)   # por defecto, el propio Jarvis
    if not is_path_allowed(repo):
        return {"error": f"Ruta no permitida: '{repo}'. Repos conocidos: {allowed_roots_str()}"}

    packages = packages or []
    smoke_args = smoke_args or {}

    prohibidos = [p for p in packages if not se.is_package_allowed(p)]
    if prohibidos:
        return {
            "error": (
                f"Paquete(s) no permitido(s): {', '.join(prohibidos)}. Hay que anadirlos a "
                f"config/allowed_packages.json antes de que Jarvis pueda instalarlos."
            )
        }

    # commit a poner en produccion = el que dejo edit_code (HEAD por defecto);
    # base = su padre, a donde volver si el revert se dispara.
    commit = commit or se.git_head(repo)
    if not commit:
        return {"error": f"'{repo}' no parece un repositorio git con commits."}
    base = subprocess.run(
        ["git", "-C", repo, "rev-parse", f"{commit}~1"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not base:
        return {"error": "No pude determinar el commit anterior (base) para un posible revert."}

    plan = se.SelfExtendPlan(
        base_commit=base, commit=commit, packages=packages,
        smoke_tool=smoke_tool, smoke_args=smoke_args, label=label, repo=repo,
    )
    return se.launch_supervised(plan)


FUNCTIONS = {
    "query_tasks": query_tasks,
    "search_memory": search_memory,
    "remember": remember,
    "list_recent_emails": list_recent_emails,
    "search_gmail": search_gmail,
    "list_calendar_events": list_calendar_events,
    "search_files_drive": search_files_drive,
    "start_audit": start_audit,
    "complete_task": complete_task,
    "add_task": add_task,
    "update_task": update_task,
    "delete_task": delete_task,
    "delete_project_tasks": delete_project_tasks,
    "send_telegram_message": send_telegram_message,
    "send_email": send_email,
    "create_calendar_event": create_calendar_event,
    "find_calendar_events": find_calendar_events,
    "delete_calendar_event": delete_calendar_event,
    "query_alpha50_history": query_alpha50_history,
    "repaso_entrenos": repaso_entrenos,
    "edit_code": edit_code,
    "self_extend": self_extend,
    "start_netscan": start_netscan,
}


def call_tool(name: str, arguments: dict):
    """Ejecuta una tool por nombre. Nunca lanza excepcion -- el error vuelve como
    resultado para que el LLM lo vea y pueda reaccionar (reintentar, pedir mas info, etc)."""
    fn = FUNCTIONS.get(name)
    if not fn:
        return {"error": f"Herramienta desconocida: {name}"}
    try:
        return fn(**arguments)
    except Exception as e:
        return {"error": str(e)}
