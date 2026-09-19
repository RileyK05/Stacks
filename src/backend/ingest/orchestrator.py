"""Milestone-1 ingestion orchestrator.

Binds the pipeline executor, the run ledger, and the stage handlers into
`run_ingestion`: extract_text → build_locators → build_chunks run
deterministically; update_toc and extract_knowledge call the provider
seam (gated + billed there). A full retry re-executes every stage from
the top — the executor has no resume logic — but each stage is
delete-your-rows-first idempotent, so re-execution is safe, just not
free. The run ledger records every attempt, so "re-ran and succeeded"
and "ran once" are distinguishable by attempt history.

Prompt text is inlined into model prompts without escaping (provider
stub); a hostile upload is a prompt-injection vector into shared course
state. Acceptable for dev; the provider seam must add input marking
before real user data flows (golden rule 4 go-live gate).
"""

from __future__ import annotations

from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from src.backend.common import provider
from src.backend.common.queries import get
from src.backend.common.schemas.base import (
    IngestionStage,
    IngestionStatus,
    UserTier,
)
from src.backend.ingest import chunking, extract, runs
from src.backend.ingest.config import load_ingestion_config
from src.backend.ingest.pipeline import (
    IngestionPipelineError,
    StageHandler,
    execute_pipeline,
)

_FILE = "ingestion"

MODEL_TASKS: dict[IngestionStage, str] = {
    IngestionStage.UPDATE_TOC: "toc_update",
    IngestionStage.EXTRACT_KNOWLEDGE: "course_knowledge_extraction",
}


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
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            get(_FILE, "source_row"), {"source_id": source_id}
        ).fetchone()
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
        owner_user_id: UUID,
        tier: UserTier,
        *,
        chunk_max_tokens: int,
        prompt_window_chars: int,
    ) -> None:
        self.conn = conn
        self.source = source
        self.owner_user_id = owner_user_id
        self.tier = tier
        self.chunk_max_tokens = chunk_max_tokens
        self.prompt_window_chars = prompt_window_chars
        self.extracted: extract.ExtractedSource | None = None
        self.spans: tuple[chunking.ChunkSpan, ...] = ()

    def handlers(self) -> dict[IngestionStage, StageHandler]:
        return {
            IngestionStage.EXTRACT_TEXT: self.extract_text,
            IngestionStage.BUILD_LOCATORS: self.build_locators,
            IngestionStage.BUILD_CHUNKS: self.build_chunks,
            IngestionStage.UPDATE_TOC: self.update_toc,
            IngestionStage.EXTRACT_KNOWLEDGE: self.extract_knowledge,
        }

    def extract_text(self) -> None:
        self.extracted = extract.extract(
            self.source.course_id,
            self.source.source_id,
            self.source.mime_type,
            stored_encoding=self.source.stored_encoding,
        )

    def build_locators(self) -> None:
        assert self.extracted is not None
        with self.conn.cursor() as cur:
            cur.execute(
                get(_FILE, "delete_chunks"),
                {"source_id": self.source.source_id},
            )
            cur.execute(
                get(_FILE, "delete_locators"),
                {"source_id": self.source.source_id},
            )
            for span in self.extracted.locators:
                cur.execute(
                    get(_FILE, "insert_locator"),
                    {
                        "locator_id": span.locator_id,
                        "source_id": self.source.source_id,
                        "locator_type": span.locator_type,
                        "start": str(span.start),
                        "end_value": str(span.end),
                        "label": span.label,
                        "description": span.description,
                    },
                )

    def build_chunks(self) -> None:
        assert self.extracted is not None
        self.spans = chunking.chunk_text(
            self.extracted.text,
            self.extracted.locators,
            max_tokens=self.chunk_max_tokens,
        )
        with self.conn.cursor() as cur:
            cur.execute(
                get(_FILE, "delete_chunks"),
                {"source_id": self.source.source_id},
            )
            for span in self.spans:
                if not span.locator_ids:
                    raise ValueError(
                        f"chunk {span.chunk_index} maps to no locator — "
                        "citation grounding is mandatory"
                    )
                # One row per logical chunk (ratified fix #10): the
                # primary locator goes on the chunk row, every locator in
                # the span goes into chunk_locators (the citation map).
                cur.execute(
                    get(_FILE, "insert_chunk"),
                    {
                        "source_id": self.source.source_id,
                        "locator_id": span.locator_ids[0],
                        "chunk_index": span.chunk_index,
                        "text": span.text,
                    },
                )
                inserted = cur.fetchone()
                if inserted is None:
                    raise RuntimeError(
                        "insert_chunk returned no chunk_id — pipeline"
                        " invariant violated"
                    )
                chunk_id = inserted[0]
                for locator_span_id in span.locator_ids:
                    cur.execute(
                        get(_FILE, "insert_chunk_locator"),
                        {
                            "chunk_id": chunk_id,
                            "locator_id": locator_span_id,
                        },
                    )

    def update_toc(self) -> None:
        result = provider.generate(
            MODEL_TASKS[IngestionStage.UPDATE_TOC],
            self._prompt("Construct the course table of contents from the "
                         "following course material; cite locators."),
            self.owner_user_id,
            self.tier,
            course_id=self.source.course_id,
        )
        self._require_rows("toc", result)

    def extract_knowledge(self) -> None:
        result = provider.generate(
            MODEL_TASKS[IngestionStage.EXTRACT_KNOWLEDGE],
            self._prompt("Extract concepts, formulas, theorems, examples, "
                         "and misconceptions with evidence links."),
            self.owner_user_id,
            self.tier,
            course_id=self.source.course_id,
        )
        self._require_rows("course knowledge", result)

    def _prompt(self, instruction: str) -> str:
        assert self.extracted is not None
        window = self.extracted.text[: self.prompt_window_chars]
        return f"{instruction}\n\n{window}"

    def _require_rows(self, what: str, result: provider.GenerationResult) -> None:
        """A model stage that returns nothing would write no rows while
        the run reads SUCCEEDED — a false success. The provider seam
        guarantees non-empty text (EmptyModelError); row-writing itself
        lands with the provider's real output format, so until then this
        asserts the seam contract explicitly and fails closed."""
        if not result.text.strip():
            raise provider.EmptyModelError(what)


def run_ingestion(
    conn: Connection,
    source_id: UUID,
    owner_user_id: UUID,
    tier: UserTier,
) -> UUID:
    """Execute the full pipeline for one source inside the caller's
    transaction context. Tier is verified inside the provider seam (not
    trusted from this caller). Creates run + stage rows, executes stages
    with retries from the top, marks run/source terminal, clears the
    queue row. Returns run_id."""
    source = fetch_source_row(conn, source_id)
    ingestion_config = load_ingestion_config()
    handler_set = IngestionHandlers(
        conn,
        source,
        owner_user_id,
        tier,
        chunk_max_tokens=ingestion_config.chunk_max_tokens,
        prompt_window_chars=ingestion_config.prompt_window_chars,
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
            "prompt_window_chars": handler_set.prompt_window_chars,
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