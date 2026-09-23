"""The single hosted-model seam.

Every model call in the backend goes through `generate`: task + prompt
in, text out — gated, routed, billed. Providers are an implementation
detail behind this one function; swapping providers never touches
ingestion/tutor code.

Contract (enforced here, not by callers remembering):
- the tier is resolved and verified from the account inside this seam —
  no caller-supplied TierPolicy, so a stale/spoofed tier can never route
  ingestion to paid models;
- the budget gate runs BEFORE the provider call (in-flight calls are
  never cut off; the gate tightens the next request only);
- the ledger row is recorded AFTER the call with the call's real token
  counts, even if the caller's access lapsed mid-flight — spend must be
  visible;
- task-to-pool routing is symmetric: ingestion tasks must bill the
  ingestion pool, interactive tasks must bill the generation pool. The
  task classification lives in `schemas/base.py` next to the task list
  (single source of truth).

Provider contract: any OpenAI-compatible chat-completions endpoint
(currently Xiaomi MiMo) — `LLM_API_KEY` + `LLM_BASE_URL` in the
environment. Token counts come from the provider's usage response, never
estimated by the caller.

Embeddings are a SEPARATE seam (`embed`), deliberately not `generate`:
the embedding model is self-hosted and in-process (sentence-transformers),
so it bills nothing, needs no tier, and sends no course text off-machine
— the no-retention vendor check does not apply to it by construction.
Its contract lives in configs/embeddings.toml (the model name is the
chunk_embeddings row key; dimension is enforced loudly on write and read).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from src.backend.common import budget, spend_repo
from src.backend.common.embeddings_config import EmbeddingPolicy, load_embedding_policy
from src.backend.common.schemas.base import (
    INGESTION_TASKS,
    KNOWN_GENERATION_TASKS,
    SpendKind,
    UserTier,
)
from src.backend.common.tiers import load_tier_policies

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class ProviderUnavailableError(RuntimeError):
    """Raised when no provider client is configured. Callers surface this
    as a retryable stage failure, not a crash."""


class EmptyModelError(RuntimeError):
    """The provider returned no usable text. Stages must fail on this —
    a model stage that 'succeeds' while writing no rows is a false
    success that empties the course knowledge base."""


def generate(
    task: str,
    prompt: str,
    user_id: UUID,
    tier: UserTier,
    *,
    course_id: UUID | None = None,
    images: Sequence[bytes] | None = None,
) -> GenerationResult:
    """One gated, routed, billed model call. `tier` is verified against
    the account inside; the pool is derived from the task, never passed
    in. `images` carries PNG page renders for the multimodal OCR task; it
    is None for every text task."""
    if task not in KNOWN_GENERATION_TASKS:
        raise ValueError(f"unknown generation task: {task}")
    spend_kind = (
        SpendKind.INGESTION if task in INGESTION_TASKS else SpendKind.GENERATION
    )
    budget.verify_tier(user_id, tier)
    policy = load_tier_policies().policy_for(tier)
    budget.check_budget(
        user_id,
        tier,
        policy,
        spend_kind=spend_kind,
    )
    model = policy.model_for(task)
    raw_text, input_tokens, output_tokens = _call_provider(
        task, model, prompt, images=images
    )
    if not raw_text.strip():
        raise EmptyModelError(task)
    result = GenerationResult(
        text=raw_text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    spend_repo.record_generation(
        user_id,
        task,
        result.model,
        result.input_tokens,
        result.output_tokens,
        course_id=course_id,
        spend_kind=spend_kind,
        overhead_tokens=budget.free_tier_overhead(
            policy, result.input_tokens + result.output_tokens
        ),
    )
    return result


def _call_provider(
    task: str,
    model: str,
    prompt: str,
    *,
    images: Sequence[bytes] | None = None,
) -> tuple[str, int, int]:
    """The provider HTTP call. Returns (text, input_tokens, output_tokens)
    — token counts come from the provider's usage response, never
    estimated by the caller. `images` is present only for the multimodal
    OCR task.

    Provider contract: any OpenAI-compatible chat-completions endpoint
    (currently Xiaomi MiMo). `LLM_API_KEY` + `LLM_BASE_URL` come from the
    environment via common.config. Fails closed: missing config or any
    HTTP/parse failure raises ProviderUnavailableError, which callers
    surface as a retryable stage failure / 503 — never as a partial row
    write."""
    import base64

    import httpx
    from src.backend.common.config import get_settings

    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_base_url:
        raise ProviderUnavailableError(
            "LLM_API_KEY / LLM_BASE_URL not configured"
        )

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

    try:
        response = httpx.post(
            settings.llm_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,
            },
            timeout=httpx.Timeout(600.0, connect=15.0),
        )
        response.raise_for_status()
        body = response.json()
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as err:
        raise ProviderUnavailableError(
            f"provider call failed (task={task}, model={model}): {err}"
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


@dataclass(frozen=True)
class _EmbedBackend:
    """The loaded sentence-transformers model plus its contract. Built
    once per process (model load is ~seconds; embedding is per-chunk)."""

    model: SentenceTransformer
    policy: EmbeddingPolicy


_EMBEDDING_BACKEND: _EmbedBackend | None = None


def _load_embedding_backend() -> _EmbedBackend:
    """Idempotent model load. Import is deferred so the whole test suite
    (and any code path that never touches the embedding seam) never pays
    the torch/sentence-transformers import cost."""
    global _EMBEDDING_BACKEND
    if _EMBEDDING_BACKEND is not None:
        return _EMBEDDING_BACKEND
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as err:
        raise ProviderUnavailableError(
            "sentence-transformers not installed — embeddings unavailable"
        ) from err
    policy = load_embedding_policy()
    model = SentenceTransformer(policy.model)
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
                f"model returned {len(vector)} dims, config says "
                f"{policy.dimension}"
            )
    return vectors_list


def embed_query(text: str) -> list[float]:
    return embed_texts([text], kind="query")[0]


def embed_chunks(texts: Sequence[str]) -> list[list[float]]:
    return embed_texts(texts, kind="document")
