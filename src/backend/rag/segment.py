from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from src.backend.rag.config import PassagePolicy

_HEADING = re.compile(
    r"(?m)^(?:#{1,6}\s+.+|(?:chapter|section)\s+(?:\d+|[ivxlcdm]+)\b[^\n]*)$",
    re.IGNORECASE,
)
_PROOF_START = re.compile(r"(?im)^\s*(?:proof\b|demonstration\b)")
_PROOF_END = re.compile(r"(?im)(?:\bq\.?e\.?d\.?\s*$|[□∎]\s*$)")
_STATEMENT = re.compile(r"(?i)^\s*(?:theorem|lemma|proposition|corollary)\b")
_EXAMPLE_START = re.compile(r"(?i)^\s*(?:worked example|example)\s*(?:\d|:)")
_EXAMPLE_END = re.compile(r"(?i)^\s*end (?:of )?(?:worked )?example\b")
_LIST = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+\S")
_TABLE = re.compile(r"(?m)^\s*\|.+\|\s*$")
_EQUATION = re.compile(r"\$\$|\\\[|\\begin\{(?:equation|align)")
_DEFINITION = re.compile(r"(?i)^\s*(?:where|in which|here|with|that is)\b")
_WORD = re.compile(r"[^\W\d_]{2,}")
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*(?:\s|$)")
# A proof, example, table, or equation is one unit. Splitting it would
# separate the claim from its ending, or a row from its header.
_ATOMIC = frozenset({"table", "equation", "proof", "example"})


@dataclass(frozen=True)
class ContainerSpan:
    start: int
    end: int
    title: str
    level: int
    parent_index: int | None
    origin: str = "source"


@dataclass(frozen=True)
class PassageSpan:
    start: int
    end: int
    container_index: int | None
    kind: str
    boundary: str


@dataclass(frozen=True)
class Segmentation:
    containers: tuple[ContainerSpan, ...]
    passages: tuple[PassageSpan, ...]
    semantic_used: bool
    warning: str | None = None


def containers(text: str) -> tuple[ContainerSpan, ...]:
    headings = list(_HEADING.finditer(text))
    result: list[ContainerSpan] = []
    stack: list[int] = []
    for heading in headings:
        title = heading.group().strip()
        level = len(title) - len(title.lstrip("#")) if title.startswith("#") else 1
        while stack and result[stack[-1]].level >= level:
            stack.pop()
        end = next(
            (
                other.start()
                for other in headings
                if other.start() > heading.start()
                and (
                    len(other.group()) - len(other.group().lstrip("#"))
                    if other.group().startswith("#")
                    else 1
                )
                <= level
            ),
            len(text),
        )
        result.append(
            ContainerSpan(
                heading.start(),
                end,
                title.lstrip("# "),
                level,
                stack[-1] if stack else None,
            )
        )
        stack.append(len(result) - 1)
    return tuple(result)


def is_thin(text: str, minimum: int) -> bool:
    """True when a span is too small to retrieve on its own.

    A short complete sentence stays (a one-line definition is real
    evidence). A heading fragment, a blank, or a running head does not.
    """
    alnum = sum(char.isalnum() for char in text)
    if alnum >= minimum:
        return False
    words = _WORD.findall(text)
    return not (len(words) >= 2 and _SENTENCE_END.search(text))


def _crosses(start: int, end: int, breaks: Sequence[int]) -> bool:
    return any(start < boundary < end for boundary in breaks)


def _split_oversized(
    text: str,
    start: int,
    end: int,
    kind: str,
    target: int,
    count: Callable[[str], int],
) -> list[tuple[int, int, str]]:
    """Cut a block down to `target` tokens without overlapping pieces.

    Sentence ends and newlines win. A single line that is still too long
    is cut on a space, then on a character, so a block cannot stay oversized.
    """
    if kind in _ATOMIC or count(text[start:end]) <= target:
        return [(start, end, kind)]
    pieces: list[tuple[int, int, str]] = []
    cursor = start
    while cursor < end:
        if count(text[cursor:end]) <= target:
            pieces.append((cursor, end, "passage"))
            break
        lo, hi = cursor + 1, end
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if count(text[cursor:mid]) <= target:
                lo = mid
            else:
                hi = mid - 1
        limit = lo
        while limit > cursor and count(text[cursor:limit]) > target:
            limit -= 1
        if limit <= cursor:
            limit = min(end, cursor + 1)
        region = text[cursor:limit]
        cut = None
        for match in re.finditer(r"(?<=[.!?])\s+|\n", region):
            cut = cursor + match.end()
        if cut is None or cut <= cursor:
            space = text.rfind(" ", cursor + 1, limit)
            cut = space + 1 if space > cursor else limit
        if cut <= cursor:
            cut = min(end, cursor + 1)
        pieces.append((cursor, cut, "passage"))
        cursor = cut
    return pieces


def _blocks(
    text: str,
    start: int,
    end: int,
    *,
    target_tokens: int,
    token_count: Callable[[str], int],
) -> list[tuple[int, int, str]]:
    cuts = [
        start,
        *(start + match.end() for match in re.finditer(r"\n\s*\n", text[start:end])),
        end,
    ]
    raw = [(a, b) for a, b in zip(cuts, cuts[1:], strict=False) if a < b]
    result: list[tuple[int, int, str]] = []
    protected: tuple[int, str] | None = None
    for a, b in raw:
        block = text[a:b]
        if protected is None and (
            _PROOF_START.search(block) or _EXAMPLE_START.search(block)
        ):
            kind = "proof" if _PROOF_START.search(block) else "example"
            if (
                kind == "proof"
                and result
                and _STATEMENT.search(text[result[-1][0] : a])
            ):
                a = result.pop()[0]
            protected = (a, kind)
        if protected is not None:
            if _PROOF_END.search(block) or _EXAMPLE_END.search(block) or b == end:
                result.append((protected[0], b, protected[1]))
                protected = None
        else:
            kind = (
                "table"
                if _TABLE.search(block)
                else "list"
                if _LIST.search(block)
                else "equation"
                if _EQUATION.search(block)
                else "passage"
            )
            if result:
                previous_start, _, previous_kind = result[-1]
                previous_text = text[previous_start:a].rstrip()
                attached = (
                    kind in {"list", "table"}
                    and (previous_text.endswith(":") or previous_kind == kind)
                ) or (previous_kind == "equation" and _DEFINITION.search(block))
                if attached and token_count(text[previous_start:b]) <= target_tokens:
                    result[-1] = (
                        previous_start,
                        b,
                        previous_kind if kind == "passage" else kind,
                    )
                    continue
            result.append((a, b, kind))
    return result


def _absorb_thin(
    text: str,
    blocks: list[tuple[int, int, str, int | None]],
    minimum: int,
    target: int,
    count: Callable[[str], int],
    breaks: Sequence[int],
) -> list[tuple[int, int, str, int | None]]:
    """Pull a heading fragment or blank into the next real block.

    A thin tail with nothing after it extends the previous block. The
    extension is only the thin text, so it may pass the token target by
    that much rather than leaving a fragment passage behind.
    """
    if minimum <= 0:
        return blocks
    result: list[tuple[int, int, str, int | None]] = []
    index = 0
    while index < len(blocks):
        start, end, kind, owner = blocks[index]
        if not is_thin(text[start:end], minimum):
            result.append(blocks[index])
            index += 1
            continue
        absorbed_end = end
        absorbed_kind = kind
        nxt = index + 1
        while nxt < len(blocks):
            _n_start, n_end, n_kind, n_owner = blocks[nxt]
            # A proof or table already starts where its claim starts.
            # Pulling a heading into it would move that start.
            if n_kind in _ATOMIC or n_owner != owner or _crosses(start, n_end, breaks):
                break
            absorbed_end = n_end
            absorbed_kind = n_kind
            nxt += 1
            if not is_thin(text[start:absorbed_end], minimum):
                break
        if nxt == index + 1:
            if (
                result
                and result[-1][3] == owner
                and not _crosses(result[-1][0], end, breaks)
            ):
                prev_start, _, prev_kind, prev_owner = result[-1]
                result[-1] = (prev_start, end, prev_kind, prev_owner)
            else:
                result.append(blocks[index])
            index += 1
            continue
        for piece_start, piece_end, piece_kind in _split_oversized(
            text, start, absorbed_end, absorbed_kind, target, count
        ):
            result.append((piece_start, piece_end, piece_kind, owner))
        index = nxt
    return result


def segment(
    text: str,
    policy: PassagePolicy,
    *,
    encode: Callable[[list[str]], Sequence[Sequence[float]]] | None = None,
    token_count: Callable[[str], int] | None = None,
    structure: tuple[ContainerSpan, ...] | None = None,
    page_breaks: Sequence[int] | None = None,
) -> Segmentation:
    if not text.strip():
        return Segmentation((), (), False)
    count = token_count or (lambda value: len(value.encode("utf-8")) + 2)
    parents = structure if structure is not None else containers(text)
    breaks = tuple(
        sorted({point for point in (page_breaks or ()) if 0 < point < len(text)})
    )
    cuts = sorted(
        {
            0,
            len(text),
            *breaks,
            *(c.start for c in parents),
            *(c.end for c in parents),
        }
    )
    blocks: list[tuple[int, int, str, int | None]] = []
    for start, end in zip(cuts, cuts[1:], strict=False):
        owner = next(
            (
                i
                for i in reversed(range(len(parents)))
                if parents[i].start <= start < parents[i].end
            ),
            None,
        )
        for block_start, block_end, kind in _blocks(
            text, start, end, target_tokens=policy.target_tokens, token_count=count
        ):
            blocks.extend(
                (piece_start, piece_end, piece_kind, owner)
                for piece_start, piece_end, piece_kind in _split_oversized(
                    text, block_start, block_end, kind, policy.target_tokens, count
                )
            )
    blocks = _absorb_thin(
        text, blocks, policy.min_alnum_chars, policy.target_tokens, count, breaks
    )
    similarities: dict[int, float] = {}
    warning = None
    if policy.semantic_enabled and encode and len(blocks) > 1:
        try:
            boundary_texts = []
            for a, b, _, _ in blocks:
                value = text[a:b]
                bounded = windows(
                    value, policy.search_window_tokens, 0, token_count=count
                )
                if not bounded:
                    bounded = ((0, len(value)),)
                first, last = bounded[0], bounded[-1]
                boundary_texts.extend(
                    [value[first[0] : first[1]], value[last[0] : last[1]]]
                )
            vectors = np.asarray(encode(boundary_texts), dtype=float)
            if (
                vectors.ndim != 2
                or len(vectors) != len(blocks) * 2
                or not np.isfinite(vectors).all()
            ):
                raise ValueError("invalid boundary vectors")
            norms = np.linalg.norm(vectors, axis=1)
            if (norms <= 0).any():
                raise ValueError("empty boundary vectors")
            vectors /= norms[:, None]
            similarities = {
                i: float(vectors[(i - 1) * 2 + 1] @ vectors[i * 2])
                for i in range(1, len(blocks))
            }
        except Exception as exc:
            warning = f"semantic boundaries unavailable: {type(exc).__name__}"
    passages: list[PassageSpan] = []
    for i, (start, end, kind, owner) in enumerate(blocks):
        if not passages:
            passages.append(PassageSpan(start, end, owner, kind, "structure"))
            continue
        previous = passages[-1]
        continuous = similarities.get(i, 1.0) >= policy.boundary_similarity
        merge = (
            previous.container_index == owner
            and previous.kind == kind == "passage"
            and continuous
            and count(text[previous.start : end]) <= policy.target_tokens
            and not _crosses(previous.start, end, breaks)
        )
        if merge:
            passages[-1] = PassageSpan(
                previous.start, end, owner, kind, previous.boundary
            )
        else:
            reason = "semantic" if i in similarities and not continuous else "structure"
            passages.append(PassageSpan(start, end, owner, kind, reason))
    return Segmentation(parents, tuple(passages), bool(similarities), warning)


def windows(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
    *,
    token_count: Callable[[str], int] | None = None,
    max_windows: int | None = None,
) -> tuple[tuple[int, int], ...]:
    if not text:
        return ()
    if not 0 <= overlap_tokens < max_tokens:
        raise ValueError("window overlap must be smaller than its window")
    count = token_count or (lambda value: len(value.encode("utf-8")) + 2)
    result: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        lo, hi = start + 1, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if count(text[start:mid]) <= max_tokens:
                lo = mid
            else:
                hi = mid - 1
        end = lo
        while end > start and count(text[start:end]) > max_tokens:
            end -= 1
        if end == start:
            raise ValueError("one character exceeds the search-window token budget")
        if end < len(text):
            space = text.rfind(" ", start, end)
            if space > start:
                end = space + 1
        result.append((start, end))
        if end == len(text) or (max_windows is not None and len(result) >= max_windows):
            break
        overlap_start = end
        while (
            overlap_start > start
            and count(text[overlap_start - 1 : end]) <= overlap_tokens
        ):
            overlap_start -= 1
        start = max(start + 1, overlap_start)
    return tuple(result)
