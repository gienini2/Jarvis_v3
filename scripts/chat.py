import sys
import os
import re
import time
import logging
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.processor import process
from core.llm import generate_stream
from core.rag import search_memories
from connectors.google_tools import send_email

sys.stdout.reconfigure(encoding="utf-8")

# Este es un chat interactivo -- los warnings de fondo (p.ej. Figaro caido)
# no deben interrumpir la conversacion. Se guardan en logs/chat.log para
# poder diagnosticar despues sin ensuciar la pantalla.
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    filename=os.path.join("logs", "chat.log"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

JARVIS_URL = "http://127.0.0.1:3000"

def _startup_banner() -> str:
    """Muestra los modelos reales y ordenados del camino tool-calling."""
    try:
        from core.llm_types import LLMRequest
        from core import llm_router

        requirements = llm_router._requirements_from_request(
            LLMRequest(prompt=[], tools=[{}])
        )
        candidates = llm_router.find_models(requirements, ignore_health=True)
        return " > ".join(
            f"{candidate['provider']} ({candidate['model']})"
            for candidate in candidates
        )
    except Exception:
        return "Groq (openai/gpt-oss-120b) > NVIDIA > Ollama local"


print("Jarvis listo -- LLM por router: " + _startup_banner())
print("Cada respuesta se etiqueta con el backend real: [groq] / [nvidia] / [qwen-local]")
print("Escribe 'exit' para salir\n")

_pending_email = {}
_last_message  = ""  # guarda el último mensaje para /aprende

SEND_KEYWORDS = ["envía", "envia", "envíes", "envies", "manda", "mandes", "mandas", "escribe", "send"]

# Efecto maquina de escribir: imprime la respuesta palabra a palabra,
# como el streaming de un LLM. Delay pequeño para no hacerse pesado
# en respuestas largas.
TYPE_DELAY = 0.02  # segundos entre palabras


def type_out(text):
    for word in text.split(" "):
        print(word, end=" ", flush=True)
        time.sleep(TYPE_DELAY)
    print("\n")


def is_send_intent(text):
    return any(w in text.lower() for w in SEND_KEYWORDS)


def is_google_intent(text):
    keywords = ["correo", "mail", "email", "gmail", "calendario", "calendar", "evento", "cita", "agenda", "drive", "archivo", "documento"]
    return any(w in text.lower() for w in keywords)


def extract_email_parts(text):
    to_match   = re.search(r"(?:a|para)\s+(\S+@\S+)", text, re.IGNORECASE)
    subj_match = re.search(r"(?:asunto|subject)[:\s=]+[\"']?(.+?)[\"']?\s*(?:\n|$)", text, re.IGNORECASE)
    body_match = re.search(r"(?:diga|diciendo|que\s+diga|cuerpo|body|texto|contenido)[:\s=]+[\"']?(.+?)[\"']?\s*(?:\n|como\s+asunto|$)", text, re.IGNORECASE | re.DOTALL)
    return (
        to_match.group(1) if to_match else None,
        subj_match.group(1).strip() if subj_match else None,
        body_match.group(1).strip() if body_match else None,
    )


def handle_aprende(user_input):
    """Procesa /aprende <intent> — guarda el último mensaje con el intent correcto."""
    parts = user_input.strip().split(maxsplit=1)
    if len(parts) < 2:
        print("Uso: /aprende <intent>  (ejemplo: /aprende code)\n")
        return
    intent = parts[1].strip()
    if not _last_message:
        print("No hay mensaje anterior que corregir.\n")
        return
    try:
        resp = requests.post(
            f"{JARVIS_URL}/aprende",
            json={"message": _last_message, "intent": intent},
            timeout=5
        )
        if resp.status_code == 200:
            print(f"✅ Guardado: '{_last_message[:60]}' → {intent}\n")
        else:
            print(f"❌ Error al guardar: {resp.text}\n")
    except Exception as e:
        print(f"❌ No se pudo conectar con Jarvis: {e}\n")


while True:
    try:
        user_input = input("Juanpa: ")
    except (KeyboardInterrupt, EOFError):
        print("\nChat cerrado.")
        break

    if user_input.lower() == "exit":
        break

    # Comando /aprende
    if user_input.strip().startswith("/aprende"):
        handle_aprende(user_input)
        continue

    print("\nJarvis: ", end="", flush=True)

    # Email pendiente
    if _pending_email.get("waiting"):
        to, subj, body = extract_email_parts(user_input)
        if to and body:
            send_email(to, subj or "Sin asunto", body)
            response = f"Correo enviado a {to}."
            _pending_email.clear()
        else:
            response = "Necesito destinatario y cuerpo del mensaje."
        type_out(response)
        continue

    # Email directo
    if is_google_intent(user_input) and is_send_intent(user_input):
        to, subj, body = extract_email_parts(user_input)
        if to and body:
            send_email(to, subj or "Sin asunto", body)
            response = f"Correo enviado a {to}."
        else:
            response = "Para enviar el correo necesito destinatario y contenido."
            _pending_email["waiting"] = True
        type_out(response)
        continue

    # Flujo normal — guarda el mensaje para posible /aprende
    _last_message = user_input
    try:
        response, intent_type = process(user_input)
    except KeyboardInterrupt:
        print("\nChat cancelado.")
        break
    except Exception as e:
        # El chat interactivo nunca debe morir por un fallo puntual de
        # proveedores LLM. Detalle completo en logs/chat.log.
        logging.getLogger("jarvis.chat").exception("process() fallo")
        response = f"[error] No pude procesar el mensaje ({e}). Detalle en logs\\chat.log."
    type_out(response)
