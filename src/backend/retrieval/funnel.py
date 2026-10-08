"""Keyword, vector and bounded graph retrieval over the same source passages."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

import numpy as np
from src.backend.common.db import Connection, json_ids
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.queries import get
from src.backend.rag import generated
from src.backend.rag.config import load_policy as load_passage_policy
from src.backend.rag.segment import is_thin
from src.backend.retrieval.config import RetrievalPolicy

_FILE = "retrieval"

KEYWORD = "keyword"
GRAPH = "graph"
CONTEXT = "context"
GENERATED = "generated_lookup"
EMBEDDING = "embedding"

# Only letters and digits (of any script) survive keyword tokenization.
# Everything else — including every FTS5 operator ( ) " * ^ : + - and the
# NEAR/AND/OR/NOT keywords' punctuation — is stripped BEFORE the string is
# split, so a math query like "f(x) = x^2" can never smuggle query syntax
# into MATCH. Not just [a-z0-9]: that cut "sociología" into "sociolog" and
# "Émile" into "mile", which match nothing the index holds (its tokenizer
# is unicode-aware and folds diacritics itself).
_TOKEN_RE = re.compile(r"[^\W_]+")

# FTS5 has no stopword filter (Postgres's 'english' config had one), and
# with OR semantics a stopword would match nearly every chunk. This is the
# Snowball English list Postgres used, so ranking behaviour carries over.
STOPWORDS = frozenset(
    {
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
    }
)


def _keyword_tokens(query: str) -> list[str]:
    lowered = unicodedata.normalize("NFC", query).lower()
    tokens = _TOKEN_RE.findall(lowered)
    unique: list[str] = []
    for token in tokens:
        # A single letter matches everything; a single CJK character is a word.
        if (
            (len(token) >= 2 or not token.isascii())
            and token not in STOPWORDS
            and token not in unique
        ):
            unique.append(token)
    return unique


def _fts_match(tokens: list[str]) -> str:
    """OR-join sanitized tokens as quoted FTS5 strings. Quoting keeps a
    token that happens to be an FTS5 keyword (e.g. "near", "not") literal;
    tokens are letters and digits so they can never contain a quote."""
    return " OR ".join(f'"{token}"' for token in tokens)


@dataclass(frozen=True)
class Candidate:
    """One chunk candidate with every layer that surfaced it.

    `rank` is seam-local on ARRIVAL (negated bm25, dot product, or arrival
    position) and is normalized to 0..1 inside fuse() before any
    comparison — that normalization is what makes cross-seam comparison
    legal. After normalization the ranks ARE comparable: a source's
    relevance is its best chunk's normalized rank."""

    chunk_id: UUID
    source_id: UUID
    locator_id: UUID | None
    chunk_index: int
    text: str
    layers: frozenset[str]
    rank: float
    window_start: int = 0
    window_end: int | None = None
    text_length: int | None = None
    partial: bool = False
    generated_materials: tuple[tuple[str, str, int], ...] = ()
    context_for: frozenset[UUID] = frozenset()
    chunk_char_start: int | None = None
    chunk_char_end: int | None = None
    source_filename: str = ""
    source_type: str = ""
    container_title: str = ""
    # Absolute locator spans (start, end, label) for the chunk's pages.
    locators: tuple[tuple[int, int, str], ...] = ()


@dataclass(frozen=True)
class RetrievalResult:
    candidates: tuple[Candidate, ...]
    layer_contribution: dict[str, int] = field(default_factory=dict)


def _rows_to_candidates(
    rows: list[dict[str, Any]], layer: str
) -> dict[UUID, Candidate]:
    out: dict[UUID, Candidate] = {}
    for position, row in enumerate(rows):
        raw_rank = row.get("rank")
        rank = float(raw_rank) if raw_rank is not None else float(-position)
        out[row["chunk_id"]] = Candidate(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            locator_id=row["locator_id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            layers=frozenset({layer}),
            rank=rank,
        )
    return out


def keyword_seam(
    conn: Connection,
    course_id: UUID,
    query: str,
    limit: int,
    source_ids: Collection[UUID] | None = None,
) -> dict[UUID, Candidate]:
    """FTS5 match with OR semantics (any term overlap counts; AND
    semantics would miss chunks holding only part of the question).
    Tokens are extracted with a strict [a-z0-9]+ regex before any SQL, so
    FTS5 query syntax can never reach the parser — math questions
    ("f(x) = x^2") must not crash retrieval. Single characters and
    stopwords are dropped (they match everything). Empty token sets match
    nothing."""
    tokens = _keyword_tokens(query)
    if not tokens:
        return {}
    rows = conn.execute(
        get(_FILE, "keyword_candidates"),
        {
            "course_id": course_id,
            "match": _fts_match(tokens),
            "limit": limit,
            "source_ids": json_ids(source_ids) if source_ids is not None else None,
        },
    ).fetchall()
    return _rows_to_candidates(rows, KEYWORD)


def embedding_seam(
    conn: Connection,
    course_id: UUID,
    query_embedding: list[float] | None,
    model: str,
    limit: int,
    source_ids: Collection[UUID] | None = None,
) -> dict[UUID, Candidate]:
    """Vector ranking. Dormant (empty) until embeddings exist; the caller
    passes None when there is no query embedding. Rank is the dot product
    (higher = closer; vectors are normalized at encode time).

    Dimension guard: a stored vector whose dimension differs from the
    query's (a model swap under the same name) is excluded, never scored —
    comparing mismatched vector spaces would rank garbage silently."""
    if not query_embedding:
        return {}
    rows = conn.execute(
        get(_FILE, "embedding_rows"),
        {
            "course_id": course_id,
            "model": model,
            "source_ids": json_ids(source_ids) if source_ids is not None else None,
        },
    ).fetchall()
    dimension = len(query_embedding)
    rows = [
        row
        for row in rows
        if row["dimension"] == dimension
        and len(row["embedding"]) == dimension * np.dtype("<f4").itemsize
    ]
    if not rows:
        return {}
    matrix = np.frombuffer(
        b"".join(row["embedding"] for row in rows), dtype="<f4"
    ).reshape(len(rows), dimension)
    query_vector = np.asarray(query_embedding, dtype=np.float32)
    if not np.isfinite(query_vector).all():
        return {}
    valid = np.isfinite(matrix).all(axis=1)
    rows = [row for row, keep in zip(rows, valid, strict=True) if keep]
    matrix = matrix[valid]
    if not rows:
        return {}
    scores = matrix @ query_vector
    top = np.argsort(-scores, kind="stable")
    selected: list[tuple[int, dict[str, Any]]] = []
    seen = set()
    for index in top:
        row = rows[int(index)]
        if row["chunk_id"] in seen:
            continue
        if len(selected) >= limit:
            break
        seen.add(row["chunk_id"])
        selected.append((int(index), row))
    originals = conn.execute(
        get("passages", "eligible_support"),
        {
            "course_id": course_id,
            "chunk_ids": json_ids(seen),
            "source_ids": json_ids(source_ids) if source_ids is not None else None,
        },
    ).fetchall()
    texts = {row["chunk_id"]: row["text"] for row in originals}
    out: dict[UUID, Candidate] = {}
    for index, row in selected:
        if row["chunk_id"] not in texts:
            continue
        out[row["chunk_id"]] = Candidate(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            locator_id=row["locator_id"],
            chunk_index=row["chunk_index"],
            text=texts[row["chunk_id"]],
            layers=frozenset({EMBEDDING}),
            rank=float(scores[int(index)]),
            window_start=row["window_start"],
            window_end=row["window_end"],
        )
    return out


def graph_seam(
    conn: Connection,
    course_id: UUID,
    hits: dict[UUID, Candidate],
    limit: int,
    model: str,
    source_ids: Collection[UUID] | None = None,
    *,
    dimension: int | None = None,
) -> dict[UUID, Candidate]:
    if not hits or limit < 1:
        return {}
    params = {
        "course_id": course_id,
        "chunk_ids": json_ids(hits),
        "limit": limit,
        "model": model,
        "dimension": (
            dimension if dimension is not None else load_embedding_policy().dimension
        ),
        "source_ids": json_ids(source_ids) if source_ids is not None else None,
    }
    rows = conn.execute(get(_FILE, "similar_candidates"), params).fetchall()
    return _rows_to_candidates(rows, GRAPH)


def _normalize(seam: dict[UUID, Candidate]) -> dict[UUID, Candidate]:
    """Min-max a seam's ranks into 0.0..1.0 without changing its candidates.

    Every seam's local rank is already higher-is-better: keyword uses
    negated bm25, while embeddings and similarity use normalized dot products.
    Normalization preserves that direction across different score ranges.

    A seam of one candidate (or all-equal ranks) normalizes to a
    mid-strength 0.5 — it IS weak information, not zero."""
    if not seam:
        return {}
    ranks = [candidate.rank for candidate in seam.values()]
    low, high = min(ranks), max(ranks)
    if high <= low:
        return {
            chunk_id: replace(candidate, rank=0.5)
            for chunk_id, candidate in seam.items()
        }
    span = high - low
    return {
        chunk_id: replace(candidate, rank=(candidate.rank - low) / span)
        for chunk_id, candidate in seam.items()
    }


def fuse(
    keyword: dict[UUID, Candidate],
    embeddings: dict[UUID, Candidate],
    graph: dict[UUID, Candidate] | None = None,
    *,
    policy: RetrievalPolicy,
    generated_hits: dict[UUID, Candidate] | None = None,
) -> tuple[Candidate, ...]:
    """Normalize each seam to a common 0..1 scale, then allocate the
    final_k slots across sources by relevance (largest remainder), then
    fill each source's slots with its best chunks. "Relevance" of a
    source = the best normalized score any of its chunks earned from any
    seam — the softmax-style allocation the design conversation settled
    on, with three guardrails:

    - A floor of one slot per contributing source (relevance can say a
      lecture barely matters, but it DID match; dropping it entirely is
      the evaluator's job, not the mixer's).
    - Slots are clamped to each source's available candidates (a source
      with 2 chunks cannot hold 7 slots; the remainder reflows).
    - Allocation is by best-chunk score, not volume: a lecture that
      mentions the topic 20 times does not outrank one that explains it
      once (the known failure mode of volume-weighted allocation).

    Embedding-only candidates still enter through their quota, admitted
    after allocated slots (semantic expansion must not displace
    grounded hits). A single-source course fills naturally — no source
    can starve another when there is no competition."""
    keyword = _normalize(keyword)
    graph = _normalize(graph or {})
    embeddings = _normalize(embeddings)
    annotations = {
        identity: replace(
            candidate, rank=candidate.rank * policy.generated_lookup_weight
        )
        for identity, candidate in _normalize(generated_hits or {}).items()
    }

    merged: dict[UUID, Candidate] = {}
    for seam in (keyword, embeddings, graph, annotations):
        for chunk_id, candidate in seam.items():
            if chunk_id in merged:
                existing = merged[chunk_id]
                merged[chunk_id] = replace(
                    candidate if candidate.window_end is not None else existing,
                    layers=existing.layers | candidate.layers,
                    rank=max(existing.rank, candidate.rank),
                    generated_materials=tuple(
                        dict.fromkeys(
                            existing.generated_materials + candidate.generated_materials
                        )
                    ),
                )
            else:
                merged[chunk_id] = candidate

    best_by_source: dict[UUID, float] = {}
    for candidate in merged.values():
        current = best_by_source.get(candidate.source_id)
        if current is None or candidate.rank > current:
            best_by_source[candidate.source_id] = candidate.rank

    total_weight = sum(best_by_source.values())
    available_by_source: dict[UUID, int] = {}
    for candidate in merged.values():
        available_by_source[candidate.source_id] = (
            available_by_source.get(candidate.source_id, 0) + 1
        )
    k = policy.final_k
    contributing = len(best_by_source)
    grounded_present = bool(keyword or graph)
    if total_weight <= 0 or contributing == 0:
        # Degenerate (all-zero scores): equal split, availability-clamped.
        quotas = {
            sid: min(k // contributing, avail) if contributing else 0
            for sid, avail in available_by_source.items()
        }
    else:
        raw = {sid: weight / total_weight * k for sid, weight in best_by_source.items()}
        # Largest-remainder: floor everything, hand leftover slots to the
        # biggest fractional remainders (Hare quota — deterministic).
        quotas = {
            sid: min(int(allocation), available_by_source[sid])
            for sid, allocation in raw.items()
        }
        remainder = k - sum(quotas.values())
        by_remainder = sorted(
            raw.items(),
            key=lambda item: (item[1] - int(item[1]), -raw[item[0]]),
            reverse=True,
        )
        # A min-1 floor per contributing source (bounded by availability)
        # keeps weak-but-matching lectures represented. Floor first, then
        # remaining remainder goes by largest fractional part.
        for sid, _ in by_remainder:
            if remainder <= 0:
                break
            if quotas[sid] == 0 and available_by_source[sid] > 0:
                quotas[sid] = 1
                remainder -= 1
        for sid, _ in by_remainder:
            if remainder <= 0:
                break
            headroom = available_by_source[sid] - quotas[sid]
            if headroom > 0:
                give = min(headroom, remainder)
                quotas[sid] += give
                remainder -= give

    ordered = sorted(
        merged.values(), key=lambda c: (-c.rank, c.chunk_index, c.chunk_id)
    )
    final: list[Candidate] = []
    taken: dict[UUID, int] = {}
    embedding_only_admitted = 0
    # The quota exists to keep semantic expansion from displacing
    # keyword/similarity hits. When no seam found anything
    # grounded, embeddings are not "expansion" — they are the only
    # evidence there is, so the quota does not apply.
    embedding_quota = policy.embedding_only_quota if grounded_present else k
    for candidate in ordered:
        if len(final) >= k:
            break
        is_embedding_only = candidate.layers == frozenset({EMBEDDING})
        if is_embedding_only and embedding_only_admitted >= embedding_quota:
            continue
        if taken.get(candidate.source_id, 0) >= quotas.get(candidate.source_id, 0):
            continue
        taken[candidate.source_id] = taken.get(candidate.source_id, 0) + 1
        if is_embedding_only:
            embedding_only_admitted += 1
        final.append(candidate)
    # Unallocated budget (sources too small to fill quotas): backfill in
    # global order so final_k is met when candidates exist.
    if len(final) < k:
        allocated_ids = {c.chunk_id for c in final}
        for candidate in ordered:
            if len(final) >= k:
                break
            if candidate.chunk_id in allocated_ids:
                continue
            is_embedding_only = candidate.layers == frozenset({EMBEDDING})
            if is_embedding_only and embedding_only_admitted >= embedding_quota:
                continue
            if is_embedding_only:
                embedding_only_admitted += 1
            final.append(candidate)
    return tuple(final)


def _keep_substantive(
    candidates: dict[UUID, Candidate], minimum: int
) -> dict[UUID, Candidate]:
    """Drop blanks and heading fragments before they take a final slot."""
    return {
        chunk_id: candidate
        for chunk_id, candidate in candidates.items()
        if not is_thin(candidate.text, minimum)
    }


def surrounding_context(
    conn: Connection,
    course_id: UUID,
    anchors: tuple[Candidate, ...],
    model: str,
    source_ids: Collection[UUID] | None,
) -> tuple[Candidate, ...]:
    policy = load_passage_policy()
    if not anchors or policy.context_neighbors == 0:
        return anchors
    rows = conn.execute(
        get("passages", "eligible_neighbors"),
        {
            "course_id": course_id,
            "chunk_ids": json_ids(c.chunk_id for c in anchors),
            "source_ids": json_ids(source_ids) if source_ids is not None else None,
            "radius": policy.context_neighbors,
            "limit": len(anchors) * policy.context_neighbors * 2,
            "model": model,
        },
    ).fetchall()
    result = {c.chunk_id: c for c in anchors}
    for row in rows:
        if row["chunk_id"] in {c.chunk_id for c in anchors}:
            continue
        if is_thin(row["text"], policy.min_alnum_chars):
            continue
        a, b = row["anchor_vector"], row["neighbor_vector"]
        if a and b and row["anchor_dimension"] == row["neighbor_dimension"]:
            dimension = row["anchor_dimension"]
            if len(a) != dimension * 4 or len(b) != dimension * 4:
                continue
            av, bv = np.frombuffer(a, dtype="<f4"), np.frombuffer(b, dtype="<f4")
            norm = float(np.linalg.norm(av) * np.linalg.norm(bv))
            if not np.isfinite(av).all() or not np.isfinite(bv).all() or norm <= 0:
                continue
            similarity = float(av @ bv) / norm
            qualification = re.match(
                r"\s*(?:however|except|unless|assuming|provided|note that|but)\b",
                row["text"],
                re.IGNORECASE,
            )
            if similarity < policy.context_similarity and not qualification:
                continue
        elif row["distance"] > 1:
            continue
        prior = result.get(row["chunk_id"])
        candidate = _rows_to_candidates([row], CONTEXT)[row["chunk_id"]]
        result[candidate.chunk_id] = replace(
            candidate,
            context_for=(prior.context_for if prior else frozenset())
            | {row["anchor_id"]},
        )
    return tuple(result.values())


def retrieve(
    conn: Connection,
    course_id: UUID,
    query: str,
    policy: RetrievalPolicy,
    *,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
    source_ids: Collection[UUID] | None = None,
) -> RetrievalResult:
    """Run every seam, fuse, attribute layers. Trace persistence is the
    caller's job (the tutor flow owns the transaction).

    `source_ids` narrows each SQL seam before its candidate limit (a chat's
    source selection); None searches the whole course. This ensures noisy,
    unselected sources cannot consume the selected sources' candidate slots."""
    minimum = load_passage_policy().min_alnum_chars
    keyword = _keep_substantive(
        keyword_seam(conn, course_id, query, policy.keyword_limit, source_ids),
        minimum,
    )
    embeddings = _keep_substantive(
        embedding_seam(
            conn,
            course_id,
            query_embedding,
            embedding_model or "",
            policy.embedding_limit,
            source_ids,
        ),
        minimum,
    )
    graph = _keep_substantive(
        graph_seam(
            conn,
            course_id,
            {**keyword, **embeddings},
            policy.graph_limit,
            embedding_model or "",
            source_ids,
            dimension=load_embedding_policy().dimension,
        ),
        minimum,
    )
    final = fuse(keyword, embeddings, graph, policy=policy)
    generated_rows = generated.lookup(
        conn, course_id, _keyword_tokens(query), policy.graph_limit, source_ids
    )
    if generated_rows:
        generated_hits = _keep_substantive(
            _rows_to_candidates(generated_rows, GENERATED), minimum
        )
        for row in generated_rows:
            hit = generated_hits.get(row["chunk_id"])
            if hit is None:
                continue
            generated_hits[row["chunk_id"]] = replace(
                hit,
                generated_materials=(
                    (
                        str(row["generated_artifact_id"]),
                        row["generated_title"],
                        row["generated_version"],
                    ),
                ),
            )
        if generated_hits:
            final = fuse(
                keyword,
                embeddings,
                graph,
                policy=policy,
                generated_hits=generated_hits,
            )
    final = surrounding_context(
        conn, course_id, final, embedding_model or "", source_ids
    )
    contribution: dict[str, int] = {}
    for candidate in final:
        for layer in candidate.layers:
            contribution[layer] = contribution.get(layer, 0) + 1
    return RetrievalResult(
        candidates=final,
        layer_contribution=contribution,
    )


OVERVIEW = "overview"


def overview(
    conn: Connection,
    course_id: UUID,
    limit: int,
    *,
    embedding_model: str | None = None,
    source_ids: Collection[UUID] | None = None,
) -> RetrievalResult:
    """A spread of the course: `limit` passages, shared evenly among its
    sources and spaced out through each one. For a request about the course
    as a whole ("make me a study guide", "what is this course about?"),
    whose words match no particular passage — searching by them returns
    whatever happens to sit nearest to the phrase "study guide"."""
    rows = conn.execute(
        get("passages", "course_passages"),
        {
            "course_id": course_id,
            "model": embedding_model or "",
            "source_ids": json_ids(source_ids) if source_ids is not None else None,
        },
    ).fetchall()
    by_source: dict[UUID, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda r: (str(r["source_id"]), r["chunk_index"])):
        by_source.setdefault(row["source_id"], []).append(row)
    if not by_source or limit < 1:
        return RetrievalResult(candidates=())
    per_source = max(1, limit // len(by_source))
    picked: list[dict[str, Any]] = []
    for chunks in list(by_source.values())[:limit]:
        take = min(len(chunks), per_source)
        if take == 1:
            picked.append(chunks[0])
            continue
        # Spread over the whole source, first and last chunk included, so a
        # source's opening and closing material both reach the overview (CR-12).
        picked.extend(
            chunks[index * (len(chunks) - 1) // (take - 1)] for index in range(take)
        )
    final = tuple(
        Candidate(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            locator_id=row["locator_id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            layers=frozenset({OVERVIEW}),
            rank=0.5,
        )
        for row in picked[:limit]
    )
    return RetrievalResult(candidates=final, layer_contribution={OVERVIEW: len(final)})
