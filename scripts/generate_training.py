"""
scripts/generate_training.py
Usa Groq para clasificar mensajes reales de la BD y generar training_data.json robusto.
"""
import sys, os, json, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import get_connection
from config.settings import settings

INTENTS = [
    "complete_task", "create_task", "query_task",
    "google_gmail", "google_calendar", "google_drive",
    "mando_add_task", "audit", "remote_audit", "memory_search", "general"
]

SYSTEM = f"""Clasifica mensajes de usuario en uno de estos intents: {', '.join(INTENTS)}

Reglas:
- complete_task: marcar tarea como hecha
- create_task: crear nueva tarea o recordatorio
- query_task: preguntar por tareas pendientes de un proyecto
- google_gmail: leer o enviar correos
- google_calendar: ver o crear eventos en calendario
- google_drive: buscar archivos en drive
- mando_add_task: aÃ±adir tarea a un proyecto del Centro de Mando
- audit: auditar/analizar codigo de un repo LOCAL
- remote_audit: auditar codigo de un servidor remoto (figaro)
- memory_search: buscar en conversaciones o chats anteriores
- general: cualquier otra cosa (preguntas, saludos, analisis de informes ya hechos)

IMPORTANTE: si el mensaje habla de "dado el informe" o "que cambios harias" o "que mejorarÃ­as" -> general
IMPORTANTE: si el mensaje es un saludo con otra pregunta aÃ±adida -> clasifica por la pregunta, no el saludo

Responde SOLO con el nombre del intent, sin explicacion."""

def classify_with_groq(message: str) -> str:
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": settings.GROQ_MODEL_GENERAL,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": message[:200]}
                ],
                "temperature": 0,
                "max_tokens": 20,
            },
            timeout=15,
        )
        r.raise_for_status()
        intent = r.json()["choices"][0]["message"]["content"].strip().lower()
        return intent if intent in INTENTS else "general"
    except Exception as e:
        print(f"  ERROR: {e}")
        return "general"

def main():
    # Cargar training_data.json existente
    path = "config/training_data.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Obtener mensajes de BD
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT message FROM intents WHERE message IS NOT NULL AND LENGTH(message) > 5 LIMIT 200")
    messages = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()

    print(f"Clasificando {len(messages)} mensajes con Groq...")
    added = 0

    for msg in messages:
        msg_clean = msg.strip()
        if not msg_clean:
            continue

        # Verificar si ya estÃ¡ en training_data
        already = any(msg_clean in examples for examples in data.values())
        if already:
            continue

        intent = classify_with_groq(msg_clean)
        if intent not in data:
            data[intent] = []
        data[intent].append(msg_clean)
        added += 1
        print(f"  [{intent}] {msg_clean[:60]}")

    # Guardar
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nAnadidos {added} ejemplos. Reentrenando...")
    from core.intent_ml import train
    train()
    print("Listo.")

if __name__ == "__main__":
    main()
