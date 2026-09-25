"""The retrieval funnel (decision 008, revised): four seams, normalized
then allocated — not raw-scored.

Seams:
- keyword: FTS5 bm25 match (works day one, zero model dependency)
- toc: static matching of the query against entry titles/descriptions,
  chunks under matched entries' locators (dormant without entries)
- dependency walk: matched concepts -> 1-hop prereq/dependent chunks
  (dormant without edges; only trusted edges passed in)
- embeddings: ranks the merged set by meaning when present (dormant
  without a provider); absent, a deterministic order applies

Fusion: each seam's ranks are min-max normalized INTO 0..1 (the unit
accident — ts_rank ~0.06 vs dependency position 8 — made cross-seam
comparison meaningless before this; bm25 scores have the same problem).
Every seam ranks "higher is better", so normalization preserves
direction for all of them. A
source's relevance is its best chunk's normalized score from any seam;
the final_k slots are split across sources proportionally (largest
remainder) with a one-slot floor per contributing source, availability
clamping, and backfill. Every surviving chunk carries its locator id;
the layer contribution is returned for the trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import numpy as np
from src.backend.common.db import Connection, json_ids
from src.backend.common.queries import get
from src.backend.retrieval.config import RetrievalPolicy

_FILE = "retrieval"

KEYWORD = "keyword"
TOC = "toc"
DEPENDENCY = "dependency"
EMBEDDING = "embedding"

# Only these characters survive keyword tokenization. Everything else —
# including every FTS5 operator ( ) " * ^ : + - and the NEAR/AND/OR/NOT
# keywords' punctuation — is stripped BEFORE the string is split, so a
# math query like "f(x) = x^2" can never smuggle query syntax into MATCH.
# Tokens must contain at least one letter or digit.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# FTS5 has no stopword filter (Postgres's 'english' config had one), and
# with OR semantics a stopword would match nearly every chunk. This is the
# Snowball English list Postgres used, so ranking behaviour carries over.
STOPWORDS = frozenset(
    {
        "a", "about", "above", "after", "again", "against", "all", "am", "an",
        "and", "any", "are", "as", "at", "be", "because", "been", "before", "being",
        "below", "between", "both", "but", "by", "can", "could", "did", "do",
        "does", "doing", "down", "during", "each", "few", "for", "from", "further",
        "had", "has", "have", "having", "he", "her", "here", "hers", "herself",
        "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its",
        "itself", "just", "me", "more", "most", "my", "myself", "no", "nor", "not",
        "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours",
        "ourselves", "out", "over", "own", "same", "she", "should", "so", "some",
        "such", "than", "that", "the", "their", "theirs", "them", "themselves",
        "then", "there", "these", "they", "this", "those", "through", "to", "too",
        "under", "until", "up", "very", "was", "we", "were", "what", "when",
        "where", "which", "while", "who", "whom", "why", "will", "with", "would",
        "you", "your", "yours", "yourself", "yourselves",
    }
)


def _keyword_tokens(query: str) -> list[str]:
    lowered = query.lower()
    tokens = _TOKEN_RE.findall(lowered)
    unique: list[str] = []
    for token in tokens:
        if len(token) >= 2 and token not in STOPWORDS and token not in unique:
            unique.append(token)
    return unique


def _fts_match(tokens: list[str]) -> str:
    """OR-join sanitized tokens as quoted FTS5 strings. Quoting keeps a
    token that happens to be an FTS5 keyword (e.g. "near", "not") literal;
    tokens are [a-z0-9]+ so they can never contain a quote."""
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
    locator_id: UUID
    chunk_index: int
    text: str
    layers: frozenset[str]
    rank: float


@dataclass(frozen=True)
class RetrievalResult:
    candidates: tuple[Candidate, ...]
    layer_contribution: dict[str, int] = field(default_factory=dict)
    matched_concept_ids: tuple[UUID, ...] = ()
    matched_toc_entry_ids: tuple[UUID, ...] = ()


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
        {"course_id": course_id, "match": _fts_match(tokens), "limit": limit},
    ).fetchall()
    return _rows_to_candidates(rows, KEYWORD)


def toc_seam(
    conn: Connection,
    course_id: UUID,
    query: str,
    limit: int,
) -> tuple[dict[UUID, Candidate], tuple[UUID, ...]]:
    """Static TOC matching: entries whose title/description full-text match
    the query tokens, chunks under those entries' locators. Returns the
    candidates AND the matched entry ids (the trace records them).
    Dormant without entries. Uses the same strict tokenizer as the keyword
    seam so query syntax never reaches MATCH."""
    tokens = _keyword_tokens(query)
    if not tokens:
        return {}, ()
    entry_ids: list[UUID] = []
    rows = conn.execute(
        get(_FILE, "toc_candidates"),
        {"course_id": course_id, "match": _fts_match(tokens), "limit": limit},
    ).fetchall()
    for row in rows:
        entry_id = row.get("entry_id")
        if entry_id is not None and entry_id not in entry_ids:
            entry_ids.append(entry_id)
    candidates = {}
    for row in rows:
        candidate = Candidate(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            locator_id=row["locator_id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            layers=frozenset({TOC}),
            rank=0.0,
        )
        candidates[row["chunk_id"]] = candidate
    return candidates, tuple(entry_ids)


def concept_matches(
    conn: Connection,
    course_id: UUID,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Concepts whose name or a synonym appears in the query as a whole
    word, case-insensitively (the dependency seam's matcher). No matches =
    seam stays dormant.

    Concept names are MODEL-EXTRACTED, so each is regex-escaped before
    matching: unescaped, 'f(x' would raise and take down retrieve(), and
    'a+b' would silently match 'aaab'. Names like 'O(n)' and 'f(x)' are the
    common case in maths and CS courses. Single-character names are
    rejected ('f' or 'R' would match nearly every question)."""
    if not query.strip():
        return []
    query_lower = query.lower()
    rows = conn.execute(
        get(_FILE, "course_concepts"), {"course_id": course_id}
    ).fetchall()
    matches: list[dict[str, Any]] = []
    for row in rows:
        names = [row["name"], *(row["synonyms"] or [])]
        if any(_whole_word_in(str(name), query_lower) for name in names):
            matches.append({"concept_id": row["concept_id"], "name": row["name"]})
            if len(matches) >= limit:
                break
    return matches


def _whole_word_in(name: str, query_lower: str) -> bool:
    needle = name.lower().strip()
    if len(needle) < 2:
        return False
    pattern = rf"(^|[^a-z0-9]){re.escape(needle)}([^a-z0-9]|$)"
    return re.search(pattern, query_lower) is not None


def dependency_seam(
    conn: Connection,
    course_id: UUID,
    matched_concept_ids: list[UUID],
    limit: int,
) -> dict[UUID, Candidate]:
    """1-hop dependency walk. Dormant (empty) without matched concepts or
    edges — the caller passes only concept ids it matched; edge trust is
    enforced upstream by the extractor's evidence bar."""
    if not matched_concept_ids:
        return {}
    rows = conn.execute(
        get(_FILE, "dependency_expansion"),
        {
            "course_id": course_id,
            "concept_ids": json_ids(matched_concept_ids),
            "limit": limit,
        },
    ).fetchall()
    return _rows_to_candidates(rows, DEPENDENCY)


def embedding_seam(
    conn: Connection,
    course_id: UUID,
    query_embedding: list[float] | None,
    model: str,
    limit: int,
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
        get(_FILE, "embedding_rows"), {"course_id": course_id, "model": model}
    ).fetchall()
    dimension = len(query_embedding)
    rows = [row for row in rows if row["dimension"] == dimension]
    if not rows:
        return {}
    matrix = np.frombuffer(
        b"".join(row["embedding"] for row in rows), dtype="<f4"
    ).reshape(len(rows), dimension)
    scores = matrix @ np.asarray(query_embedding, dtype=np.float32)
    top = np.argsort(-scores, kind="stable")[:limit]
    out: dict[UUID, Candidate] = {}
    for index in top:
        row = rows[int(index)]
        out[row["chunk_id"]] = Candidate(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            locator_id=row["locator_id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            layers=frozenset({EMBEDDING}),
            rank=float(scores[int(index)]),
        )
    return out


def _normalize(seam: dict[UUID, Candidate]) -> None:
    """Min-max a seam's ranks into 0.0..1.0 IN PLACE, seam-locally. This
    is what makes cross-seam comparison legal (the #4 lesson: ts_rank
    ~0.06 and dependency position 8 were incomparable units).

    Every seam's seam-local rank is already "higher is better": keyword
    is negated bm25, embedding is the dot product, and toc/dependency use
    arrival position as `-position` (best chunk at position 0). The
    normalization therefore keeps the direction for ALL seams. (An
    earlier version flipped keyword/dependency, which inverted their
    evidence: the best keyword chunk normalized to 0.0 and sank below the
    worst. Fixed 2026-09-22.)

    A seam of one candidate (or all-equal ranks) normalizes to a
    mid-strength 0.5 — it IS weak information, not zero."""
    if not seam:
        return
    ranks = [candidate.rank for candidate in seam.values()]
    low, high = min(ranks), max(ranks)
    if high <= low:
        for candidate in seam.values():
            _mutate_rank(candidate, 0.5)
        return
    span = high - low
    for candidate in seam.values():
        _mutate_rank(candidate, (candidate.rank - low) / span)


def _mutate_rank(candidate: Candidate, new_rank: float) -> None:
    object.__setattr__(candidate, "rank", new_rank)


def fuse(
    keyword: dict[UUID, Candidate],
    toc: dict[UUID, Candidate],
    dependency: dict[UUID, Candidate],
    embeddings: dict[UUID, Candidate],
    *,
    policy: RetrievalPolicy,
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
    _normalize(keyword)
    _normalize(toc)
    _normalize(dependency)
    _normalize(embeddings)

    merged: dict[UUID, Candidate] = {}
    for seam in (keyword, toc, dependency, embeddings):
        for chunk_id, candidate in seam.items():
            if chunk_id in merged:
                existing = merged[chunk_id]
                merged[chunk_id] = Candidate(
                    chunk_id=existing.chunk_id,
                    source_id=existing.source_id,
                    locator_id=existing.locator_id,
                    chunk_index=existing.chunk_index,
                    text=existing.text,
                    layers=existing.layers | candidate.layers,
                    rank=max(existing.rank, candidate.rank),
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
    grounded_present = bool(keyword or toc or dependency)
    if total_weight <= 0 or contributing == 0:
        # Degenerate (all-zero scores): equal split, availability-clamped.
        quotas = {sid: min(k // contributing, avail) if contributing else 0
                  for sid, avail in available_by_source.items()}
    else:
        raw = {
            sid: weight / total_weight * k
            for sid, weight in best_by_source.items()
        }
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
    # grounded (keyword/toc/dependency) hits. When no seam found anything
    # grounded, embeddings are not "expansion" — they are the only
    # evidence there is, so the quota does not apply.
    embedding_quota = (
        policy.embedding_only_quota if grounded_present else k
    )
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
            if (
                is_embedding_only
                and embedding_only_admitted >= embedding_quota
            ):
                continue
            if is_embedding_only:
                embedding_only_admitted += 1
            final.append(candidate)
    return tuple(final)


def retrieve(
    conn: Connection,
    course_id: UUID,
    query: str,
    policy: RetrievalPolicy,
    *,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
) -> RetrievalResult:
    """Run every seam, fuse, attribute layers. Trace persistence is the
    caller's job (the tutor flow owns the transaction)."""
    matched_concepts = concept_matches(conn, course_id, query, policy.dependency_limit)
    matched_ids = [row["concept_id"] for row in matched_concepts]
    keyword = keyword_seam(conn, course_id, query, policy.keyword_limit)
    toc, toc_entry_ids = toc_seam(conn, course_id, query, policy.toc_limit)
    dependency = dependency_seam(conn, course_id, matched_ids, policy.dependency_limit)
    embeddings = embedding_seam(
        conn,
        course_id,
        query_embedding,
        embedding_model or "",
        policy.embedding_limit,
    )
    final = fuse(
        keyword, toc, dependency, embeddings, policy=policy
    )
    contribution: dict[str, int] = {}
    for candidate in final:
        for layer in candidate.layers:
            contribution[layer] = contribution.get(layer, 0) + 1
    return RetrievalResult(
        candidates=final,
        layer_contribution=contribution,
        matched_concept_ids=tuple(matched_ids),
        matched_toc_entry_ids=tuple(toc_entry_ids),
    )