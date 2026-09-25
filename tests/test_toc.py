"""TOC from the author's own structure (ingest/toc.py) — no model."""

import io
from uuid import UUID, uuid4

import pypdf
from src.backend.common import courses_repo, storage
from src.backend.common.db import connection
from src.backend.ingest import runs, toc
from src.backend.ingest.extract import ExtractedSource, _join_pages, _pdf_locators
from src.backend.ingest.orchestrator import run_ingestion
from src.backend.retrieval import funnel


def test_page_headings_use_size_not_bold_and_merge_wrapped_lines() -> None:
    runs_on_page = [
        (22.4, "Community Building in"),
        (22.4, "Latino America"),
        (11.2, "Body text that explains the idea at length. " * 5),
        (12.8, "Similar Historical Context"),
        (11.2, "More body text, with an emphasised word."),
        (11.2, "Hispanicity"),  # bold at body size = emphasis, not a heading
        (52.2, "O"),  # drop cap
        (12.8, "A sentence set large but ending in a period."),
    ]
    assert toc._page_headings(runs_on_page) == [
        "Community Building in Latino America",
        "Similar Historical Context",
    ]


def test_page_without_larger_text_has_no_headings() -> None:
    assert toc._page_headings([(11.0, "just body text " * 20)]) == []
    assert toc._page_headings([]) == []


def _pdf_with_bookmarks() -> bytes:
    writer = pypdf.PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=200)
    writer.add_outline_item("Introduction", 0)
    chapter = writer.add_outline_item("Chapter One", 1)
    writer.add_outline_item("A Subsection", 2, parent=chapter)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_bookmarks_become_entries_on_their_pages() -> None:
    pages = ["intro text", "chapter one text", "subsection text"]
    extracted = ExtractedSource(text=_join_pages(pages), locators=_pdf_locators(pages))
    drafts = toc.pdf_entries(extracted, _pdf_with_bookmarks())
    assert [d.title for d in drafts] == ["Introduction", "Chapter One", "A Subsection"]
    assert [d.locator_id for d in drafts] == [s.locator_id for s in extracted.locators]
    assert drafts[1].description == "chapter one text"


def _markdown_source(course_id: UUID) -> UUID:
    body = (
        b"# Eigenvalues\n\nAn eigenvalue scales its eigenvector.\n\n"
        b"# Orthogonality\n\nOrthogonal vectors have zero dot product.\n"
    )
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, body)
    with connection() as conn:
        conn.execute(
            "INSERT INTO sources (source_id, course_id, filename, mime_type,"
            " source_type, uri, status, file_hash, size_bytes, stored_encoding)"
            " VALUES (?, ?, 'notes.md', 'text/markdown', 'notes', ?, 'uploaded',"
            " ?, ?, 'identity')",
            (source_id, course_id, str(path), uuid4().hex, len(body)),
        )
        runs.enqueue_pending(conn, source_id, course_id, "uploaded_new_source")
        conn.commit()
    return source_id


def test_ingestion_builds_the_toc_and_the_toc_seam_finds_it() -> None:
    course_id = courses_repo.create_course("Linear Algebra").course_id
    source_id = _markdown_source(course_id)
    with connection() as conn:
        run_id = run_ingestion(conn, source_id)
        stage = conn.execute(
            "SELECT status, error_message FROM ingestion_stage_runs"
            " WHERE run_id = ? AND stage = 'update_toc'",
            (run_id,),
        ).fetchone()
        titles = [
            row["title"]
            for row in conn.execute(
                "SELECT title FROM toc_entries WHERE source_id = ? ORDER BY position",
                (source_id,),
            ).fetchall()
        ]
    assert (stage["status"], stage["error_message"]) == ("succeeded", None)
    assert titles == ["Eigenvalues", "Orthogonality"]

    with connection() as conn:
        candidates, entry_ids = funnel.toc_seam(
            conn, course_id, "what is orthogonality", limit=10
        )
    assert len(entry_ids) == 1
    assert any("zero dot product" in c.text for c in candidates.values())


def test_reingesting_replaces_a_sources_entries() -> None:
    course_id = courses_repo.create_course("Linear Algebra").course_id
    source_id = _markdown_source(course_id)
    for _ in range(2):
        with connection() as conn:
            run_ingestion(conn, source_id)
            conn.execute(
                "UPDATE sources SET status = 'uploaded' WHERE source_id = ?",
                (source_id,),
            )
            runs.enqueue_pending(conn, source_id, course_id, "again")
            conn.commit()
    with connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM toc_entries WHERE source_id = ?", (source_id,)
        ).fetchone()["n"]
    assert count == 2
