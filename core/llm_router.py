import json
import logging
from dataclasses import replace
from pathlib import Path

import requests

from core.backend_state import set_backend
from core.llm_health import health_manager
from core.llm_types import LLMRequest, LLMResponse
from providers.registry import PROVIDERS

log = logging.getLogger("jarvis.llm_router")

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "providers.json"


def _load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


_CONFIG = _load_config()
_PROVIDERS_CONFIG = _CONFIG["providers"]
_SELECTION = _CONFIG.get("selection", {})
_BACKEND_LABELS = _CONFIG.get("backend_labels", {})

# Ponderacion potencia + DISPONIBILIDAD. La potencia (prioridad + capacidad) elige
# el mejor modelo; la disponibilidad ajusta: un proveedor potente pero lento o con
# fallos recientes baja, para que uno mas fiable lo adelante. Tunable desde
# providers.json -> "scoring" sin tocar codigo.
_SCORING = {
    "failure_penalty": 6.0,   # puntos por fallo en la racha actual
    "failure_cap": 5,         # tope de fallos que cuentan
    "latency_penalty": 1.5,   # puntos por segundo de latencia
    "latency_cap": 8.0,       # tope de latencia en segundos
    "healthy_bonus": 4.0,     # premio si el proveedor esta online y sin fallos
    **_CONFIG.get("scoring", {}),
}


def _availability_adjustment(provider_name: str) -> float:
    """Ajuste por disponibilidad real medida por HealthManager (latencia + racha
    de fallos + online). Negativo cuando el proveedor esta degradado."""
    state = health_manager.get(provider_name)
    adjustment = 0.0
    if state.recent_penalty:
        adjustment -= min(state.recent_penalty, _SCORING["failure_cap"]) * _SCORING["failure_penalty"]
    if state.latency:
        adjustment -= min(state.latency, _SCORING["latency_cap"]) * _SCORING["latency_penalty"]
    if state.online and not state.recent_penalty:
        adjustment += _SCORING["healthy_bonus"]
    return adjustment


def _requirements_from_request(request: LLMRequest) -> dict:
    defaults = dict(_SELECTION.get("defaults", {}))
    intent_roles = _SELECTION.get("intent_roles", {})
    role_defaults = _SELECTION.get("role_defaults", {})
    explicit = request.requirements or {}

    role = explicit.get("role") or intent_roles.get(request.intent, request.intent or defaults.get("role"))
    requirements = defaults | role_defaults.get(role, {}) | {"role": role}
    requirements["tools"] = bool(request.tools)
    if requirements["tools"] and "role" not in explicit:
        requirements["role"] = "tools"
        requirements.update(role_defaults.get("tools", {}))
    requirements.update(explicit)
    if getattr(request, "images", None):
        # Con imagen adjunta forzamos un modelo con vision (rol 'vision') y sin
        # tools: manda el contenido visual por encima del rol que tocara por intent.
        requirements["role"] = "vision"
        requirements["vision"] = True
        requirements["tools"] = False
    return requirements


def _backend_label(provider_name: str) -> str:
    return _BACKEND_LABELS.get(provider_name, provider_name)


def _is_connectivity_failure(exception: Exception | None) -> bool:
    """Solo una caida real de red debe saltar el resto de modelos del proveedor."""
    return isinstance(exception, (requests.Timeout, requests.ConnectionError))


def _power_score(provider_config: dict, model_config: dict, requirements: dict) -> int:
    """Solo potencia: prioridad de proveedor + prioridad de modelo + capacidad."""
    role = requirements.get("role", "general")
    if role == "code":
        capability_bonus = model_config.get("coding", 0)
    elif role == "reasoning":
        capability_bonus = model_config.get("reasoning", 0)
    else:
        capability_bonus = model_config.get("speed", 0)
    return provider_config.get("priority", 0) + model_config.get("priority", 0) + capability_bonus


def _score(provider_name: str, provider_config: dict, model_config: dict, requirements: dict) -> float:
    """Potencia + disponibilidad. La cascada sigue siendo 'el mas potente primero',
    pero un proveedor degradado (lento o fallando) cede el puesto al siguiente."""
    return _power_score(provider_config, model_config, requirements) + _availability_adjustment(provider_name)


def _discard_reason(provider_name: str, provider_config: dict, model_config: dict, requirements: dict, ignore_health: bool = False) -> str:
    if not provider_config.get("enabled", False):
        return "proveedor deshabilitado"
    if provider_name not in PROVIDERS:
        return "proveedor sin implementacion"
    if not ignore_health and not health_manager.is_online(provider_name):
        return "proveedor offline"

    role = requirements.get("role", "general")
    roles = model_config.get("roles", [])
    if role not in roles:
        return f"rol no soportado: {role}"
    if requirements.get("tools") and not model_config.get("tools", False):
        return "tools no soportado"
    if requirements.get("stream") and not model_config.get("stream", False):
        return "stream no soportado"
    if requirements.get("vision") and not model_config.get("vision", False):
        return "vision no soportado"
    if requirements.get("embeddings") and not model_config.get("embeddings", False):
        return "embeddings no soportado"
    if model_config.get("context", 0) < requirements.get("min_context", 0):
        return "contexto insuficiente"
    return ""


def _iter_model_configs():
    for provider_name, provider_config in _PROVIDERS_CONFIG.items():
        for model_config in provider_config.get("models", []):
            yield provider_name, provider_config, model_config


def find_models(requirements: dict, ignore_health: bool = False) -> list[dict]:
    candidates = []
    for provider_name, provider_config, model_config in _iter_model_configs():
        reason = _discard_reason(provider_name, provider_config, model_config, requirements, ignore_health)
        if reason:
            continue
        candidates.append({
            "provider": provider_name,
            "model": model_config["name"],
            "display_name": model_config.get("display_name", model_config["name"]),
            "score": _score(provider_name, provider_config, model_config, requirements),
            "provider_config": provider_config,
            "model_config": model_config,
        })
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _call_candidates(request: LLMRequest, use_tools: bool):
    requirements = _requirements_from_request(request)
    candidates = find_models(requirements)
    if not candidates:
        # La salud es una pista, no un veto: un 429 o un 400 puntual marca el
        # proveedor offline durante ~60s y podia dejar la lista vacia aunque
        # el proveedor siga vivo. Reintentar ignorando el estado de salud.
        log.warning("Sin candidatos por salud; reintentando ignorando health")
        candidates = find_models(requirements, ignore_health=True)
    last_result = None
    failed_providers = set()

    for candidate in candidates:
        provider_name = candidate["provider"]
        # Los modelos de un proveedor comparten la misma conexion/API. Si el
        # proveedor acaba de fallar por red, probar sus otros modelos solo
        # multiplica el bloqueo antes de llegar al siguiente fallback.
        if provider_name in failed_providers:
            continue
        provider = PROVIDERS[provider_name]
        model_request = replace(request, model=candidate["model"], requirements=requirements)
        result = provider.chat_tools(model_request) if use_tools else provider.chat(model_request)
        last_result = result
        if result.success:
            health_manager.record_success(provider_name, result.latency)
            set_backend(_backend_label(provider_name))
            return result
        # Cualquier fallo (429 rate-limit, 5xx, timeout) resta disponibilidad en el
        # scoring; una caida de red ademas tumba al proveedor (filtro duro).
        health_manager.record_issue(provider_name)
        if _is_connectivity_failure(result.exception):
            health_manager.record_failure(provider_name)
            failed_providers.add(provider_name)
        log.warning(f"{provider_name}/{candidate['model']} fallo: {result.exception}")

    if last_result and last_result.exception:
        raise last_result.exception
    raise RuntimeError(f"No hay modelos compatibles para requirements={requirements}")


def chat(request: LLMRequest):
    result = _call_candidates(request, use_tools=False)
    return LLMResponse(
        text=result.response,
        provider=_backend_label(result.provider),
        model=result.model,
        latency=result.latency,
        success=result.success,
    )


def chat_tools(request: LLMRequest):
    result = _call_candidates(request, use_tools=True)
    return result.response


def debug(request: LLMRequest | dict) -> str:
    if isinstance(request, LLMRequest):
        requirements = _requirements_from_request(request)
    else:
        requirements = request

    lines = ["=== LLM Router ===", "", "Solicitud:"]
    for key, value in requirements.items():
        lines.append(f"{key}={value}")
    lines.extend(["", "Candidatos:"])

    accepted = []
    rejected = []
    for provider_name, provider_config, model_config in _iter_model_configs():
        reason = _discard_reason(provider_name, provider_config, model_config, requirements)
        item = {
            "provider": provider_name,
            "model": model_config.get("display_name", model_config.get("name")),
            "power": _power_score(provider_config, model_config, requirements),
            "availability": _availability_adjustment(provider_name),
            "score": _score(provider_name, provider_config, model_config, requirements),
            "reason": reason,
        }
        if reason:
            rejected.append(item)
        else:
            accepted.append(item)

    for item in sorted(accepted, key=lambda data: data["score"], reverse=True):
        lines.append("")
        lines.append(f"OK {item['provider']} / {item['model']}")
        lines.append(f"score: {item['score']:.1f} (potencia {item['power']} + disponibilidad {item['availability']:+.1f})")

    for item in rejected:
        lines.append("")
        lines.append(f"NO {item['provider']} / {item['model']}")
        lines.append("descartado:")
        lines.append(item["reason"])

    selected = sorted(accepted, key=lambda data: data["score"], reverse=True)[:1]
    lines.extend(["", "Modelo seleccionado:"])
    if selected:
        lines.append(f"{selected[0]['provider']} / {selected[0]['model']}")
    else:
        lines.append("ninguno")
    return "\n".join(lines)
