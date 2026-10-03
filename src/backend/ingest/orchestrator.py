from __future__ import annotations

import logging
from uuid import UUID

from src.backend.common import provider
from src.backend.common.db import Connection
from src.backend.common.prompt_registry import load_prompt
from src.backend.common.queries import get
from src.backend.common.schemas.base import IngestionStage, IngestionStatus
from src.backend.ingest import extract, runs, structure
from src.backend.ingest.config import load_ingestion_config
from src.backend.ingest.ocr_pages import split_ocr_pages
from src.backend.ingest.pipeline import (
    IngestionPipelineError,
    StageHandler,
    execute_pipeline,
)
from src.backend.rag import store
from src.backend.rag.config import load_policy

_FILE = "ingestion"

logger = logging.getLogger(__name__)

MODEL_TASKS = {IngestionStage.OCR: "ocr"}


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
    """Preparation has no writes; publication replaces a complete index atomically."""

    def __init__(
        self,
        conn: Connection,
        source: SourceRow,
        *,
        ocr_max_pages: int,
        ocr_scale: float,
    ) -> None:
        self.conn = conn
        self.source = source
        self.ocr_max_pages = ocr_max_pages
        self.ocr_scale = ocr_scale
        self.extracted: extract.ExtractedSource | None = None
        self.prepared: store.PreparedIndex | None = None
        self.needs_ocr = False

    def handlers(self) -> dict[IngestionStage, StageHandler]:
        return {
            IngestionStage.EXTRACT_TEXT: self.extract_text,
            IngestionStage.OCR: self.ocr,
            IngestionStage.PREPARE_PASSAGES: self.prepare_passages,
            IngestionStage.PUBLISH_INDEX: self.publish_index,
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
        page_texts = split_ocr_pages(result.text, len(images))
        if not any(page_text.strip() for page_text in page_texts):
            raise provider.EmptyModelError("ocr: model returned no text")
        self.extracted = extract.ocr_extracted_source(page_texts)

    def prepare_passages(self) -> None:
        assert self.extracted is not None
        parents = structure.office_containers(self.extracted)
        if self.source.mime_type == "application/pdf":
            parents = structure.pdf_containers(
                self.extracted,
                extract.read_pdf_bytes(
                    self.source.course_id,
                    self.source.source_id,
                    self.source.stored_encoding,
                ),
            )
        self.prepared = store.prepare(
            self.conn,
            self.source.source_id,
            self.extracted,
            load_policy(),
            structure=parents,
        )

    def publish_index(self) -> None:
        assert self.prepared is not None
        store.publish(self.conn, self.prepared)


def run_ingestion(conn: Connection, source_id: UUID) -> UUID:
    """Execute the full pipeline for one source. Creates run + stage rows,
    executes stages with retries, marks run/source terminal, clears the
    queue row. Returns run_id."""
    source = fetch_source_row(conn, source_id)
    ingestion_config = load_ingestion_config()
    handler_set = IngestionHandlers(
        conn,
        source,
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
            "passage_policy": load_policy().model_dump(),
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
        _refresh_graph(source.source_id)
    except IngestionPipelineError as err:
        message = _failure_message(err)
        _commit_failure_audit(
            conn, run.run_id, source_id, source.course_id, message, failed_stage=err
        )
        raise
    return run.run_id


def _refresh_graph(source_id: UUID) -> None:
    """Best-effort similarity refresh over published passage vectors."""
    try:
        from src.backend.graph import build_source_edges

        build_source_edges(source_id)
    except Exception:  # noqa: BLE001 - derived enrichment, never fatal
        logger.exception("course graph refresh failed for source %s", source_id)


def _failure_message(err: IngestionPipelineError) -> str:
    """What the file browser shows under a failed source. The pipeline's
    own summary ("stage X failed after 2 attempts") says nothing the user
    can act on; the underlying cause (an unreadable PDF, an unavailable
    model) does, so it rides along."""
    cause = str(err.__cause__).strip() if err.__cause__ is not None else ""
    return (f"{err}: {cause}" if cause else str(err))[:500]


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
        runs.record_history(conn, source_id, course_id, "failed", queued_at)
    runs.clear_pending_source(conn, source_id)
    conn.commit()
