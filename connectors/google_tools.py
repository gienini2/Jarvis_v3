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
    events_result = service.events().list(
        calendarId="primary",
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = events_result.get("items", [])
    return [
        {
            "summary": e.get("summary", "Sin título"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date")),
        }
        for e in events
    ]


def create_event(summary: str, start: str, end: str, description: str = "") -> bool:
    service = get_google_service("calendar", "v3")
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start, "timeZone": "Europe/Madrid"},
        "end": {"dateTime": end, "timeZone": "Europe/Madrid"},
    }
    service.events().insert(calendarId="primary", body=event).execute()
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
    results = service.files().list(
        q=f"name contains '{query}'",
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
        if any(w in message.lower() for w in ["crea", "añade", "agrega"]):
            return "Para crear un evento necesito: título, fecha/hora de inicio y fin. ¿Me los das?"
        events = get_upcoming_events(5)
        if not events:
            return "No hay eventos próximos en el calendario."
        lines = "\n".join(f"- {e['start'][:16]} | {e['summary']}" for e in events)
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