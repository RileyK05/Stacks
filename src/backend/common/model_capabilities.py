"""What the student's chosen model can do, asked of its provider.

Stacks does not pick models or hard-code their limits, so a generation call
used to treat every model without a profile as "unknown": a 2048-token first
request (a quiz needs ~5,000 tokens with thinking on, so it was cut off and
redone), and no way to tell whether thinking can be turned down. Providers
answer this themselves:

- Anthropic's Models API lists `max_tokens`, the `effort` levels and the
  `thinking` types a model supports.
- Ollama's `/api/show` lists `capabilities` (e.g. "thinking").

Answers are cached per (provider, base URL, model) for the life of the
process. A failed lookup is cached briefly as "unknown", which keeps the
conservative behaviour: nothing here may make a call fail that would have
worked without it.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from src.backend.common.providers import ResolvedProvider

logger = logging.getLogger(__name__)

_UNKNOWN_RETRY_SECONDS = 300.0
_LOOKUP_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class Capabilities:
    # The model's own output ceiling; None when the provider does not say.
    max_output_tokens: int | None = None
    # Effort levels the provider accepts (Anthropic `output_config.effort`).
    efforts: frozenset[str] = field(default_factory=frozenset)
    # Whether thinking can be switched off for a call.
    can_disable_thinking: bool = False
    # Whether the model thinks at all (so a reasoning setting means anything).
    thinks: bool = False


UNKNOWN = Capabilities()
_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str, str], tuple[float, Capabilities]] = {}


def capabilities_for(endpoint: ResolvedProvider) -> Capabilities:
    if endpoint.is_local or not endpoint.model:
        return UNKNOWN
    key = (endpoint.name, endpoint.base_url, endpoint.model)
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and (hit[1] is not UNKNOWN or now < hit[0]):
            return hit[1]
    found = _lookup(endpoint)
    with _LOCK:
        _CACHE[key] = (now + _UNKNOWN_RETRY_SECONDS, found)
    return found


def reset() -> None:
    """Test hook."""
    with _LOCK:
        _CACHE.clear()


def _lookup(endpoint: ResolvedProvider) -> Capabilities:
    try:
        if endpoint.name == "anthropic":
            return _anthropic(endpoint)
        if endpoint.name == "ollama_cloud":
            return _ollama(endpoint)
    except Exception as err:  # noqa: BLE001 — a lookup must never break a call
        logger.info(
            "could not read %s capabilities for %s: %s",
            endpoint.name,
            endpoint.model,
            type(err).__name__,
        )
    return UNKNOWN


def _anthropic(endpoint: ResolvedProvider) -> Capabilities:
    from src.backend.common.provider import anthropic_client

    client = anthropic_client(
        endpoint.base_url, endpoint.api_key, timeout=_LOOKUP_TIMEOUT_SECONDS
    )
    info = client.models.retrieve(endpoint.model).model_dump()
    caps = info.get("capabilities") or {}
    effort = caps.get("effort") or {}
    efforts = frozenset(
        level
        for level, value in effort.items()
        if isinstance(value, dict) and value.get("supported")
    )
    thinking = caps.get("thinking") or {}
    types = thinking.get("types") or {}
    disabled = types.get("disabled") or {}
    max_tokens = info.get("max_tokens")
    return Capabilities(
        max_output_tokens=max_tokens if isinstance(max_tokens, int) else None,
        efforts=efforts if effort.get("supported") else frozenset(),
        can_disable_thinking=bool(disabled.get("supported")),
        thinks=bool(thinking.get("supported")),
    )


def _ollama(endpoint: ResolvedProvider) -> Capabilities:
    import httpx

    root = endpoint.base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    headers = (
        {"Authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}
    )
    response = httpx.post(
        f"{root}/api/show",
        json={"model": endpoint.model},
        headers=headers,
        timeout=_LOOKUP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    shown = response.json()
    listed = shown.get("capabilities") or []
    thinks = "thinking" in listed
    info = shown.get("model_info") or {}
    # Ollama states no separate output limit and does not reject a large
    # max_tokens; the context length bounds what it can generate.
    context = next(
        (
            value
            for key, value in info.items()
            if key.endswith(".context_length") and isinstance(value, int)
        ),
        None,
    )
    # Ollama's OpenAI endpoint takes reasoning_effort for thinking models,
    # "none" included (measured on Ollama Cloud).
    return Capabilities(
        max_output_tokens=context,
        efforts=frozenset({"low", "medium", "high"}) if thinks else frozenset(),
        can_disable_thinking=thinks,
        thinks=thinks,
    )
