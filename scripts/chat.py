import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import generate_stream
from core.memory import save_message
from core.intent import classify
from connectors.google_tools import handle_google_request, send_email

sys.stdout.reconfigure(encoding="utf-8")

print("Jarvis listo (RTX 5050 GPU)")
print("Escribe 'exit' para salir\n")

_pending_email = {}

SEND_KEYWORDS = ["envía", "envia", "envíes", "envies", "manda", "mandes", "mandas", "escribe", "envia", "send"]


def is_send_intent(text: str) -> bool:
    return any(w in text.lower() for w in SEND_KEYWORDS)


def is_google_intent(text: str) -> bool:
    keywords = [
        "correo", "mail", "email", "gmail",
        "calendario", "calendar", "evento", "cita", "agenda",
        "drive", "archivo", "documento", "fichero",
    ]
    return any(w in text.lower() for w in keywords)


def extract_email_parts(text: str):
    to_match = re.search(r"(?:a|para)\s+(\S+@\S+)", text, re.IGNORECASE)
    subj_match = re.search(
        r"(?:asunto|subject)[:\s=]+[\"']?(.+?)[\"']?\s*(?:\n|$)",
        text, re.IGNORECASE
    )
    body_match = re.search(
        r"(?:diga|diciendo|que\s+diga|cuerpo|body|texto|contenido)[:\s=]+[\"']?(.+?)[\"']?\s*(?:\n|como\s+asunto|$)",
        text, re.IGNORECASE | re.DOTALL
    )
    return (
        to_match.group(1) if to_match else None,
        subj_match.group(1).strip() if subj_match else None,
        body_match.group(1).strip() if body_match else None,
    )


while True:
    print("Juanpa: (poner END al final de todo)")
    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)

    user_input = "\n".join(lines)

    if user_input.lower() == "exit":
        break

    save_message("user", user_input)
    print("\nJarvis: ", end="", flush=True)

    # Flujo pendiente: esperando datos para enviar mail
    if _pending_email.get("waiting"):
        to, subj, body = extract_email_parts(user_input)
        if to and body:
            send_email(to, subj or "Sin asunto", body)
            response = f"Correo enviado a {to}."
            _pending_email.clear()
        else:
            response = "Necesito al menos: destinatario (email) y cuerpo del mensaje."
        print(response + "\n")
        save_message("assistant", response)
        continue

    # Detección directa sin depender solo de classify()
    if is_google_intent(user_input):
        if is_send_intent(user_input):
            to, subj, body = extract_email_parts(user_input)
            if to and body:
                send_email(to, subj or "Sin asunto", body)
                response = f"Correo enviado a {to}."
            else:
                response = "Para enviar el correo necesito destinatario y contenido. ¿Me los das?\nFormato: para: email | asunto: texto | cuerpo: texto"
                _pending_email["waiting"] = True
        else:
            intent = classify(user_input)
            if intent.type in ("google_gmail", "google_calendar", "google_drive"):
                response = handle_google_request(intent.type, user_input)
            elif "mail" in user_input.lower() or "correo" in user_input.lower():
                response = handle_google_request("google_gmail", user_input)
            elif "calendario" in user_input.lower() or "agenda" in user_input.lower():
                response = handle_google_request("google_calendar", user_input)
            elif "drive" in user_input.lower() or "archivo" in user_input.lower():
                response = handle_google_request("google_drive", user_input)
            else:
                response = handle_google_request("google_gmail", user_input)

        print(response + "\n")
        save_message("assistant", response)

    else:
        response = generate_stream(user_input)
        print("\n")
        save_message("assistant", response)