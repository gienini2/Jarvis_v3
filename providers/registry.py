from providers.cerebras import CerebrasProvider
from providers.groq import GroqProvider
from providers.nvidia import NvidiaProvider
from providers.ollama import OllamaProvider
from providers.kimi import KimiProvider


PROVIDERS = {
    "groq": GroqProvider(),
    "nvidia": NvidiaProvider(),
    "ollama": OllamaProvider(),
    "kimi": KimiProvider(),
    "cerebras": CerebrasProvider(),
}
