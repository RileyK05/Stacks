"""The retrieval funnel (decision 008): four seams, mixed not scored.

Seams:
- keyword: tsvector match (works day one, zero model dependency)
- toc: static matching of the query against entry titles/descriptions,
  chunks under matched entries' locators (dormant without entries)
- dependency walk: matched concepts -> 1-hop prereq/dependent chunks
  (dormant without edges; only trusted edges passed in)
- embeddings: ranks the merged set by meaning when present (dormant
  without a provider); absent, a deterministic order applies

Fusion mixes: union with layer attribution, per-source caps, final_k cut.
Every surviving chunk carries its locator id; the layer contribution is
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

    `rank` is seam-local and unit-free by design (ts_rank, dot product,
    or arrival position); it is only ever compared against ranks from the
    SAME seam, never across seams — sort_key routes embedding ranks and
    non-embedding ranks through separate sort buckets so the units never
    mix. Do not use `rank` for cross-seam scoring; the funnel mixes, it
    does not score."""

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


def fuse(
    keyword: dict[UUID, Candidate],
    toc: dict[UUID, Candidate],
    dependency: dict[UUID, Candidate],
    embeddings: dict[UUID, Candidate],
    *,
    policy: RetrievalPolicy,
) -> tuple[Candidate, ...]:
    """Mix, not score. Order: embedding rank when available (the
    relevance ordering), else seam-arrival rank. Ranks are never compared
    across seams (see Candidate) — max() below only merges the SAME
    chunk's ranks so a multi-layer chunk keeps its best same-unit
    representative; sort_key buckets embedding vs non-embedding first.
    Per-source caps apply to the final cut; embedding-only candidates
    (surfaced by no other layer) are admitted up to their quota."""
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

    def sort_key(candidate: Candidate) -> tuple[int, float, int]:
        if candidate.chunk_id in embeddings:
            return (0, -embeddings[candidate.chunk_id].rank, candidate.chunk_index)
        return (1, -candidate.rank, candidate.chunk_index)

    ordered = sorted(merged.values(), key=sort_key)

    counts: dict[UUID, int] = {}
    embedding_only_admitted = 0
    final: list[Candidate] = []
    for candidate in ordered:
        is_embedding_only = candidate.layers == frozenset({EMBEDDING})
        if is_embedding_only and embedding_only_admitted >= policy.embedding_only_quota:
            continue
        if counts.get(candidate.source_id, 0) >= policy.per_source_cap:
            continue
        counts[candidate.source_id] = counts.get(candidate.source_id, 0) + 1
        if is_embedding_only:
            embedding_only_admitted += 1
        final.append(candidate)
        if len(final) >= policy.final_k:
            break
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