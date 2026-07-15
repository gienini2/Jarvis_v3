from dataclasses import dataclass


@dataclass
class LLMRequest:
    prompt: str
    intent: str = "general"
    tools: object = None
    rag: object = None
    model: str = ""
    requirements: object = None


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    latency: float
    success: bool
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class ProviderResult:
    provider: str
    model: str
    success: bool
    latency: float
    response: object = None
    exception: object = None
