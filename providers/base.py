from abc import ABC, abstractmethod

import requests


class BaseProvider(ABC):
    name = ""
    supports_tools = False
    supports_stream = False
    supports_embeddings = False

    @abstractmethod
    def chat(self, request):
        pass

    @abstractmethod
    def chat_tools(self, request):
        pass

    @abstractmethod
    def health(self):
        pass


def raise_with_body(response: requests.Response):
    """Include provider response body in HTTP errors."""
    if response.status_code >= 400:
        raise requests.HTTPError(
            f"{response.status_code} {response.reason} -- body: {response.text[:1000]}",
            response=response,
        )


def openai_content(text: str, request):
    """Contenido para APIs OpenAI-compatibles (Groq, NVIDIA). Si el request trae
    imagenes, devuelve el array multimodal [texto + image_url...]; si no, el texto."""
    images = getattr(request, "images", None)
    if not images:
        return text
    blocks = [{"type": "text", "text": text}]
    for img in images:
        blocks.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}})
    return blocks
