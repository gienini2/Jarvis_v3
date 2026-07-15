"""
core/backend_state.py
Rastrea que backend LLM respondio la peticion EN CURSO (Groq / NVIDIA / qwen
local), para poder etiquetar cada respuesta con la IA que la genero.

Es thread-local a proposito: cada peticion (API FastAPI, poll del relay, REPL
local) corre en su propio hilo y tiene su propio valor sin pisar el de otra
peticion concurrente. Un global normal daria carreras entre el chat local y un
mensaje de Telegram llegando a la vez.

Uso:
    from core import backend_state
    backend_state.reset()             # al empezar a procesar un mensaje
    backend_state.set_backend("groq") # dentro del generador que respondio
    backend_state.get_backend()       # "groq" | "nvidia" | "qwen-local" | "local"
"""
import threading

DEFAULT = "local"  # sin LLM (respuesta por reglas: alpha50, intents deterministas)

_state = threading.local()


def reset() -> None:
    _state.name = DEFAULT


def set_backend(name: str) -> None:
    _state.name = name


def get_backend() -> str:
    return getattr(_state, "name", DEFAULT)
