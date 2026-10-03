"""Prepare outside a transaction, then publish one complete source index."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4, uuid5

import numpy as np
from src.backend.common import provider
from src.backend.common.db import Connection
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.queries import get
from src.backend.ingest.extract import ExtractedSource, ExtractionReport
from src.backend.rag.config import PassagePolicy
from src.backend.rag.segment import ContainerSpan, Segmentation, segment, windows

# Bump when extracted text or page coverage changes, so an older index can
# be marked stale. structured-v2 records per-page quality and spacing.
EXTRACTION_VERSION = "structured-v2"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreparedIndex:
    source_id: UUID
    course_id: UUID
    file_hash: str
    previous_revision: str | None
    revision: str
    policy: PassagePolicy
    segmentation: Segmentation
    containers: tuple[dict[str, Any], ...]
    locators: tuple[dict[str, Any], ...]
    passages: tuple[dict[str, Any], ...]
    links: tuple[dict[str, Any], ...]
    search_windows: tuple[dict[str, Any], ...]
    embeddings: tuple[dict[str, Any], ...]
    report: ExtractionReport | None = None


def prepare(
    conn: Connection,
    source_id: UUID,
    extracted: ExtractedSource,
    policy: PassagePolicy,
    *,
    structure: tuple[ContainerSpan, ...] | None = None,
) -> PreparedIndex:
    fence = conn.execute(
        get("passages", "source_fence"), {"source_id": source_id}
    ).fetchone()
    if fence is None or fence["deleted_at"] is not None:
        raise ValueError("source is no longer available")
    if not extracted.text.strip():
        raise ValueError("source contains no searchable text")
    if conn.in_transaction:
        raise RuntimeError("index preparation cannot hold a write transaction")
    text = extracted.text
    text_hash = digest(text)
    revision = str(uuid4())
    count = provider.embedding_token_count
    segmentation = segment(
        text,
        policy,
        encode=provider.embed_chunks,
        token_count=count,
        structure=structure,
        page_breaks=tuple(
            loc.start
            for loc in extracted.locators
            if loc.locator_type in {"page", "slide", "sheet"}
        ),
    )
    root_id = uuid5(source_id, f"{text_hash}:document")
    container_ids = [
        uuid5(source_id, f"{text_hash}:container:{c.start}:{c.level}")
        for c in segmentation.containers
    ]
    container_rows = [
        {
            "container_id": root_id,
            "source_id": source_id,
            "revision": revision,
            "parent_id": None,
            "title": "Document",
            "level": 0,
            "origin": "source",
            "char_start": 0,
            "char_end": len(text),
        }
    ]
    for i, container in enumerate(segmentation.containers):
        container_rows.append(
            {
                "container_id": container_ids[i],
                "source_id": source_id,
                "revision": revision,
                "parent_id": container_ids[container.parent_index]
                if container.parent_index is not None
                else root_id,
                "title": container.title,
                "level": container.level,
                "origin": container.origin,
                "char_start": container.start,
                "char_end": container.end,
            }
        )
    locator_rows = [
        {
            "locator_id": span.locator_id,
            "source_id": source_id,
            "locator_type": span.locator_type,
            "start": str(span.start),
            "end_value": str(span.end),
            "label": span.label,
            "description": span.description,
        }
        for span in extracted.locators
    ]
    # Reuse an existing identity when the exact source span is unchanged.
    previous = conn.execute(
        get("passages", "previous_passages"), {"source_id": source_id}
    ).fetchall()
    existing: dict[tuple[int, int, str], UUID] = {}
    cursor = 0
    for row in previous:
        start = row["char_start"]
        if start is None:
            start = text.find(row["text"], cursor)
        if start >= 0:
            end = start + len(row["text"])
            existing[(start, end, row["text"])] = row["chunk_id"]
            cursor = end
    passage_rows: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    search_rows: list[dict[str, Any]] = []
    window_texts: list[str] = []
    for index, span in enumerate(segmentation.passages):
        passage_text = text[span.start : span.end]
        chunk_id = existing.get((span.start, span.end, passage_text)) or uuid5(
            source_id, f"{text_hash}:passage:{span.start}:{span.end}"
        )
        locations = [
            loc.locator_id
            for loc in extracted.locators
            if loc.start < span.end and loc.end > span.start
        ]
        if not locations and not passage_text.strip() and extracted.locators:
            previous_location = next(
                (loc for loc in reversed(extracted.locators) if loc.end <= span.start),
                extracted.locators[0],
            )
            locations = [previous_location.locator_id]
        if not locations:
            raise ValueError(f"passage {index} has no source location")
        passage_rows.append(
            {
                "chunk_id": chunk_id,
                "source_id": source_id,
                "locator_id": locations[0],
                "chunk_index": index,
                "text": passage_text,
                "revision": revision,
                "container_id": container_ids[span.container_index]
                if span.container_index is not None
                else root_id,
                "char_start": span.start,
                "char_end": span.end,
                "unit_kind": span.kind,
                "boundary": span.boundary,
            }
        )
        links.extend(
            {"chunk_id": chunk_id, "locator_id": location} for location in locations
        )
        for start, end in windows(
            passage_text,
            policy.search_window_tokens,
            policy.window_overlap_tokens,
            token_count=count,
        ):
            value = passage_text[start:end]
            window_texts.append(value)
            search_rows.append(
                {
                    "window_id": uuid5(chunk_id, f"window:{start}:{end}"),
                    "chunk_id": chunk_id,
                    "char_start": start,
                    "char_end": end,
                    "text_hash": digest(value),
                }
            )
    embedding_policy = load_embedding_policy()
    vectors = np.asarray(provider.embed_chunks(window_texts), dtype=np.float32)
    expected = (len(window_texts), embedding_policy.dimension)
    if vectors.shape != expected or not np.isfinite(vectors).all():
        raise ValueError("invalid search-window embeddings")
    norms = np.linalg.norm(vectors, axis=1)
    if (norms <= 0).any():
        raise ValueError("empty search-window embeddings")
    vectors /= norms[:, None]
    grouped: dict[UUID, list[np.ndarray]] = {}
    for row, vector in zip(search_rows, vectors, strict=True):
        row.update(
            model=embedding_policy.model,
            dimension=embedding_policy.dimension,
            embedding=vector.astype("<f4").tobytes(),
        )
        grouped.setdefault(row["chunk_id"], []).append(vector)
    embeddings = []
    for chunk_id, values in grouped.items():
        representative = np.mean(values, axis=0)
        norm = float(np.linalg.norm(representative))
        if norm <= 0:
            representative = values[0]
        else:
            representative /= norm
        embeddings.append(
            {
                "chunk_id": chunk_id,
                "model": embedding_policy.model,
                "dimension": embedding_policy.dimension,
                "embedding": representative.astype("<f4").tobytes(),
            }
        )
    return PreparedIndex(
        source_id,
        fence["course_id"],
        fence["file_hash"],
        fence["revision"],
        revision,
        policy,
        segmentation,
        tuple(container_rows),
        tuple(locator_rows),
        tuple(passage_rows),
        tuple(links),
        tuple(search_rows),
        tuple(embeddings),
        report=extracted.report,
    )


def publish(conn: Connection, prepared: PreparedIndex) -> None:
    """The caller commits only after every derived row has been installed."""
    if conn.in_transaction:
        raise RuntimeError("index publication requires a fresh transaction")
    conn.execute("BEGIN IMMEDIATE")
    params = {"source_id": prepared.source_id, "course_id": prepared.course_id}
    fence = conn.execute(get("passages", "source_fence"), params).fetchone()
    if (
        fence is None
        or fence["deleted_at"] is not None
        or fence["file_hash"] != prepared.file_hash
        or fence["revision"] != prepared.previous_revision
    ):
        raise ValueError("source changed while its index was being prepared")
    conn.execute(get("sources", "snapshot_citations_before_reindex"), params)
    conn.execute(get("ingestion", "delete_chunks"), params)
    conn.execute(get("passages", "delete_containers"), params)
    conn.execute(get("ingestion", "delete_locators"), params)
    conn.executemany(get("passages", "insert_container"), prepared.containers)
    conn.executemany(get("ingestion", "insert_locator"), prepared.locators)
    conn.executemany(get("passages", "insert_passage"), prepared.passages)
    conn.executemany(get("ingestion", "insert_chunk_locator"), prepared.links)
    conn.executemany(get("passages", "insert_window"), prepared.search_windows)
    conn.executemany(get("ingestion", "replace_chunk_embedding"), prepared.embeddings)
    report = prepared.report
    conn.execute(
        get("passages", "publish_index"),
        {
            **params,
            "revision": prepared.revision,
            "file_hash": prepared.file_hash,
            "extraction_version": EXTRACTION_VERSION,
            "segmentation_version": prepared.policy.version,
            "semantic_used": int(prepared.segmentation.semantic_used),
            "warning": prepared.segmentation.warning,
            "pages_total": None if report is None else report.pages_total,
            "pages_empty": None if report is None else report.pages_empty,
            "pages_low_quality": None if report is None else report.pages_low_quality,
            "pages_ocr": None if report is None else report.pages_ocr,
        },
    )
