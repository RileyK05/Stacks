"""One bounded operation for output recovery and nested content/schema repairs.

Counts cover requests, not just delivered answers. Estimated input reservations
are internal safeguards; only provider-reported counts belong in the usage ledger.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from src.backend.common import model_profiles, providers
from src.backend.common.generation_config import (
    GenerationPolicy,
    load_generation_policy,
)
from src.backend.common.providers import ResolvedProvider


class GenerationLimitError(RuntimeError):
    """A request cannot fit, or its shared recovery allowance is exhausted."""


@dataclass(frozen=True)
class CallLimits:
    output_tokens: int
    output_ceiling: int
    input_tokens_estimate: int
    context_tokens: int | None
    available_output_tokens: int | None
    max_recoveries: int
    images: bool = False

    def wider(self) -> CallLimits | None:
        ceiling = self.output_ceiling
        if self.available_output_tokens is not None:
            if self.images:
                # Image token costs are not inferred from PNG byte counts.
                return None
            ceiling = min(ceiling, self.available_output_tokens)
        allowance = min(self.output_tokens * 2, ceiling)
        return (
            replace(self, output_tokens=allowance)
            if allowance > self.output_tokens
            else None
        )


def plan_call(
    task: str,
    endpoint: ResolvedProvider,
    prompt: str,
    *,
    response_schema: dict[str, Any] | None = None,
    images: bool = False,
    policy: GenerationPolicy | None = None,
) -> CallLimits:
    policy = policy or load_generation_policy()
    demand = policy.tasks[task]
    defaults = providers.load_models_config().generation
    profile = model_profiles.profile_for(endpoint.model)
    preferred = (
        profile.max_output_tokens
        if profile and profile.max_output_tokens is not None
        else defaults.max_output_tokens
    )
    ceiling = profile.output_token_limit if profile else None
    ceiling = ceiling or preferred
    thinking = profile.reasoning if profile else defaults.enable_thinking
    desired = preferred if thinking else min(demand.desired_output_tokens, preferred)
    output = min(desired, ceiling)
    context = profile.context_window_tokens if profile else None
    if endpoint.name == "local":
        from src.backend.runtime.config import load_runtime_config
        from src.backend.runtime.user_models import find_model

        if find_model(endpoint.model) is not None:
            allocated = load_runtime_config().llama_cpp.context_size
            context = min(context, allocated) if context is not None else allocated
            # The managed llama-server has no smaller separate output allocation.
            ceiling = (
                min(ceiling, context)
                if profile and profile.output_token_limit
                else context
            )
    framing = json.dumps(response_schema, ensure_ascii=False) if response_schema else ""
    estimate = (
        math.ceil(
            len((prompt + framing).encode("utf-8")) / policy.input_bytes_per_token
        )
        + policy.framing_tokens
    )
    available = (
        context - estimate - policy.context_margin_tokens
        if context is not None
        else None
    )
    if available is not None:
        if available < policy.min_output_tokens:
            raise GenerationLimitError(
                "This request has too much material for the selected model. "
                "Select fewer sources, focus on one section, or choose another model."
            )
        output = min(output, available)
    return CallLimits(
        output, ceiling, estimate, context, available, demand.max_recoveries, images
    )


@dataclass
class Operation:
    policy: GenerationPolicy
    clock: Callable[[], float] = field(default_factory=lambda: time.monotonic)
    started: float = field(init=False)
    calls: int = 0
    http_requests: int = 0
    requested_tokens: int = 0
    reported_input_tokens: int = 0
    reported_output_tokens: int = 0
    missing_usage_calls: int = 0
    endpoints: dict[str, ResolvedProvider | None] = field(default_factory=dict)
    local_fallbacks: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.started = self.clock()

    def remaining_seconds(self) -> float:
        remaining = self.policy.max_elapsed_seconds - (self.clock() - self.started)
        if remaining <= 0:
            raise GenerationLimitError(
                "Preparing this response took too long. Try a more focused request "
                "or choose a faster model."
            )
        return remaining

    def reserve(self, tokens: int) -> None:
        self.remaining_seconds()
        if self.requested_tokens + tokens > self.policy.max_requested_tokens:
            raise GenerationLimitError(
                "I couldn't finish this request within its generation allowance. "
                "Try one section at a time or choose another model."
            )
        self.requested_tokens += tokens

    def begin_call(self, limits: CallLimits) -> None:
        if self.calls >= self.policy.max_calls:
            raise GenerationLimitError(
                "I couldn't finish a usable response after several attempts. "
                "Try a more focused request or another model."
            )
        self.reserve(limits.input_tokens_estimate + limits.output_tokens)
        self.calls += 1

    def endpoint(
        self, key: str, resolve: Callable[[], ResolvedProvider | None]
    ) -> ResolvedProvider | None:
        if key not in self.endpoints:
            self.endpoints[key] = resolve()
        return self.endpoints[key]

    def record_usage(self, inputs: int, outputs: int, reported: bool) -> None:
        self.reported_input_tokens += inputs
        self.reported_output_tokens += outputs
        if not reported:
            self.missing_usage_calls += 1


@dataclass
class _Call:
    operation: Operation
    limits: CallLimits
    http_requests: int = 0

    def before_http(self, body: dict[str, Any]) -> float:
        op = self.operation
        remaining = op.remaining_seconds()
        if op.http_requests >= op.policy.max_http_requests:
            raise GenerationLimitError(
                "The model couldn't complete this response after several requests. "
                "Try again with a more focused request or another model."
            )
        if self.http_requests:
            output = int(
                body.get("max_tokens")
                or body.get("max_completion_tokens")
                or self.limits.output_tokens
            )
            op.reserve(self.limits.input_tokens_estimate + output)
        self.http_requests += 1
        op.http_requests += 1
        return remaining


_OPERATION: ContextVar[Operation | None] = ContextVar(
    "generation_operation", default=None
)
_CALL: ContextVar[_Call | None] = ContextVar("generation_call", default=None)


@contextmanager
def operation(
    policy: GenerationPolicy | None = None, *, clock: Callable[[], float] | None = None
) -> Iterator[Operation]:
    active = _OPERATION.get()
    if active is not None:
        yield active
        return
    active = Operation(policy or load_generation_policy(), clock or time.monotonic)
    token = _OPERATION.set(active)
    try:
        yield active
    finally:
        _OPERATION.reset(token)


def output_allowance() -> int | None:
    active = _CALL.get()
    return active.limits.output_tokens if active is not None else None


def before_http(body: dict[str, Any]) -> float | None:
    active = _CALL.get()
    return active.before_http(body) if active is not None else None


def record_usage(inputs: int, outputs: int, reported: bool = True) -> None:
    active = _OPERATION.get()
    if active is not None:
        active.record_usage(inputs, outputs, reported)


Recovery = Literal["empty", "length"]


def complete[T](
    limits: CallLimits,
    invoke: Callable[[], T],
    classify: Callable[[Exception], Recovery | None],
) -> T:
    """Regenerate a complete bounded unit; never splice incomplete JSON."""
    with operation() as op:
        recovered = 0
        empty_retried = False
        while True:
            op.begin_call(limits)
            token = _CALL.set(_Call(op, limits))
            try:
                result = invoke()
                op.remaining_seconds()
                return result
            except Exception as error:
                kind = classify(error)
                if recovered >= limits.max_recoveries or kind is None:
                    raise
                if kind == "empty":
                    if empty_retried:
                        raise
                    empty_retried = True
                else:
                    wider = limits.wider()
                    if wider is None:
                        raise
                    limits = wider
                recovered += 1
            finally:
                _CALL.reset(token)
