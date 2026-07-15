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
