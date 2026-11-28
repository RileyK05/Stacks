"""When to ask a provider to cache a prompt prefix, and where it ends.

Stacks makes one-shot calls: a chat turn retrieves different passages each
time, so consecutive turns share no long prefix and caching them would only
pay the write premium (1.25x input on Claude for a 5-minute entry, with
reads at 0.1x). Prefixes do repeat in bursts: a quiz the checks rejected is
regenerated from the same instruction and material, a cut-off reply is
re-asked whole. So caching is switched on per (model, task) when that pair
has recently sent the same prefix again within the cache's lifetime, and a
prefix already seen in that window is cached at once.

The prefix ends at the course-material fence (prompt_registry.grounded_prompt
puts what differs between attempts after it).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque

from src.backend.common.prompt_registry import UNTRUSTED_END

# The provider's default cache lifetime.
WINDOW_SECONDS = 300.0
# Below this a prefix is not worth marking (and the newest Claude models do
# not cache under 512 tokens; ~4 bytes per token).
MIN_PREFIX_CHARS = 4096
_HISTORY = 20
_RATE = 0.3

_LOCK = threading.Lock()
_SEEN: dict[tuple[str, str], dict[str, float]] = {}
_REPEATS: dict[tuple[str, str], deque[bool]] = {}


def split(prompt: str) -> tuple[str, str]:
    """(shared prefix, varying tail): the prefix runs through the first
    material fence; a prompt without one has no tail."""
    end = prompt.find(UNTRUSTED_END)
    if end < 0:
        return prompt, ""
    cut = end + len(UNTRUSTED_END)
    return prompt[:cut], prompt[cut:]


def should_cache(model: str, task: str, prefix: str) -> bool:
    """Record this prefix and say whether to mark it for caching."""
    if len(prefix) < MIN_PREFIX_CHARS:
        return False
    key = (model, task)
    digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _LOCK:
        seen = _SEEN.setdefault(key, {})
        for old, at in list(seen.items()):
            if now - at > WINDOW_SECONDS:
                del seen[old]
        repeat = digest in seen
        seen[digest] = now
        history = _REPEATS.setdefault(key, deque(maxlen=_HISTORY))
        history.append(repeat)
        rate = sum(history) / len(history)
    return repeat or (len(history) >= 5 and rate >= _RATE)


def reset() -> None:
    with _LOCK:
        _SEEN.clear()
        _REPEATS.clear()
