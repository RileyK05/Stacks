"""The model seams: `generate` (chat models) and `embed` (encoders).

Every generation call in the backend goes through `generate`: task +
prompt in, text out — routed, checked, and recorded. Which endpoint serves
a task is `providers.resolve` (the user's choice per task class, then the
development `.env` fallback); swapping providers never touches ingestion
or tutor code.

Contract (enforced here, not by callers remembering):
- the endpoint is pinned for one operation; a Settings change applies to
  the next operation without a restart;
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
course text anywhere. Its contract lives in configs/embeddings.toml. Vectors
carry model identity; dimension is enforced on write and read.
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from src.backend.common import generation, model_profiles, providers, usage_repo
from src.backend.common.embeddings_config import EmbeddingPolicy, load_embedding_policy
from src.backend.common.providers import ProviderChoice, ResolvedProvider

logger = logging.getLogger(__name__)
_USAGE_RECORDER: ContextVar[Callable[[int, int, bool], None] | None] = ContextVar(
    "generation_usage_recorder", default=None
)

# Presets for servers the user runs (not the bundled one). They get the
# runtime-specific reasoning switches that cloud APIs would reject.
SELF_HOSTED_PRESETS = frozenset({"custom", "lmstudio", "ollama"})


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
    usage_reported: bool = True


class ProviderUnavailableError(RuntimeError):
    """No provider is configured, or the call failed. Callers surface this
    as a retryable stage failure / 503, never as a partial row write."""


class ProviderRateLimitedError(ProviderUnavailableError):
    """The provider answered 429 (rate limit / daily free-model cap)."""


class ProviderRequestRejectedError(ProviderUnavailableError):
    """The provider refused the request itself (4xx other than 429) —
    e.g. a model without structured-output support rejecting
    `response_format`. Retrying without that option may succeed."""


class EmptyModelError(ProviderUnavailableError):
    """The provider returned no usable text. Stages must fail on this —
    a model stage that 'succeeds' while writing no rows is a false
    success that empties the course knowledge base."""


class ModelOutputTruncatedError(ProviderUnavailableError):
    """The provider stopped at its output limit; partial text is unsafe to use."""

    def __init__(
        self,
        message: str,
        *,
        partial_text: str = "",
        output_limit: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        usage_reported: bool = False,
    ) -> None:
        super().__init__(message)
        self.partial_text = partial_text
        self.output_limit = output_limit
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.usage_reported = usage_reported


class ModelReasoningOnlyError(ProviderUnavailableError):
    """The model finished after thinking and returned no visible answer."""


def generate(
    task: str,
    prompt: str,
    *,
    course_id: UUID | None = None,
    images: Sequence[bytes] | None = None,
    response_schema: dict[str, Any] | None = None,
    bigger: bool = False,
    choice: ProviderChoice | None = None,
) -> GenerationResult:
    """Route, bound, recover and record one task through the chosen model."""
    with generation.operation() as operation:
        try:
            return _generate(
                task,
                prompt,
                course_id=course_id,
                images=images,
                response_schema=response_schema,
                bigger=bigger,
                choice=choice,
                operation=operation,
            )
        except generation.GenerationLimitError as error:
            raise ProviderUnavailableError(str(error)) from error


def _generate(
    task: str,
    prompt: str,
    *,
    course_id: UUID | None,
    images: Sequence[bytes] | None,
    response_schema: dict[str, Any] | None,
    bigger: bool,
    choice: ProviderChoice | None,
    operation: generation.Operation,
) -> GenerationResult:
    """One routed, recorded model call. `images` carries PNG page renders
    for the multimodal OCR task. `response_schema`, when given, asks the
    endpoint to constrain output to that JSON schema. `bigger` routes an
    interactive task to the user's "bigger model" slot instead; `choice`
    (a chat's model picker) names the endpoint outright. Neither an
    explicit choice nor the bigger model falls back to another model when
    rate-limited: the user picked it on purpose."""
    cls = providers.task_class(task)
    if bigger:
        if cls != providers.TaskClass.INTERACTIVE:
            raise ValueError(f"only interactive tasks can ask a bigger model: {task}")
        cls = providers.TaskClass.BIGGER
    key = cls.value + (
        choice.model_dump_json() if choice is not None and not bigger else ""
    )
    endpoint = operation.endpoint(
        key,
        lambda: (
            providers.resolve_choice(choice)
            if choice is not None and not bigger
            else providers.resolve(cls)
        ),
    )
    if endpoint is None:
        if bigger:
            message = (
                "no bigger model configured — set one under Settings → Models, "
                "or LLM_BIGGER_BASE_URL and LLM_BIGGER_MODEL in development"
            )
        elif choice is not None:
            message = (
                "this chat's model isn't available — check its connection "
                "and key in Settings, or pick another model"
            )
        else:
            message = "no model provider configured — choose one in Settings"
        raise ProviderUnavailableError(message)
    pinned = bigger or choice is not None
    if endpoint.name == "local":
        _ensure_local_runtime(endpoint.model)
    fell_back = key in operation.local_fallbacks
    try:
        if not endpoint.is_local:
            usage_repo.check_cloud_budget()
        raw_text, input_tokens, output_tokens, usage_reported = _complete_call(
            task,
            endpoint,
            prompt,
            course_id=course_id,
            images=images,
            response_schema=response_schema,
            operation=operation,
        )
    except ProviderRateLimitedError as limited:
        # The user asked for the bigger model on purpose: quietly answering
        # with the small one instead would defeat the button.
        local = None if pinned else _local_fallback(endpoint)
        if local is None:
            raise
        logger.warning(
            "%s rate-limited task %s; falling back to the local model",
            endpoint.name,
            task,
        )
        try:
            _ensure_local_runtime(local.model)
            raw_text, input_tokens, output_tokens, usage_reported = _complete_call(
                task,
                local,
                prompt,
                course_id=course_id,
                images=images,
                response_schema=response_schema,
                operation=operation,
            )
        except ProviderUnavailableError as err:
            # The rate limit is what the student needs to hear about, not
            # that a fallback they never set up could not start.
            logger.warning("local fallback failed too: %s", err)
            raise limited from err
        endpoint, fell_back = local, True
        operation.endpoints[key] = local
        operation.local_fallbacks.add(key)
    return GenerationResult(
        text=raw_text,
        model=endpoint.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=endpoint.name,
        fell_back_to_local=fell_back,
        usage_reported=usage_reported,
    )


def _complete_call(
    task: str,
    endpoint: ResolvedProvider,
    prompt: str,
    *,
    course_id: UUID | None,
    images: Sequence[bytes] | None,
    response_schema: dict[str, Any] | None,
    operation: generation.Operation,
) -> tuple[str, int, int, bool]:
    limits = generation.plan_call(
        task,
        endpoint,
        prompt,
        response_schema=response_schema,
        images=bool(images),
        policy=operation.policy,
    )

    def invoke() -> tuple[str, int, int, bool]:
        result = _recorded_call(
            task,
            endpoint,
            prompt,
            course_id=course_id,
            images=images,
            response_schema=response_schema,
        )
        if not result[0].strip():
            raise EmptyModelError(
                "The model returned no usable answer. Try again with a more "
                "focused request or choose another model in Settings."
            )
        return result

    def classify(error: Exception) -> generation.Recovery | None:
        if isinstance(error, EmptyModelError):
            return "empty"
        if isinstance(error, (ModelOutputTruncatedError, ModelReasoningOnlyError)):
            return "length"
        return None

    return generation.complete(limits, invoke, classify)


def _recorded_call(
    task: str,
    endpoint: ResolvedProvider,
    prompt: str,
    *,
    course_id: UUID | None,
    images: Sequence[bytes] | None,
    response_schema: dict[str, Any] | None,
) -> tuple[str, int, int, bool]:
    recorded = False
    usage_reported = True

    def record(input_tokens: int, output_tokens: int, reported: bool = True) -> None:
        nonlocal recorded, usage_reported
        usage_repo.record(
            task=task,
            provider=endpoint.name,
            model=endpoint.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            course_id=course_id,
            is_local=endpoint.is_local,
            usage_reported=reported,
        )
        recorded = True
        usage_reported = reported
        generation.record_usage(input_tokens, output_tokens, reported)

    token = _USAGE_RECORDER.set(record)
    try:
        result = _call_provider(
            task, endpoint, prompt, images=images, response_schema=response_schema
        )
        if not recorded:
            record(result[1], result[2])
        return (*result, usage_reported)
    finally:
        _USAGE_RECORDER.reset(token)


def probe(endpoint: ResolvedProvider) -> None:
    """One tiny real completion, for Settings' connection test. Listing an
    endpoint's models proves the URL and key, not that the chosen model
    answers: a mistyped name, or a free model the provider gates, only
    fails on a real request. Raises ProviderUnavailableError with the
    provider's own reason. Unrecorded: a handful of tokens, spent only
    when the user presses Test."""
    # A cut-off or empty reply still means the model answered: a reasoning
    # model may spend the whole tiny reply thinking.
    with contextlib.suppress(
        ModelOutputTruncatedError, EmptyModelError, ModelReasoningOnlyError
    ):
        _call_provider("connection_test", endpoint, "Reply with the single word: ok")


def _ensure_local_runtime(model_id: str) -> None:
    """The "local" preset is the app's own llama.cpp server: start the
    chosen catalog model on first use. A model name outside the catalog
    (a server the user runs themselves) is left alone."""
    from src.backend.runtime.server import RuntimeUnavailableError, ensure_running
    from src.backend.runtime.user_models import find_model

    if find_model(model_id) is None:
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
        connection=providers.LOCAL,
        label=preset.label,
    )


def request_body(
    task: str,
    endpoint: ResolvedProvider,
    prompt: str,
    *,
    images: Sequence[bytes] | None = None,
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The chat-completions request for one call: the model's profile
    (configs/models/) decides reasoning, output length and temperature;
    `[generation]` covers models without one."""
    import base64

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

    profile = model_profiles.profile_for(endpoint.model)
    thinking = profile.reasoning if profile else defaults.enable_thinking
    body: dict[str, Any] = {
        "model": endpoint.model,
        "messages": messages,
        "temperature": (
            profile.temperature
            if profile and profile.temperature is not None
            else defaults.temperature
        ),
        "max_tokens": (
            generation.output_allowance()
            or (profile.max_output_tokens if profile else None)
            or defaults.max_output_tokens
        ),
    }
    if endpoint.is_local or endpoint.name in SELF_HOSTED_PRESETS:
        # Local runtimes disagree on the switch: llama-server reads the
        # template kwarg, LM Studio only honours reasoning_effort (measured:
        # MiniCPM5-2B spent ~90% of its tokens thinking with the kwarg alone).
        # Cloud APIs reject unknown fields, so neither goes to them.
        body["chat_template_kwargs"] = {"enable_thinking": thinking}
        body["reasoning_effort"] = "high" if thinking else "none"
    if response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": task, "schema": response_schema, "strict": True},
        }
    return body


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
    import httpx

    defaults = providers.load_models_config().generation
    body = request_body(
        task, endpoint, prompt, images=images, response_schema=response_schema
    )
    headers = (
        {"Authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}
    )
    who = endpoint.label or endpoint.name
    learned = _ADAPTATIONS.setdefault((endpoint.base_url, endpoint.model), set())
    try:
        while True:
            _apply_adaptations(body, learned)
            remaining = generation.before_http(body)
            timeout = defaults.request_timeout_seconds
            if remaining is not None:
                timeout = min(timeout, remaining)
            if not endpoint.is_local:
                usage_repo.check_cloud_budget()
            response = httpx.post(
                endpoint.base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json=body,
                follow_redirects=True,
                timeout=httpx.Timeout(timeout, connect=min(15.0, timeout)),
            )
            if 200 <= response.status_code < 300:
                break
            detail = provider_error_detail(response)
            logger.warning(
                "%s answered %s (task=%s, model=%s): %s",
                endpoint.name,
                response.status_code,
                task,
                endpoint.model,
                detail,
            )
            fix = _adaptation_for(response.status_code, detail, body)
            if fix is None or fix in learned:
                break
            # Learn only explicitly rejected request parameters. Output recovery
            # belongs to the controller, which owns the shared operation budget.
            learned.add(fix)
        if response.status_code == 429:
            raise ProviderRateLimitedError(
                f"{who} is rate-limiting requests right now"
                + (f": {detail}" if detail else "")
                + ". Wait a minute or pick another model."
            )
        if 400 <= response.status_code < 500:
            raise ProviderRequestRejectedError(
                rejection_message(who, response.status_code, detail)
            )
        if response.status_code >= 500:
            raise ProviderUnavailableError(
                f"{who} had a server error ({response.status_code})"
                + (f": {detail}" if detail else "")
                + ". Try again shortly."
            )
        if 300 <= response.status_code < 400:
            raise ProviderRequestRejectedError(
                f"{who} redirected the model request. Set the connection URL to "
                "the final API endpoint and try again."
            )
        recorder = _USAGE_RECORDER.get()
        try:
            payload = response.json()
        except ValueError:
            if recorder is not None:
                recorder(0, 0, False)
            raise
        usage = payload.get("usage") if isinstance(payload, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        input_tokens, input_reported = _usage_count(usage.get("prompt_tokens"))
        output_tokens, output_reported = _usage_count(usage.get("completion_tokens"))
        reported = input_reported and output_reported
        if recorder is not None:
            recorder(input_tokens, output_tokens, reported)
        if not isinstance(payload, dict):
            raise TypeError("reply is not an object")
        if payload.get("error") and not payload.get("choices"):
            # Upstream failures can arrive inside a 200, with billed usage.
            raise ProviderUnavailableError(
                f"{who} could not answer: {provider_error_detail(response)}. "
                "Try again or pick another model."
            )
        choices = payload.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise TypeError("reply has no completion choice")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise TypeError("completion message is not an object")
        text = _visible_message_text(message.get("content"))
        if choice.get("finish_reason") in {"length", "max_tokens"}:
            raise ModelOutputTruncatedError(
                f"{who} ({endpoint.model}) hit its output limit before finishing. "
                "Try one section at a time or pick another model.",
                partial_text=text,
                output_limit=int(
                    body.get("max_tokens") or body.get("max_completion_tokens") or 0
                ),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                usage_reported=reported,
            )
        if choice.get("finish_reason") == "stop" and not text:
            details = usage.get("completion_tokens_details")
            details = details if isinstance(details, dict) else {}
            if (
                message.get("reasoning_content")
                or message.get("reasoning")
                or details.get("reasoning_tokens")
                or (
                    isinstance(message.get("content"), str)
                    and "<think" in message["content"].lower()
                )
            ):
                raise ModelReasoningOnlyError(
                    f"{who} ({endpoint.model}) returned only reasoning and no answer. "
                    "Try the question again or pick another model."
                )
            raise EmptyModelError(
                f"{who} ({endpoint.model}) returned no usable answer. "
                "Try again or pick another model."
            )
    except ProviderUnavailableError:
        raise
    except httpx.ConnectError as err:
        raise ProviderUnavailableError(
            f"Could not reach {who} at {endpoint.base_url}. Check your internet "
            "connection, or that the server is running."
        ) from err
    except httpx.TimeoutException as err:
        raise ProviderUnavailableError(
            f"{who} did not answer in time ({endpoint.model}). Try again or pick "
            "a faster model."
        ) from err
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as err:
        logger.warning(
            "unreadable reply from %s (task=%s, model=%s): %r",
            endpoint.name,
            task,
            endpoint.model,
            err,
        )
        raise ProviderUnavailableError(
            f"{who} sent a reply Stacks could not read ({endpoint.model}): {err}"
        ) from err
    return text, input_tokens, output_tokens


def _usage_count(value: Any) -> tuple[int, bool]:
    """Optional malformed usage must not discard an otherwise usable answer."""
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            value = int(value)
        except ValueError:
            return 0, False
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**63:
        return value, True
    return 0, False


# Request adjustments learned per (base_url, model) from the endpoint's own
# 400 replies. Process-local: a restart simply relearns them in one call.
_ADAPTATIONS: dict[tuple[str, str], set[str]] = {}
_DETAIL_LIMIT = 300


def _apply_adaptations(body: dict[str, Any], learned: set[str]) -> None:
    if "max_completion_tokens" in learned and "max_tokens" in body:
        body["max_completion_tokens"] = body.pop("max_tokens")
    if "no_temperature" in learned:
        body.pop("temperature", None)
    if "no_runtime_switches" in learned:
        body.pop("chat_template_kwargs", None)
        body.pop("reasoning_effort", None)


def _adaptation_for(status: int, detail: str, body: dict[str, Any]) -> str | None:
    """Which adjustment a 400 asks for, when it names a parameter we can
    drop or rename without changing what is asked."""
    if status != 400:
        return None
    lowered = detail.lower()
    if "max_completion_tokens" in lowered and "max_tokens" in body:
        return "max_completion_tokens"
    if "temperature" in lowered and "temperature" in body:
        return "no_temperature"
    if ("chat_template_kwargs" in lowered or "reasoning_effort" in lowered) and (
        "chat_template_kwargs" in body or "reasoning_effort" in body
    ):
        return "no_runtime_switches"
    return None


def provider_error_detail(response: Any) -> str:
    """The provider's own explanation from an error response, trimmed to one
    readable line. OpenAI-compatible APIs put it at error.message; OpenRouter
    nests the upstream provider's text under error.metadata.raw."""
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    text: Any = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            text = error.get("message")
            metadata = error.get("metadata")
            raw = metadata.get("raw") if isinstance(metadata, dict) else None
            if (
                isinstance(raw, str)
                and raw.strip()
                and (not text or "provider returned error" in str(text).lower())
            ):
                text = raw
        elif isinstance(error, str):
            text = error
        text = text or body.get("message") or body.get("detail")
    if not isinstance(text, str) or not text.strip():
        text = getattr(response, "text", "") or ""
    line = " ".join(str(text).split())
    return line if len(line) <= _DETAIL_LIMIT else line[: _DETAIL_LIMIT - 1] + "…"


def rejection_message(who: str, status: int, detail: str) -> str:
    """What the student reads when an endpoint refuses a request: the
    provider's own words plus the one setting most likely to fix it."""
    said = f': "{detail}"' if detail else ""
    lowered = detail.lower()
    if status == 401:
        hint = "The API key was not accepted; replace it in Settings."
    elif status == 402:
        hint = "The account has run out of credits."
    elif status == 404 or "model" in lowered:
        hint = (
            "Check the model name in Settings; Test on the connection lists "
            "the names it accepts."
        )
    elif status == 403:
        hint = "This key cannot use this model; pick a different model."
    else:
        hint = ""
    return f"{who} rejected the request ({status}){said}." + (
        f" {hint}" if hint else ""
    )


_THINK_BLOCK = re.compile(
    r"<think(?:\s[^>]*)?>.*?</think\s*>", re.IGNORECASE | re.DOTALL
)


def _visible_message_text(content: Any) -> str:
    """Read final text from OpenAI-compatible string or content-block replies.

    Some local chat templates put their private chain of thought inside
    ``<think>`` tags in the visible content. Never pass those tokens to
    downstream parsing or the UI. A reasoning model may send ``content:
    null`` when it spent the budget thinking.
    """
    if content is None:
        return ""
    if isinstance(content, list):
        pieces = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") in {"text", "output_text"}
            and isinstance(block.get("text"), str)
        ]
        content = "\n".join(pieces)
    if not isinstance(content, str):
        raise TypeError("message content is not text")
    visible = _THINK_BLOCK.sub("", content).strip()
    if re.search(r"<think(?:\s[^>]*)?>", visible, re.IGNORECASE):
        return ""
    return visible


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
_MODEL_LOAD_LOCK = threading.RLock()


def _load_embedding_backend() -> _EmbedBackend:
    with _MODEL_LOAD_LOCK:
        return _load_embedding_backend_locked()


def _load_embedding_backend_locked() -> _EmbedBackend:
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
    with _MODEL_LOAD_LOCK:
        _EMBEDDING_BACKEND = None


def embedding_token_count(text: str) -> int:
    """Count document tokens without the encoder's truncation or padding."""
    backend = _load_embedding_backend()
    counter = getattr(backend.model, "token_count", None)
    value = backend.policy.document_prefix + text
    if counter is None:
        # Custom backends without a tokenizer use a conservative byte budget.
        return len(value.encode("utf-8")) + 2
    return int(counter(value))


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


def rerank_scores(model_name: str, query: str, texts: Sequence[str]) -> list[float]:
    """Relevance of each text to the query from a cross-encoder (higher =
    more relevant). In-process and CPU-only, like the embedding seam:
    records nothing and sends nothing anywhere."""
    global _RERANKER, _RERANKER_NAME
    if not texts:
        return []
    with _MODEL_LOAD_LOCK:
        if _RERANKER is None or model_name != _RERANKER_NAME:
            from src.backend.common.encoders import RERANKER_SPECS, OnnxCrossEncoder

            spec = RERANKER_SPECS.get(model_name)
            if spec is None:
                raise ProviderUnavailableError(
                    f"no ONNX build registered for {model_name}"
                )
            _RERANKER, _RERANKER_NAME = OnnxCrossEncoder(spec), model_name
        model = _RERANKER
    scores = model.predict([(query, text) for text in texts])
    return [float(score) for score in scores]


def embed_query(text: str) -> list[float]:
    return embed_texts([text], kind="query")[0]


def embed_chunks(texts: Sequence[str]) -> list[list[float]]:
    return embed_texts(texts, kind="document")
