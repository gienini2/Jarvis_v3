import os
from datetime import datetime, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config.settings import settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
]


def get_google_service(service_name: str, version: str):
    creds = None
    if os.path.exists(settings.GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(settings.GOOGLE_TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.GOOGLE_CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(settings.GOOGLE_TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    return build(service_name, version, credentials=creds)


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def get_recent_emails(max_results: int = 10) -> list[dict]:
    service = get_google_service("gmail", "v1")
    results = service.users().messages().list(userId="me", maxResults=max_results).execute()
    messages = results.get("messages", [])
    emails = []
    for msg in messages:
        detail = service.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        emails.append({
            "id": msg["id"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
        })
    return emails


def send_email(to: str, subject: str, body: str) -> bool:
    import base64
    from email.mime.text import MIMEText
    service = get_google_service("gmail", "v1")
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return True


def search_emails(query: str, max_results: int = 5) -> list[dict]:
    service = get_google_service("gmail", "v1")
    results = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    messages = results.get("messages", [])
    emails = []
    for msg in messages:
        detail = service.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        emails.append({
            "id": msg["id"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
        })
    return emails


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def get_upcoming_events(max_results: int = 10) -> list[dict]:
    service = get_google_service("calendar", "v3")
    now = datetime.now(timezone.utc).isoformat()
    
    # Obtener todos los calendarios
    calendars = service.calendarList().list().execute()
    
    all_events = []
    for cal in calendars.get("items", []):
        events_result = service.events().list(
            calendarId=cal["id"],
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        for e in events_result.get("items", []):
            all_events.append({
                "summary": e.get("summary", "Sin título"),
                "start": e["start"].get("dateTime", e["start"].get("date")),
                "end": e["end"].get("dateTime", e["end"].get("date")),
                "calendar": cal["summary"],
            })

    # Ordenar por fecha
    all_events.sort(key=lambda x: x["start"])
    return all_events[:max_results]


def create_event(summary: str, start: str, end: str, description: str = "",
                 calendar_id: str = "") -> bool:
    service = get_google_service("calendar", "v3")
    calendar_id = calendar_id or settings.GOOGLE_DEFAULT_CALENDAR_ID
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start, "timeZone": "Europe/Madrid"},
        "end": {"dateTime": end, "timeZone": "Europe/Madrid"},
    }
    service.events().insert(calendarId=calendar_id, body=event).execute()
    return True


def find_events(query: str, max_results: int = 10, calendar_id: str = "") -> list[dict]:
    """Busca eventos por texto (titulo/descripcion/ubicacion) para poder borrarlos.
    Devuelve id + datos basicos. Solo lectura."""
    service = get_google_service("calendar", "v3")
    calendar_id = calendar_id or settings.GOOGLE_DEFAULT_CALENDAR_ID
    now = datetime.now(timezone.utc).isoformat()
    events_result = service.events().list(
        calendarId=calendar_id,
        q=query,
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    out = []
    for e in events_result.get("items", []):
        out.append({
            "id": e["id"],
            "summary": e.get("summary", "Sin titulo"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date")),
        })
    return out


def delete_event(event_id: str, calendar_id: str = "") -> bool:
    service = get_google_service("calendar", "v3")
    calendar_id = calendar_id or settings.GOOGLE_DEFAULT_CALENDAR_ID
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return True


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------

def list_drive_files(max_results: int = 10) -> list[dict]:
    service = get_google_service("drive", "v3")
    results = service.files().list(
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime)",
    ).execute()
    return results.get("files", [])


def search_drive_files(query: str, max_results: int = 10) -> list[dict]:
    service = get_google_service("drive", "v3")
    # Escapar \ y ' o una comilla en la busqueda rompe la query de Drive.
    safe = query.replace("\\", "\\\\").replace("'", "\\'")
    results = service.files().list(
        q=f"name contains '{safe}'",
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime)",
    ).execute()
    return results.get("files", [])


# ---------------------------------------------------------------------------
# Dispatcher — el LLM llama a esto
# ---------------------------------------------------------------------------

def handle_google_request(intent_type: str, message: str) -> str:
    if intent_type == "google_gmail":
        if any(w in message.lower() for w in ["envía", "envia", "manda", "escribe"]):
            return "Para enviar un correo necesito: destinatario, asunto y cuerpo. ¿Me los das?"
        if any(w in message.lower() for w in ["busca", "encuentra"]):
            emails = search_emails(message)
        else:
            emails = get_recent_emails(5)
        if not emails:
            return "No hay correos recientes."
        lines = "\n".join(f"- {e['date'][:16]} | {e['from']} | {e['subject']}" for e in emails)
        return f"Últimos correos:\n{lines}"

    elif intent_type == "google_calendar":
        msg_lower = message.lower()
        
        if any(w in msg_lower for w in ["crea", "añade", "agrega", "añadir", "agregar", "crear"]):
            # Intentar extraer datos del mensaje con el LLM
            from core.llm import generate
            extraction_prompt = f"""Extrae del siguiente mensaje los datos para crear un evento de Google Calendar.
    Responde SOLO con un JSON válido con estas claves exactas:
    - "summary": título del evento (string)
    - "start": fecha y hora inicio en formato ISO8601 con zona horaria, ejemplo: "2026-06-17T17:45:00+02:00"
    - "end": fecha y hora fin en formato ISO8601 (si no se especifica, suma 1 hora al inicio)
    - "description": descripción opcional (string vacío si no hay)

    Fecha y hora actual: {datetime.now().astimezone().isoformat(timespec='minutes')}.
    Calcula las referencias relativas ("hoy", "mañana", "este martes") con
    respecto a esa fecha; no uses fechas de ejemplo ni supongas un año fijo.

    Mensaje: "{message}"

    Responde SOLO el JSON, sin explicaciones ni backticks."""

            raw = generate(extraction_prompt)
            
            import json, re
            try:
                # Limpiar posibles backticks
                clean = re.sub(r"```json|```", "", raw).strip()
                data = json.loads(clean)
                
                ok = create_event(
                    summary=data["summary"],
                    start=data["start"],
                    end=data["end"],
                    description=data.get("description", ""),
                )
                if ok:
                    return f"✅ Evento creado: '{data['summary']}' el {data['start'][:16].replace('T', ' a las ')}"
                return "❌ No pude crear el evento en Google Calendar."
            except Exception as e:
                return f"❌ No pude interpretar los datos del evento: {e}\nRaw: {raw[:200]}"
        
        # Listar eventos
        events = get_upcoming_events(5)
        if not events:
            return "No hay eventos próximos en el calendario."
        lines = "\n".join(f"- {e['start'][:16]} | {e['summary']} ({e.get('calendar','')})" for e in events)
        return f"Próximos eventos:\n{lines}"

    elif intent_type == "google_drive":
        if any(w in message.lower() for w in ["busca", "encuentra", "dame"]):
            words = message.lower().split()
            keyword = words[-1] if words else ""
            files = search_drive_files(keyword)
        else:
            files = list_drive_files(10)
        if not files:
            return "No encontré archivos en Drive."
        lines = "\n".join(f"- {f['name']} ({f['mimeType'].split('.')[-1]})" for f in files)
        return f"Archivos en Drive:\n{lines}"

    return "No entendí qué quieres hacer con Google."
