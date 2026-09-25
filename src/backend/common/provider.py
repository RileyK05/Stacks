"""The model seams: `generate` (chat models) and `embed` (encoders).

Every generation call in the backend goes through `generate`: task +
prompt in, text out — routed, checked, and recorded. Which endpoint serves
a task is `providers.resolve` (the user's choice per task class, then the
development `.env` fallback); swapping providers never touches ingestion
or tutor code.

Contract (enforced here, not by callers remembering):
- the endpoint is resolved per call, so a Settings change applies to the
  next call without a restart;
- a cloud call checks the user's optional monthly token budget BEFORE the
  request (an in-flight call is never cut off); local calls are free;
- the usage row is recorded AFTER the call with the provider's real token
  counts — usage is inspectable, never estimated;
- a cloud provider that rate-limits (HTTP 429, e.g. OpenRouter's free
  daily cap) falls back to the local model once, and the result says so.

Provider contract: any OpenAI-compatible chat-completions endpoint — the
bundled llama.cpp server, Ollama / LM Studio, OpenRouter, OpenAI, or a
custom URL. Local models get `enable_thinking: false` by default: small
models deliberate at length and llama.cpp ignores JSON-schema constraints
while thinking (plan §6.3).

Embeddings are a SEPARATE seam (`embed_*`), deliberately not `generate`:
the embedding model runs in-process, so it records nothing and sends no
course text anywhere. Its contract lives in configs/embeddings.toml (the
model name is the chunk_embeddings row key; dimension is enforced loudly
on write and read).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from src.backend.common import providers, usage_repo
from src.backend.common.embeddings_config import EmbeddingPolicy, load_embedding_policy
from src.backend.common.providers import ResolvedProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    provider: str = ""
    # True when a rate-limited cloud provider fell back to the local model;
    # the UI shows this so a weaker answer is never silently substituted.
    fell_back_to_local: bool = False


class ProviderUnavailableError(RuntimeError):
    """No provider is configured, or the call failed. Callers surface this
    as a retryable stage failure / 503, never as a partial row write."""


class ProviderRateLimitedError(ProviderUnavailableError):
    """The provider answered 429 (rate limit / daily free-model cap)."""


class ProviderRequestRejectedError(ProviderUnavailableError):
    """The provider refused the request itself (4xx other than 429) —
    e.g. a model without structured-output support rejecting
    `response_format`. Retrying without that option may succeed."""


class EmptyModelError(RuntimeError):
    """The provider returned no usable text. Stages must fail on this —
    a model stage that 'succeeds' while writing no rows is a false
    success that empties the course knowledge base."""


def generate(
    task: str,
    prompt: str,
    *,
    course_id: UUID | None = None,
    images: Sequence[bytes] | None = None,
    response_schema: dict[str, Any] | None = None,
) -> GenerationResult:
    """One routed, recorded model call. `images` carries PNG page renders
    for the multimodal OCR task. `response_schema`, when given, asks the
    endpoint to constrain output to that JSON schema."""
    endpoint = providers.resolve(providers.task_class(task))
    if endpoint is None:
        raise ProviderUnavailableError(
            "no model provider configured — choose one in Settings"
        )
    if endpoint.name == "local":
        _ensure_local_runtime(endpoint.model)
    fell_back = False
    try:
        if not endpoint.is_local:
            usage_repo.check_cloud_budget()
        raw_text, input_tokens, output_tokens = _call_provider(
            task, endpoint, prompt, images=images, response_schema=response_schema
        )
    except ProviderRateLimitedError:
        local = _local_fallback(endpoint)
        if local is None:
            raise
        logger.warning(
            "%s rate-limited task %s; falling back to the local model",
            endpoint.name,
            task,
        )
        endpoint, fell_back = local, True
        _ensure_local_runtime(endpoint.model)
        raw_text, input_tokens, output_tokens = _call_provider(
            task, endpoint, prompt, images=images, response_schema=response_schema
        )
    if not raw_text.strip():
        raise EmptyModelError(task)
    usage_repo.record(
        task=task,
        provider=endpoint.name,
        model=endpoint.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        course_id=course_id,
    )
    return GenerationResult(
        text=raw_text,
        model=endpoint.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=endpoint.name,
        fell_back_to_local=fell_back,
    )


def _ensure_local_runtime(model_id: str) -> None:
    """The "local" preset is the app's own llama.cpp server: start the
    chosen catalog model on first use. A model name outside the catalog
    (a server the user runs themselves) is left alone."""
    from src.backend.runtime.config import load_runtime_config
    from src.backend.runtime.server import RuntimeUnavailableError, ensure_running

    if load_runtime_config().model(model_id) is None:
        return
    try:
        ensure_running(model_id)
    except RuntimeUnavailableError as err:
        raise ProviderUnavailableError(
            f"the local model could not start: {err}. "
            "Download it or pick another model in Settings."
        ) from err


def _local_fallback(failed: ResolvedProvider) -> ResolvedProvider | None:
    if failed.is_local:
        return None
    preset = providers.load_models_config().presets.get("local")
    if preset is None or not preset.base_url or not preset.default_model:
        return None
    return ResolvedProvider(
        name="local",
        base_url=preset.base_url,
        model=preset.default_model,
        api_key=None,
        is_local=True,
    )


def _call_provider(
    task: str,
    endpoint: ResolvedProvider,
    prompt: str,
    *,
    images: Sequence[bytes] | None = None,
    response_schema: dict[str, Any] | None = None,
) -> tuple[str, int, int]:
    """The HTTP call. Returns (text, input_tokens, output_tokens) — token
    counts come from the provider's usage response, never estimated.
    Fails closed: any HTTP/parse failure raises ProviderUnavailableError
    (ProviderRateLimitedError for 429)."""
    import base64

    import httpx

    defaults = providers.load_models_config().generation
    if images:
        content: list[dict[str, object]] = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64.b64encode(img).decode()}"
                },
            }
            for img in images
        ]
        content.append({"type": "text", "text": prompt})
        messages: list[dict[str, object]] = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]

    body: dict[str, Any] = {
        "model": endpoint.model,
        "messages": messages,
        "temperature": defaults.temperature,
        "max_tokens": defaults.max_output_tokens,
    }
    if endpoint.is_local or endpoint.name == "custom":
        # Local runtimes disagree on the switch: llama-server reads the
        # template kwarg, LM Studio only honours reasoning_effort (measured:
        # MiniCPM5-2B spent ~90% of its tokens thinking with the kwarg alone).
        # Cloud APIs reject unknown fields, so neither goes to them.
        body["chat_template_kwargs"] = {"enable_thinking": defaults.enable_thinking}
        if not defaults.enable_thinking:
            body["reasoning_effort"] = "none"
    if response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": task, "schema": response_schema, "strict": True},
        }
    headers = (
        {"Authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}
    )

    try:
        response = httpx.post(
            endpoint.base_url.rstrip("/") + "/chat/completions",
            headers=headers,
            json=body,
            timeout=httpx.Timeout(defaults.request_timeout_seconds, connect=15.0),
        )
        if response.status_code == 429:
            raise ProviderRateLimitedError(
                f"{endpoint.name} rate-limited (task={task}, model={endpoint.model})"
            )
        if 400 <= response.status_code < 500:
            raise ProviderRequestRejectedError(
                f"{endpoint.name} rejected the request ({response.status_code}, "
                f"task={task}, model={endpoint.model})"
            )
        response.raise_for_status()
        payload = response.json()
        text = payload["choices"][0]["message"]["content"] or ""
        usage = payload.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
    except (ProviderRateLimitedError, ProviderRequestRejectedError):
        raise
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as err:
        raise ProviderUnavailableError(
            f"provider call failed ({endpoint.name}, task={task}, "
            f"model={endpoint.model}): {err}"
        ) from err
    return text, input_tokens, output_tokens


# ---------------------------------------------------------------------
# Embedding seam (self-hosted, in-process). See module docstring for why
# this is not `generate`.
# ---------------------------------------------------------------------


class EmbeddingDimensionError(RuntimeError):
    """The loaded model's output dimension disagrees with the config.
    A hard error on both write and read paths: the retrieval seam's
    cardinality guard would otherwise rank garbage silently."""


class _EmbeddingModel(Protocol):
    def get_embedding_dimension(self) -> int: ...

    def encode(
        self,
        texts: list[str],
        batch_size: int = ...,
        normalize_embeddings: bool = ...,
        show_progress_bar: bool = ...,
    ) -> Any: ...


@dataclass(frozen=True)
class _EmbedBackend:
    """The loaded embedding model plus its contract. Built once per process
    (model load is ~seconds; embedding is per-chunk)."""

    model: _EmbeddingModel
    policy: EmbeddingPolicy


_EMBEDDING_BACKEND: _EmbedBackend | None = None


def _load_embedding_backend() -> _EmbedBackend:
    """Idempotent model load, deferred so code paths that never embed never
    pay for it. The model runs on ONNX Runtime (common/encoders.py):
    identical output to the sentence-transformers model it replaced
    (scripts/check_encoders.py), without shipping torch."""
    global _EMBEDDING_BACKEND
    if _EMBEDDING_BACKEND is not None:
        return _EMBEDDING_BACKEND
    from src.backend.common.encoders import EMBEDDING_SPECS, OnnxEmbedder

    policy = load_embedding_policy()
    spec = EMBEDDING_SPECS.get(policy.model)
    if spec is None:
        raise ProviderUnavailableError(
            f"no ONNX build registered for embedding model {policy.model}"
        )
    try:
        model = OnnxEmbedder(spec)
    except Exception as err:
        raise ProviderUnavailableError(f"embedding model unavailable: {err}") from err
    test_dimension = model.get_embedding_dimension()
    if test_dimension != policy.dimension:
        raise EmbeddingDimensionError(
            f"configured dimension {policy.dimension} != model's actual "
            f"{test_dimension} for {policy.model}"
        )
    _EMBEDDING_BACKEND = _EmbedBackend(model=model, policy=policy)
    return _EMBEDDING_BACKEND


def reset_embedding_backend() -> None:
    """Test/process hook: drop the cached model so a config change (or a
    fake in tests) takes effect on the next embed call."""
    global _EMBEDDING_BACKEND
    _EMBEDDING_BACKEND = None


def embed_texts(
    texts: Sequence[str],
    *,
    kind: str,
) -> list[list[float]]:
    """Embed a batch of texts under the configured model's contract.

    `kind` is "query" or "document" — it selects the prefix (asymmetric
    models require different handling of the two sides; symmetric models
    ship empty prefixes and this is a no-op). Dimension is verified per
    call: a model swap that changes dimensionality fails here, loudly,
    not as silent garbage ranks in Postgres.
    """
    if not texts:
        return []
    if kind not in ("query", "document"):
        raise ValueError(f"unknown embed kind: {kind}")
    backend = _load_embedding_backend()
    policy = backend.policy
    prefix = policy.query_prefix if kind == "query" else policy.document_prefix
    if prefix:
        texts = [f"{prefix}{text}" for text in texts]
    vectors = backend.model.encode(
        list(texts),
        batch_size=policy.batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    vectors_list = [list(map(float, vector)) for vector in vectors]
    for vector in vectors_list:
        if len(vector) != policy.dimension:
            raise EmbeddingDimensionError(
                f"model returned {len(vector)} dims, config says {policy.dimension}"
            )
    return vectors_list


_RERANKER: Any = None
_RERANKER_NAME: str | None = None


def reset_reranker() -> None:
    global _RERANKER, _RERANKER_NAME
    _RERANKER, _RERANKER_NAME = None, None


def rerank_scores(model_name: str, query: str, texts: Sequence[str]) -> list[float]:
    """Relevance of each text to the query from a cross-encoder (higher =
    more relevant). In-process and CPU-only, like the embedding seam:
    records nothing and sends nothing anywhere."""
    global _RERANKER, _RERANKER_NAME
    if not texts:
        return []
    if _RERANKER is None or model_name != _RERANKER_NAME:
        from src.backend.common.encoders import RERANKER_SPECS, OnnxCrossEncoder

        spec = RERANKER_SPECS.get(model_name)
        if spec is None:
            raise ProviderUnavailableError(f"no ONNX build registered for {model_name}")
        _RERANKER, _RERANKER_NAME = OnnxCrossEncoder(spec), model_name
    scores = _RERANKER.predict([(query, text) for text in texts])
    return [float(score) for score in scores]


def embed_query(text: str) -> list[float]:
    return embed_texts([text], kind="query")[0]


def embed_chunks(texts: Sequence[str]) -> list[list[float]]:
    return embed_texts(texts, kind="document")
