"""Authored parent structure recovered without a separate TOC subsystem."""

import io
from uuid import UUID, uuid4

import pypdf
from src.backend.common import courses_repo, storage
from src.backend.common.db import connection
from src.backend.ingest import runs, structure
from src.backend.ingest.extract import ExtractedSource, _join_pages, _pdf_locators
from src.backend.ingest.orchestrator import run_ingestion


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
    assert structure._page_headings(runs_on_page) == [
        "Community Building in Latino America",
        "Similar Historical Context",
    ]


def test_page_without_larger_text_has_no_headings() -> None:
    assert structure._page_headings([(11.0, "just body text " * 20)]) == []
    assert structure._page_headings([]) == []


def test_same_baseline_fragments_are_one_heading_at_a_line_start() -> None:
    """Small-caps runs are one title. A fragment must not open a container
    in the middle of that word."""
    merged = structure._merge_baseline_runs(
        [
            (18.0, "C", 700.0),
            (18.0, "OMMUNITY B", 700.0),
            (18.0, "UILDING IN L", 700.0),
            (18.0, "ATINO AMERICA", 700.0),
            (11.0, "Body text that explains the idea at length. " * 4, 680.0),
        ]
    )
    assert structure._page_headings(merged) == ["COMMUNITY BUILDING IN LATINO AMERICA"]
    text = "COMMUNITY BUILDING IN LATINO AMERICA\nBody of the chapter is here."
    extracted = ExtractedSource(text=text, locators=_pdf_locators([text]))
    pages = [loc for loc in extracted.locators if loc.locator_type == "page"]
    titles = (
        "C",
        "OMMUNITY B",
        "UILDING IN L",
        "COMMUNITY BUILDING IN LATINO AMERICA",
    )
    starts = [
        structure._heading_start(
            extracted.text,
            pages[0].start,
            pages[0].end,
            title,
            allow_page_start=False,
        )
        for title in titles
    ]
    assert starts[:3] == [None, None, None]
    assert starts[3] == 0
    assert text[0].isupper()


def test_running_head_repeated_across_pages_is_dropped() -> None:
    title = "COMMUNITY BUILDING IN LATINO AMERICA"
    headings = [
        structure._Heading(0, title),
        structure._Heading(1, title),
        structure._Heading(2, "Chapter Two Latinos"),
        structure._Heading(3, title),
    ]
    kept = structure._drop_running_heads(headings, page_count=4)
    assert [heading.title for heading in kept] == ["Chapter Two Latinos"]


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
    drafts = structure.pdf_containers(extracted, _pdf_with_bookmarks())
    assert [d.title for d in drafts] == ["Introduction", "Chapter One", "A Subsection"]
    assert [d.start for d in drafts] == [s.start for s in extracted.locators]
    assert drafts[2].parent_index == 1


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
            "SELECT COUNT(*) AS n FROM passage_containers"
            " WHERE source_id = ? AND level > 0",
            (source_id,),
        ).fetchone()["n"]
    assert count == 2
