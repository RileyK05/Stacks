from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from uuid import UUID

from src.backend.common import generation, provider
from src.backend.common.db import Connection
from src.backend.common.prompt_registry import load_prompt
from src.backend.common.queries import get
from src.backend.common.schemas.base import IngestionStage, IngestionStatus
from src.backend.common.usage_repo import BudgetExceededError
from src.backend.ingest import extract, runs, structure
from src.backend.ingest.config import load_ingestion_config
from src.backend.ingest.ocr_pages import split_ocr_pages
from src.backend.ingest.pipeline import (
    IngestionPipelineError,
    StageHandler,
    StageWarning,
    execute_pipeline,
    is_transient_error,
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
        ocr_batch_pages: int = 4,
        ocr_max_image_pixels: int = 8_000_000,
        ocr_max_request_image_bytes: int = 12_000_000,
        ocr_max_attempts: int = 2,
        retry_backoff_seconds: float = 0.5,
        retry_backoff_multiplier: float = 2.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.conn = conn
        self.source = source
        self.ocr_max_pages = ocr_max_pages
        self.ocr_scale = ocr_scale
        self.ocr_batch_pages = ocr_batch_pages
        self.ocr_max_image_pixels = ocr_max_image_pixels
        self.ocr_max_request_image_bytes = ocr_max_request_image_bytes
        self.ocr_max_attempts = ocr_max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.retry_backoff_multiplier = retry_backoff_multiplier
        self.sleeper = sleeper
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
            return
        report = self.extracted.report
        self.needs_ocr = report is not None and bool(report.ocr_pages)

    def ocr(self) -> None:
        """Recognize text for a source that had no text layer, or for the
        blank and garbled pages of a mixed PDF. A no-op when extraction
        already covered every page."""
        if not self.needs_ocr:
            return
        if self.extracted is not None:
            self._ocr_weak_pages()
            return
        page_count = extract.pdf_page_count(
            self.source.course_id,
            self.source.source_id,
            self.source.stored_encoding,
        )
        if page_count == 0:
            raise ValueError("this PDF has no readable pages")
        page_indexes = list(range(min(page_count, self.ocr_max_pages)))
        recognized: dict[int, str] = {}
        failures: list[str] = []
        for batch_start in range(0, len(page_indexes), self.ocr_batch_pages):
            batch = page_indexes[batch_start : batch_start + self.ocr_batch_pages]
            rendered = self._render_batch(batch, failures)
            self._recognize_batch(rendered, recognized, failures)
        texts = [recognized.get(index, "") for index in range(page_count)]
        if not any(page.strip() for page in texts):
            detail = "; ".join(failures) if failures else "model returned no text"
            raise provider.EmptyModelError(f"ocr: no usable text recognized ({detail})")
        self.extracted = extract.ocr_extracted_source(texts)
        assert self.extracted.report is not None
        self.extracted = replace(
            self.extracted,
            report=replace(self.extracted.report, pages_total=page_count),
        )
        unresolved = [index for index, text in enumerate(texts) if not text.strip()]
        self._warn_if_incomplete(
            unresolved, failures, cap_exceeded=page_count > self.ocr_max_pages
        )

    def _ocr_weak_pages(self) -> None:
        """OCR only the pages extraction flagged, and keep the text layer
        when the vision model is unavailable. A mixed PDF must still index."""
        assert self.extracted is not None and self.extracted.report is not None
        requested_indexes = self.extracted.report.ocr_pages
        indexes = list(requested_indexes[: self.ocr_max_pages])
        if not indexes:
            return
        recognized: dict[int, str] = {}
        failures: list[str] = []
        for batch_start in range(0, len(indexes), self.ocr_batch_pages):
            batch = indexes[batch_start : batch_start + self.ocr_batch_pages]
            rendered = self._render_batch(batch, failures)
            self._recognize_batch(rendered, recognized, failures)
        rendered_indexes = list(recognized)
        if rendered_indexes:
            self.extracted = extract.apply_page_ocr(
                self.extracted,
                rendered_indexes,
                [recognized[index] for index in rendered_indexes],
            )
        self.needs_ocr = False
        assert self.extracted.report is not None
        self._warn_if_incomplete(
            list(self.extracted.report.ocr_pages),
            failures,
            cap_exceeded=len(requested_indexes) > self.ocr_max_pages,
        )

    def _render_batch(
        self, indexes: list[int], failures: list[str]
    ) -> list[extract.RasterizedPage]:
        try:
            rendered = extract.rasterize_pages_with_ids(
                self.source.course_id,
                self.source.source_id,
                self.source.stored_encoding,
                max_pages=self.ocr_batch_pages,
                scale=self.ocr_scale,
                max_pixels=self.ocr_max_image_pixels,
                pages=indexes,
            )
        except (OSError, RuntimeError, ValueError) as err:
            failures.append(
                f"pages {self._page_labels(indexes)} could not be rendered: {err}"
            )
            return []
        rendered_ids = {page.page_index for page in rendered}
        missing = [index for index in indexes if index not in rendered_ids]
        if missing:
            failures.append(f"pages {self._page_labels(missing)} could not be rendered")
        return rendered

    def _recognize_batch(
        self,
        rendered: list[extract.RasterizedPage],
        recognized: dict[int, str],
        failures: list[str],
    ) -> None:
        batch: list[extract.RasterizedPage] = []
        byte_count = 0
        for page in rendered:
            encoded_size = 4 * ((len(page.image) + 2) // 3) + 128
            if encoded_size > self.ocr_max_request_image_bytes:
                failures.append(
                    f"page {page.page_index + 1} exceeds the OCR image byte limit"
                )
                continue
            if batch and byte_count + encoded_size > self.ocr_max_request_image_bytes:
                self._recognize_bounded_batch(batch, recognized, failures)
                batch, byte_count = [], 0
            batch.append(page)
            byte_count += encoded_size
        self._recognize_bounded_batch(batch, recognized, failures)

    @generation.operation()
    def _recognize_bounded_batch(
        self,
        rendered: list[extract.RasterizedPage],
        recognized: dict[int, str],
        failures: list[str],
    ) -> None:
        if not rendered:
            return
        indexes = [page.page_index for page in rendered]
        for attempt in range(1, self.ocr_max_attempts + 1):
            try:
                result = provider.generate(
                    MODEL_TASKS[IngestionStage.OCR],
                    load_prompt("ocr"),
                    course_id=self.source.course_id,
                    images=[page.image for page in rendered],
                )
            except (provider.ProviderUnavailableError, BudgetExceededError) as err:
                # A moderation refusal is a coin flip, and the same batch often
                # succeeds on resend (R4-NEW-l): a dropped page is permanent.
                retryable = is_transient_error(err) or isinstance(
                    err, provider.ModelRefusalError
                )
                if attempt < self.ocr_max_attempts and retryable:
                    delay = (
                        self.retry_backoff_seconds
                        * self.retry_backoff_multiplier ** (attempt - 1)
                    )
                    if delay > 0:
                        self.sleeper(delay)
                    continue
                if len(rendered) > 1 and isinstance(err, provider.ModelRefusalError):
                    for page in rendered:
                        self._recognize_single_page(page, recognized, failures)
                    return
                logger.warning(
                    "OCR failed for source %s after %d attempt(s): %s",
                    self.source.source_id,
                    attempt,
                    err,
                )
                if isinstance(err, provider.ModelRefusalError):
                    failures.append(
                        f"pages {self._page_labels(indexes)} were declined by "
                        "the reading model"
                    )
                else:
                    failures.append(
                        f"pages {self._page_labels(indexes)} could not be read "
                        f"after {attempt} attempt(s): {err}"
                    )
                return
            break
        try:
            page_texts = split_ocr_pages(result.text, len(rendered))
        except ValueError as err:
            if len(rendered) > 1:
                for page in rendered:
                    self._recognize_single_page(page, recognized, failures)
                return
            logger.warning(
                "OCR page split failed for source %s: %s", self.source.source_id, err
            )
            failures.append(
                f"pages {self._page_labels(indexes)} came back without readable "
                "page breaks"
            )
            return
        recognized.update(zip(indexes, page_texts, strict=True))

    @generation.operation(fresh=True)
    def _recognize_single_page(
        self,
        page: extract.RasterizedPage,
        recognized: dict[int, str],
        failures: list[str],
    ) -> None:
        """Retried alone on its own budget: the batch's spent attempts must
        not leave the page unrecoverable (R4-NEW-e)."""
        self._recognize_bounded_batch([page], recognized, failures)

    def _warn_if_incomplete(
        self, unresolved: list[int], failures: list[str], *, cap_exceeded: bool
    ) -> None:
        if not unresolved and not failures and not cap_exceeded:
            return
        texts = self.extracted.page_texts if self.extracted is not None else []
        blank: list[int] = []
        thin: list[int] = []
        for index in sorted(unresolved):
            if index < len(texts) and texts[index].strip():
                thin.append(index)
            else:
                blank.append(index)
        details = []
        if blank:
            details.append(f"unresolved pages {self._page_labels(blank)}")
        if thin:
            details.append(
                f"pages {self._page_labels(thin)} have only a little text to index"
            )
        if cap_exceeded:
            details.append(f"only the first {self.ocr_max_pages} pages were read")
        details.extend(failures)
        message = "; ".join(
            detail[:-1] if detail.endswith(".") else detail for detail in details
        )
        logger.warning(
            "OCR incomplete for source %s: %s", self.source.source_id, message
        )
        raise StageWarning(message)

    @staticmethod
    def _page_labels(indexes: list[int]) -> str:
        labels = [str(index + 1) for index in indexes[:20]]
        if len(indexes) > 20:
            labels.append(f"... (+{len(indexes) - 20} more)")
        return ", ".join(labels)

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
        ocr_batch_pages=ingestion_config.ocr.batch_pages,
        ocr_max_image_pixels=ingestion_config.ocr.max_image_pixels,
        ocr_max_request_image_bytes=ingestion_config.ocr.max_request_image_bytes,
        ocr_max_attempts=ingestion_config.max_attempts,
        retry_backoff_seconds=ingestion_config.retry_backoff_seconds,
        retry_backoff_multiplier=ingestion_config.retry_backoff_multiplier,
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
            retry_backoff_seconds=ingestion_config.retry_backoff_seconds,
            retry_backoff_multiplier=ingestion_config.retry_backoff_multiplier,
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
    except Exception as err:
        _commit_failure_audit(
            conn, run.run_id, source_id, source.course_id, str(err)[:500]
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
