"""Canal por el que llega el turno actual (hilo-local): 'voz' pide respuestas cortas para leerlas en alto."""
import threading

_state = threading.local()

VOICE_HINT = ("\n\nMODO VOZ: tu respuesta se lee en voz alta. Contesta en una o dos frases cortas y naturales, sin listas, markdown ni emojis. "
              "Si te piden datos en lista o tabla puedes incluirla (se muestra en pantalla), pero lo que dices antes es una sola frase.")


def set_channel(name: str):
    _state.name = name or ""


def is_voice() -> bool:
    return getattr(_state, "name", "") == "voz"


def reset():
    _state.name = ""
