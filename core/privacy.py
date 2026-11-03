"""Privacidad: contenido privado y MODO PRIVADO. Lo privado solo lo toca el modelo local y no se guarda.

- Modo privado (persistente): `/privado` lo activa, `/publico` lo desactiva; `/privado <mensaje>` lo aplica a un solo mensaje.
- Herramienta privada (PRIVATE_TOOLS o resultado con "_privado": true): desde ese momento el resto del turno es local.
En ambos casos el router solo admite proveedores locales (falla antes que usar la nube), la transcripcion de voz
(Groq) se bloquea y el procesador no guarda ni el mensaje ni la respuesta en la memoria ni en el historial.
"""
import threading
from pathlib import Path

LOCAL_PROVIDERS = {"ollama"}
PRIVATE_TOOLS: set[str] = {"resumir_chat", "redactar_como_yo"}
PLACEHOLDER = "[respuesta privada: no se guarda]"
PLACEHOLDER_USER = "[mensaje privado: no se guarda]"
MAX_PRIVATE_RESULT_CHARS = 5000   # el contexto local es de 4096 tokens
FLAG = Path(__file__).resolve().parent.parent / "data" / "modo_privado.flag"

_state = threading.local()


def mode_on() -> bool:
    return FLAG.exists()


def set_mode(on: bool) -> None:
    if on:
        FLAG.parent.mkdir(exist_ok=True)
        FLAG.write_text("1")
    else:
        FLAG.unlink(missing_ok=True)


def is_private(tool_name: str, result) -> bool:
    return tool_name in PRIVATE_TOOLS or (isinstance(result, dict) and bool(result.get("_privado")))


def force_local(value: bool = True) -> None:
    _state.forced = value


def is_forced() -> bool:
    return bool(getattr(_state, "forced", False))


def mark_private() -> None:
    _state.private = True
    _state.forced = True


def is_private_turn() -> bool:
    return is_forced() or bool(getattr(_state, "private", False))


def reset() -> None:
    _state.private = False
    _state.forced = False


def pop_private() -> bool:
    value = is_private_turn()
    reset()
    return value
