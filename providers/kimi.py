from providers.base import BaseProvider
from core.llm_types import ProviderResult


class KimiProvider(BaseProvider):
    name = "kimi"

    def chat(self, request):
        return ProviderResult(self.name, request.model, False, 0.0, None, NotImplementedError())

    def chat_tools(self, request):
        return ProviderResult(self.name, request.model, False, 0.0, None, NotImplementedError())

    def health(self):
        return False
