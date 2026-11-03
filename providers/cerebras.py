from config.settings import settings
from providers.groq import GroqProvider


class CerebrasProvider(GroqProvider):
    """Cerebras: API compatible con OpenAI y misma mecanica que Groq (inferencia muy rapida, plan gratuito)."""
    name = "cerebras"
    URL = "https://api.cerebras.ai/v1/chat/completions"
    MODELS_URL = "https://api.cerebras.ai/v1/models"

    def _api_key(self):
        return settings.CEREBRAS_API_KEY
