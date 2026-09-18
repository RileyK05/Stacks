"""The retrieval funnel (decision 008, revised): four seams, normalized
then allocated — not raw-scored.

Seams:
- keyword: tsvector match (works day one, zero model dependency)
- toc: static matching of the query against entry titles/descriptions,
  chunks under matched entries' locators (dormant without entries)
- dependency walk: matched concepts -> 1-hop prereq/dependent chunks
  (dormant without edges; only trusted edges passed in)
- embeddings: ranks the merged set by meaning when present (dormant
  without a provider); absent, a deterministic order applies

Fusion: each seam's ranks are min-max normalized INTO 0..1 (the unit
accident — ts_rank ~0.06 vs dependency position 8 — made cross-seam
comparison meaningless before this). A source's relevance is its best
chunk's normalized score from any seam; the final_k slots are split
across sources proportionally (largest remainder) with a one-slot floor
per contributing source, availability clamping, and backfill. Every
surviving chunk carries its locator id; the layer contribution is
returned for the trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from src.backend.common.queries import get
from src.backend.retrieval.config import RetrievalPolicy

_FILE = "retrieval"

KEYWORD = "keyword"
TOC = "toc"
DEPENDENCY = "dependency"
EMBEDDING = "embedding"

# Only these characters survive keyword tokenization. Everything else —
# including every to_tsquery operator ( ) < > ! & | : * — is stripped
# BEFORE the string is split, so a math query like "f(x) = x^2" can never
# smuggle operator syntax into the tsquery. Tokens must contain at least
# one letter or digit.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _keyword_tokens(query: str) -> list[str]:
    lowered = query.lower()
    tokens = _TOKEN_RE.findall(lowered)
    return [token for token in tokens if len(token) >= 2]


@dataclass(frozen=True)
class Candidate:
    """One chunk candidate with every layer that surfaced it.

    `rank` is seam-local on ARRIVAL (ts_rank, dot product, or arrival
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
    """tsvector match with OR semantics (any term overlap counts; AND
    semantics would miss chunks holding only part of the question).
    Tokens are extracted with a strict [a-z0-9]+ regex before any SQL, so
    to_tsquery operator characters can never reach the parser — math
    questions ("f(x) = x^2") must not crash retrieval. Single characters
    are dropped (they match everything). Empty token sets match nothing."""
    tokens = _keyword_tokens(query)
    if not tokens:
        return {}
    or_query = " | ".join(tokens)
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "keyword_candidates"),
            {"course_id": course_id, "or_query": or_query, "limit": limit},
        ).fetchall()
    return _rows_to_candidates(list(rows), KEYWORD)


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
    seam so operator characters never reach to_tsquery."""
    tokens = _keyword_tokens(query)
    if not tokens:
        return {}, ()
    or_query = " | ".join(tokens)
    entry_ids: list[UUID] = []
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "toc_candidates"),
            {"course_id": course_id, "or_query": or_query, "limit": limit},
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
    """Concepts whose name/synonyms appear in the query (the dependency
    seam's matcher). No rows = seam stays dormant."""
    if not query.strip():
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "concept_synonym_matches"),
            {"course_id": course_id, "query_lower": query.lower(), "limit": limit},
        ).fetchall()
    return list(rows)


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
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "dependency_expansion"),
            {
                "course_id": course_id,
                "concept_ids": [str(cid) for cid in matched_concept_ids],
                "limit": limit,
            },
        ).fetchall()
    return _rows_to_candidates(list(rows), DEPENDENCY)


def embedding_seam(
    conn: Connection,
    course_id: UUID,
    query_embedding: list[float] | None,
    model: str,
    limit: int,
) -> dict[UUID, Candidate]:
    """Vector ranking. Dormant (empty) until embeddings exist; the caller
    passes None when there is no query embedding. The seam's `dot` column
    is the similarity rank (higher = closer)."""
    if not query_embedding:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            get(_FILE, "embedding_candidates"),
            {
                "course_id": course_id,
                "query_embedding": query_embedding,
                "model": model,
                "limit": limit,
            },
        ).fetchall()
    out: dict[UUID, Candidate] = {}
    for row in rows:
        out[row["chunk_id"]] = Candidate(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            locator_id=row["locator_id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            layers=frozenset({EMBEDDING}),
            rank=float(row["dot"]),
        )
    return out


def _normalize(seam: dict[UUID, Candidate], layer: str) -> None:
    """Min-max a seam's ranks into 0.0..1.0 IN PLACE, seam-locally. This
    is what makes cross-seam comparison legal (the #4 lesson: ts_rank
    ~0.06 and dependency position 8 were incomparable units). Embedding
    dots need no shift (already "higher is closer to the query"); for the
    rest higher rank meant earlier arrival, so the sign flips here. A
    seam of one candidate (or all-equal ranks) normalizes to a
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
    if layer == EMBEDDING:
        for candidate in seam.values():
            _mutate_rank(candidate, (candidate.rank - low) / span)
    else:
        for candidate in seam.values():
            _mutate_rank(candidate, (high - candidate.rank) / span)


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
    _normalize(keyword, KEYWORD)
    _normalize(toc, TOC)
    _normalize(dependency, DEPENDENCY)
    _normalize(embeddings, EMBEDDING)

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