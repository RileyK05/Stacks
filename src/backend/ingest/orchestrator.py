"""Ingestion orchestrator.

Binds the pipeline executor, the run ledger, and the stage handlers into
`run_ingestion`: extract_text → ocr (scanned PDFs only) → build_locators →
build_chunks → embed_chunks run deterministically (embeddings run
in-process). update_toc and extract_knowledge are enrichment stages: they
run without the chat model where possible: the TOC comes from the
author's own headings/bookmarks (plan §10a), and knowledge extraction
records a skip until decomposed per-chunk extraction lands, instead of
spending model calls whose output nothing stores.

A full retry re-executes every stage from the top — the executor has no
resume logic — but each stage is delete-your-rows-first idempotent, so
re-execution is safe, just not free. The run ledger records every
attempt, so "re-ran and succeeded" and "ran once" are distinguishable by
attempt history.

Prompt text is inlined into model prompts with uploaded material fenced
inside the UNTRUSTED_COURSE_MATERIAL markers (`prompt_registry`), and the
prompts state that fenced block is data — input marking, the
prompt-injection go-live gate. The fence is a documented mitigation, not
a security boundary; uploaded text can still attempt persuasion.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import numpy as np
from src.backend.common import provider
from src.backend.common.db import Connection
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.prompt_registry import load_prompt
from src.backend.common.queries import get
from src.backend.common.schemas.base import IngestionStage, IngestionStatus
from src.backend.ingest import chunking, extract, runs, toc
from src.backend.ingest.config import load_ingestion_config
from src.backend.ingest.pipeline import (
    IngestionPipelineError,
    StageHandler,
    StageSkipped,
    execute_pipeline,
)

_FILE = "ingestion"

MODEL_TASKS: dict[IngestionStage, str] = {
    IngestionStage.UPDATE_TOC: "toc_update",
    IngestionStage.EXTRACT_KNOWLEDGE: "course_knowledge_extraction",
    IngestionStage.OCR: "ocr",
}

_OCR_PAGE_BOUNDARY = "\n\n---\n\n"


def _split_ocr_pages(text: str, page_count: int) -> list[str]:
    """Split the OCR model's output back into per-page texts so page
    locators align the way text-layer PDFs do (citations must land on the
    page they came from, golden rule 1). The prompt asks for the sentinel
    separator between pages; when the model does not comply we cannot
    invent page alignment, so the whole text becomes page 1's span and the
    remaining pages are empty — honest degradation, never a miscitation.
    """
    parts = text.split(_OCR_PAGE_BOUNDARY)
    if len(parts) == page_count:
        return parts
    if len(parts) == 1:
        return [text] + [""] * (page_count - 1)
    # Model emitted some but not all separators: keep what it gave, pad the
    # rest, so the count always matches the rendered pages.
    parts = parts[:page_count]
    return parts + [""] * (page_count - len(parts))


class UnknownSourceError(RuntimeError):
    def __init__(self, source_id: UUID) -> None:
        super().__init__(f"unknown source: {source_id}")


class SourceRow:
    """The source facts the handlers need, fetched once and passed through
    the constructor — no lazy DB reads, no private reach-ins."""

    def __init__(
        self,
        source_id: UUID,
        course_id: UUID,
        mime_type: str,
        stored_encoding: str | None,
    ) -> None:
        self.source_id = source_id
        self.course_id = course_id
        self.mime_type = mime_type
        self.stored_encoding = stored_encoding


def fetch_source_row(conn: Connection, source_id: UUID) -> SourceRow:
    row = conn.execute(get(_FILE, "source_row"), {"source_id": source_id}).fetchone()
    if row is None:
        raise UnknownSourceError(source_id)
    return SourceRow(
        source_id=row["source_id"],
        course_id=row["course_id"],
        mime_type=row["mime_type"],
        stored_encoding=row["stored_encoding"],
    )


class IngestionHandlers:
    """Stage handlers for one source. Extracted state flows
    handler-to-handler through instance attributes; every derived-writing
    stage clears its own rows first, so a from-the-top retry is safe."""

    def __init__(
        self,
        conn: Connection,
        source: SourceRow,
        *,
        chunk_max_tokens: int,
        ocr_max_pages: int,
        ocr_scale: float,
    ) -> None:
        self.conn = conn
        self.source = source
        self.chunk_max_tokens = chunk_max_tokens
        self.ocr_max_pages = ocr_max_pages
        self.ocr_scale = ocr_scale
        self.extracted: extract.ExtractedSource | None = None
        self.spans: tuple[chunking.ChunkSpan, ...] = ()
        self.needs_ocr = False

    def handlers(self) -> dict[IngestionStage, StageHandler]:
        return {
            IngestionStage.EXTRACT_TEXT: self.extract_text,
            IngestionStage.OCR: self.ocr,
            IngestionStage.BUILD_LOCATORS: self.build_locators,
            IngestionStage.BUILD_CHUNKS: self.build_chunks,
            IngestionStage.EMBED_CHUNKS: self.embed_chunks,
            IngestionStage.UPDATE_TOC: self.update_toc,
            IngestionStage.EXTRACT_KNOWLEDGE: self.extract_knowledge,
        }

    def extract_text(self) -> None:
        try:
            self.extracted = extract.extract(
                self.source.course_id,
                self.source.source_id,
                self.source.mime_type,
                stored_encoding=self.source.stored_encoding,
            )
        except extract.ScannedPdfNeedsOcrError:
            # No text layer: defer to the ocr stage rather than failing
            # extraction. The stage succeeds with a marker so the pipeline
            # reaches OCR; the loud failure lives at the ocr stage (where
            # an unavailable provider is an actionable error).
            self.needs_ocr = True
            self.extracted = None

    def ocr(self) -> None:
        """Recognize text for a source that had no text layer. A no-op for
        every source that already extracted (the common case); this stage
        exists so the scanned path is explicit, billed, and inspectable
        rather than hidden inside extract_text."""
        if not self.needs_ocr:
            return
        images = extract.rasterize_pages(
            self.source.course_id,
            self.source.source_id,
            self.source.stored_encoding,
            max_pages=self.ocr_max_pages,
            scale=self.ocr_scale,
        )
        if not images:
            raise provider.EmptyModelError("ocr: no pages rendered")
        result = provider.generate(
            MODEL_TASKS[IngestionStage.OCR],
            load_prompt("ocr"),
            course_id=self.source.course_id,
            images=images,
        )
        page_texts = _split_ocr_pages(result.text, len(images))
        if not any(page_text.strip() for page_text in page_texts):
            raise provider.EmptyModelError("ocr: model returned no text")
        self.extracted = extract.ocr_extracted_source(page_texts)

    def build_locators(self) -> None:
        assert self.extracted is not None
        source_param = {"source_id": self.source.source_id}
        self.conn.execute(get(_FILE, "delete_chunks"), source_param)
        self.conn.execute(get(_FILE, "delete_locators"), source_param)
        self.conn.executemany(
            get(_FILE, "insert_locator"),
            [
                {
                    "locator_id": span.locator_id,
                    "source_id": self.source.source_id,
                    "locator_type": span.locator_type,
                    "start": str(span.start),
                    "end_value": str(span.end),
                    "label": span.label,
                    "description": span.description,
                }
                for span in self.extracted.locators
            ],
        )

    def build_chunks(self) -> None:
        assert self.extracted is not None
        self.spans = chunking.chunk_text(
            self.extracted.text,
            self.extracted.locators,
            max_tokens=self.chunk_max_tokens,
        )
        self.conn.execute(
            get(_FILE, "delete_chunks"), {"source_id": self.source.source_id}
        )
        chunk_rows: list[dict[str, object]] = []
        link_rows: list[dict[str, object]] = []
        for span in self.spans:
            if not span.locator_ids:
                raise ValueError(
                    f"chunk {span.chunk_index} maps to no locator — "
                    "citation grounding is mandatory"
                )
            # One row per logical chunk (ratified fix #10): the primary
            # locator goes on the chunk row, every locator in the span
            # goes into chunk_locators (the citation map).
            chunk_id = uuid4()
            chunk_rows.append(
                {
                    "chunk_id": chunk_id,
                    "source_id": self.source.source_id,
                    "locator_id": span.locator_ids[0],
                    "chunk_index": span.chunk_index,
                    "text": span.text,
                }
            )
            link_rows.extend(
                {"chunk_id": chunk_id, "locator_id": locator_span_id}
                for locator_span_id in span.locator_ids
            )
        self.conn.executemany(get(_FILE, "insert_chunk"), chunk_rows)
        self.conn.executemany(get(_FILE, "insert_chunk_locator"), link_rows)

    def update_toc(self) -> None:
        """TOC entries from the author's own structure (ingest/toc.py) — no
        model call. Replaces this source's entries in the course TOC."""
        if self.extracted is None:
            raise StageSkipped("no extracted text")
        if self.source.mime_type == "application/pdf":
            pdf_bytes = extract.read_pdf_bytes(
                self.source.course_id,
                self.source.source_id,
                self.source.stored_encoding,
            )
            drafts = toc.pdf_entries(self.extracted, pdf_bytes)
        else:
            drafts = toc.markdown_entries(self.extracted)
        source_param = {"source_id": self.source.source_id}
        self.conn.execute(get(_FILE, "delete_source_toc_entries"), source_param)
        if not drafts:
            raise StageSkipped("no headings or bookmarks found in this source")
        row = self.conn.execute(
            get(_FILE, "course_toc"), {"course_id": self.source.course_id}
        ).fetchone()
        toc_id = row["toc_id"] if row else uuid4()
        if row is None:
            self.conn.execute(
                get(_FILE, "insert_toc"),
                {"toc_id": toc_id, "course_id": self.source.course_id},
            )
        self.conn.executemany(
            get(_FILE, "insert_toc_entry"),
            [
                {
                    "entry_id": uuid4(),
                    "toc_id": toc_id,
                    "source_id": self.source.source_id,
                    "locator_id": draft.locator_id,
                    "title": draft.title,
                    "description": draft.description,
                    "position": position,
                }
                for position, draft in enumerate(drafts)
            ],
        )

    def embed_chunks(self) -> None:
        """Embed every chunk of this source under the configured model's
        contract. In-process: records nothing and sends no text anywhere.
        The (slow) encoding runs before any write, so no transaction is
        held open while the model works."""
        assert self.spans
        policy = load_embedding_policy()
        vectors = provider.embed_chunks([span.text for span in self.spans])
        source_param = {"source_id": self.source.source_id}
        rows = self.conn.execute(
            get(_FILE, "chunk_ids_by_source_index"), source_param
        ).fetchall()
        by_index = {row["chunk_index"]: row["chunk_id"] for row in rows}
        embedding_rows: list[dict[str, object]] = []
        for span, vector in zip(self.spans, vectors, strict=True):
            chunk_id = by_index.get(span.chunk_index)
            if chunk_id is None:
                raise RuntimeError(
                    f"chunk {span.chunk_index} vanished between "
                    "build_chunks and embed_chunks"
                )
            embedding_rows.append(
                {
                    "chunk_id": chunk_id,
                    "model": policy.model,
                    "dimension": len(vector),
                    "embedding": np.asarray(vector, dtype="<f4").tobytes(),
                }
            )
        self.conn.execute(get(_FILE, "delete_chunk_embeddings"), source_param)
        self.conn.executemany(get(_FILE, "replace_chunk_embedding"), embedding_rows)

    def extract_knowledge(self) -> None:
        raise StageSkipped(
            "knowledge extraction lands with decomposed per-chunk extraction "
            "(plan §10a)"
        )


def run_ingestion(conn: Connection, source_id: UUID) -> UUID:
    """Execute the full pipeline for one source. Creates run + stage rows,
    executes stages with retries, marks run/source terminal, clears the
    queue row. Returns run_id."""
    source = fetch_source_row(conn, source_id)
    ingestion_config = load_ingestion_config()
    handler_set = IngestionHandlers(
        conn,
        source,
        chunk_max_tokens=ingestion_config.chunk_max_tokens,
        ocr_max_pages=ingestion_config.ocr.max_pages,
        ocr_scale=ingestion_config.ocr.scale,
    )
    stage_versions = [
        (stage_config.name, stage_config.handler_version)
        for stage_config in ingestion_config.stages
    ]
    run, _stage_rows = runs.create_run(
        conn,
        source_id,
        ingestion_config.pipeline_version,
        {
            "chunk_max_tokens": handler_set.chunk_max_tokens,
        },
        stage_versions,
        ingestion_config.max_attempts,
    )
    conn.commit()
    observer = runs.RunObserver(conn, run.run_id, source_id=source_id)
    try:
        execute_pipeline(
            handler_set.handlers(),
            max_attempts=ingestion_config.max_attempts,
            observe=observer.observe,
            conn=conn,
        )
        observer.finish(IngestionStatus.SUCCEEDED, None)
        runs.mark_source_indexed(conn, source_id)
        runs.record_history(
            conn,
            source_id,
            source.course_id,
            "ingested",
            runs.queued_at_for(conn, source_id),
        )
        runs.clear_pending_source(conn, source_id)
        conn.commit()
    except IngestionPipelineError as err:
        message = str(err)[:500]
        _commit_failure_audit(
            conn, run.run_id, source_id, source.course_id, message, failed_stage=err
        )
        raise
    return run.run_id


def _commit_failure_audit(
    conn: Connection,
    run_id: UUID,
    source_id: UUID,
    course_id: UUID,
    message: str,
    *,
    failed_stage: IngestionPipelineError | None = None,
) -> None:
    """Record run/source failure and commit it on its own: the pipeline
    exception aborted the caller's transaction, and the audit trail must
    survive the rollback of any partial derived rows. The history row is
    written BEFORE the queue row is deleted (queued_at captured first —
    the doc-code-drift lesson). Queue rows are cleared too — a failed
    source must not linger as a permanently unclaimable zombie (requeue
    is a deliberate operator/API action, see requeue_failed_source)."""
    conn.rollback()
    queued_at = runs.queued_at_for(conn, source_id)
    runs.mark_run_failed_direct(conn, run_id, message, failed_stage=failed_stage)
    runs.mark_source_failed(conn, source_id, message)
    if queued_at is not None:
        runs.record_history(
            conn, source_id, course_id, "failed", queued_at
        )
    runs.clear_pending_source(conn, source_id)
    conn.commit()