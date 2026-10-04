from __future__ import annotations

import hashlib
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from src.backend.artifacts import content, edit
from src.backend.common import (
    conversations_repo,
    courses_repo,
    providers,
    sources_repo,
    usage_repo,
)
from src.backend.common.db import connection
from src.backend.common.schemas.base import SourceType
from src.backend.ingest import runs, worker
from src.backend.ingest.extract import read_decoded
from src.backend.ingest.ocr_pages import OCR_PAGE_BOUNDARY, split_ocr_pages
from src.backend.office_reader import package
from src.backend.office_reader.merge import merge_reads
from src.backend.office_reader.models import DocumentRead, TextUnit
from src.backend.runtime import downloads
from src.backend.tutor.compose import compose_answer, parse_json_object
from src.backend.tutor.quotes import Quote, anchor_citations
from src.backend.tutor.workspace import extract_workspace_items


def test_citation_renumbering_preserves_executable_text() -> None:
    raw = {
        "code": "arr[0] = arr[12]",
        "html": "<script>x[12]</script>",
        "markdown": "Proof [1–2]. `arr[0]`\n\n```python\narr[9]\n```",
    }
    assert content.cited_numbers(raw) == {1, 2}
    changed = content.renumber(raw, {1: 3, 2: 4})
    assert changed["code"] == raw["code"] and changed["html"] == raw["html"]
    assert changed["markdown"] == raw["markdown"].replace("[1–2]", "[3, 4]")
    literal = content.validate_content(
        "doc", {"markdown": "Prose \\[1\\]\n\n```text\n\\[1\\]\n```"}
    )
    assert literal["markdown"] == "Prose [1]\n\n```text\n\\[1\\]\n```"


@pytest.mark.parametrize(
    "item",
    [
        '{"type":"sheet","columns":["A"],"rows":[["bad [1,9]"]],"sources":[1]}',
        '{"type":"quiz","questions":[{"prompt":"P",'
        '"options":["bad [1-9]","B"],"answer":0,"sources":[1]}]}',
    ],
)
def test_displayed_cells_and_options_cannot_cite_unprovided_sources(item: str) -> None:
    result = extract_workspace_items(f"```workspace\n{item}\n```", 2)
    assert not result.items and result.withheld


def test_plain_and_quoted_answers_cannot_keep_fabricated_markers() -> None:
    answer = compose_answer(
        "What is a basis?", (), lambda *args, **kwargs: "It is true [99]."
    )
    assert "withheld" in answer.text and "[99]" not in answer.text
    anchored = anchor_citations(
        "First [99], second [1,9].", [Quote(source=1, text="Verified quotation")]
    )
    assert "[99]" not in anchored and "[9]" not in anchored and "[1]" in anchored


def test_json_extraction_handles_multiple_objects_and_braces_in_strings() -> None:
    assert parse_json_object(
        'Intro {oops}. ```json\n{"text":"a } brace"}\n``` and {"second":2}'
    ) == {"text": "a } brace"}


def test_ocr_does_not_discard_or_misalign_overflow() -> None:
    with pytest.raises(ValueError, match="boundaries"):
        split_ocr_pages(OCR_PAGE_BOUNDARY.join(["first", "second", "lost"]), 2)


def test_ocr_accepts_line_separator_variants_and_trailing_boundary() -> None:
    assert split_ocr_pages("first\n---\nsecond", 2) == ["first", "second"]
    assert split_ocr_pages("first\r\n\r\n---\r\n\r\nsecond", 2) == [
        "first",
        "second",
    ]
    assert split_ocr_pages("first\n\n---\n\nsecond\n---\n", 2) == [
        "first",
        "second",
    ]


def test_ocr_keeps_a_real_last_blank_page() -> None:
    assert split_ocr_pages("recognized\n---\n", 2) == ["recognized", ""]


def test_ocr_refuses_to_guess_multiple_pages_without_boundaries() -> None:
    with pytest.raises(ValueError, match="boundaries"):
        split_ocr_pages("two pages merged into one response", 2)


def _upload(course_id, body: bytes):
    return sources_repo.upload_source(
        course_id,
        filename=f"{uuid4()}.txt",
        mime_type="text/plain",
        source_type=SourceType.NOTES,
        stream=io.BytesIO(body),
    )


def test_shutdown_does_not_preclaim_unprocessed_sources(monkeypatch) -> None:
    course_id = courses_repo.create_course("Stop test").course_id
    sources = [_upload(course_id, f"text {n}".encode()) for n in range(2)]
    stopped = False

    def ingest(source_id):
        nonlocal stopped
        stopped = True
        return True

    monkeypatch.setattr(worker, "_ingest_claimed", ingest)
    assert worker.process_batch(5, should_stop=lambda: stopped) == (1, 1)
    with connection() as conn:
        rows = conn.execute("SELECT claimed_at FROM pending_ingestion").fetchall()
    assert sum(row["claimed_at"] is None for row in rows) == 1
    assert len(sources) == 2


def test_retry_clears_stale_claim_and_late_failure_cannot_overwrite_success() -> None:
    course_id = courses_repo.create_course("Retry").course_id
    source = _upload(course_id, b"retry text")
    with connection() as conn:
        conn.execute(
            "UPDATE pending_ingestion SET claimed_at=?, claimed_runs=5 "
            "WHERE source_id=?",
            (datetime.now(UTC), source.source_id),
        )
        runs.mark_source_failed(conn, source.source_id, "failure")
        assert runs.requeue_failed_source(conn, source.source_id, course_id)
        row = conn.execute(
            "SELECT claimed_at, claimed_runs FROM pending_ingestion"
        ).fetchone()
        assert row == {"claimed_at": None, "claimed_runs": 0}
        runs.mark_source_indexed(conn, source.source_id)
        runs.mark_source_failed(conn, source.source_id, "late failure")
        runs.record_history(conn, source.source_id, course_id, "already cleared", None)
        conn.commit()
    assert sources_repo.get_source(course_id, source.source_id).status == "indexed"


def test_parallel_connection_additions_and_message_turns_are_preserved() -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        connections = list(
            pool.map(
                lambda _: providers.add_connection("custom", name="same name"), range(8)
            )
        )
    assert len({item.id for item in connections}) == 8
    assert len(providers.list_connections()) == 9
    course_id = courses_repo.create_course("Concurrent turns").course_id
    conversation_id = conversations_repo.create(course_id).conversation_id

    def add(number):
        with connection() as conn:
            pair = conversations_repo.add_turn(
                conn,
                conversation_id,
                question=str(number),
                answer="answer",
                trace_id=None,
                payload={},
            )
            conn.commit()
            return pair

    with ThreadPoolExecutor(max_workers=4) as pool:
        pairs = list(pool.map(add, range(8)))
    assert sorted(message.seq for pair in pairs for message in pair) == list(
        range(1, 17)
    )


def test_loopback_usage_does_not_consume_cloud_budget() -> None:
    for url in ("http://[::1]/v1", "https://localhost/v1", "http://127.0.0.2/v1"):
        assert providers._is_loopback(url)
    assert not providers._is_loopback("http://localhost.attacker.invalid/v1")
    usage_repo.record(
        task="tutor_answer",
        provider="environment",
        model="local",
        input_tokens=20,
        output_tokens=10,
        is_local=True,
    )
    assert usage_repo.cloud_tokens_this_month() == 0
    with pytest.raises(ValueError):
        usage_repo.set_monthly_budget(-1)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32", "utf-8-sig", "cp1252"])
def test_text_decoding_preserves_supported_unicode(encoding: str) -> None:
    course_id = courses_repo.create_course("Encodings").course_id
    source = _upload(course_id, "café — a proof".encode(encoding))
    assert (
        read_decoded(course_id, source.source_id, source.stored_encoding)
        == "café — a proof"
    )


def test_mislabelled_binary_text_fails_instead_of_becoming_evidence() -> None:
    course_id = courses_repo.create_course("Binary text").course_id
    source = _upload(course_id, b"%PDF-1.7 not text")
    with pytest.raises(ValueError, match="binary"):
        read_decoded(course_id, source.source_id, source.stored_encoding)


def _zip(parts: dict[str, str]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return stream.getvalue()


def test_office_parts_use_numeric_and_authored_order() -> None:
    parts = {
        f"ppt/slides/slide{n}.xml": (
            f'<root xmlns:a="{package._A}"><a:t>slide {n}</a:t></root>'
        )
        for n in range(1, 13)
    }
    assert [
        unit.text for unit in package.read_package(_zip(parts), kind="powerpoint").units
    ] == [f"slide {n}" for n in range(1, 13)]
    parts["ppt/presentation.xml"] = (
        f'<p:presentation xmlns:p="{package._P}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<p:sldIdLst><p:sldId r:id="r2"/><p:sldId r:id="r1"/></p:sldIdLst>'
        "</p:presentation>"
    )
    parts["ppt/_rels/presentation.xml.rels"] = (
        '<Relationships><Relationship Id="r1" Target="slides/slide1.xml"/>'
        '<Relationship Id="r2" Target="slides/slide2.xml"/></Relationships>'
    )
    assert [
        unit.text for unit in package.read_package(_zip(parts), kind="powerpoint").units
    ] == ["slide 2", "slide 1"]
    parts["ppt/slides/_rels/slide1.xml.rels"] = (
        '<Relationships><Relationship Id="n1" Type="test/notesSlide" '
        'Target="../notesSlides/notesSlide9.xml"/></Relationships>'
    )
    parts["ppt/notesSlides/notesSlide9.xml"] = (
        f'<root xmlns:a="{package._A}"><a:t>owned by slide one</a:t></root>'
    )
    parts["ppt/notesSlides/notesSlide2.xml"] = (
        f'<root xmlns:a="{package._A}"><a:t>unknown owner</a:t></root>'
    )
    read = package.read_package(_zip(parts), kind="powerpoint")
    assert (
        next(unit.label for unit in read.units if unit.text == "owned by slide one")
        == "speaker notes 2"
    )
    assert next(
        unit.label for unit in read.units if unit.text == "unknown owner"
    ).startswith("unlinked speaker notes")


def test_literal_code_with_longer_or_missing_closing_fences_keeps_indices() -> None:
    for literal in ("````python\na[99]\n```\nb[88]\n`````", "~~~python\na[99]"):
        raw = {"markdown": "Source [1]\n\n" + literal}
        assert content.cited_numbers(raw) == {1}
        assert content.renumber(raw, {1: 2})["markdown"] == ("Source [2]\n\n" + literal)


def test_office_read_bounds_expansion_and_counts_shared_formulas(monkeypatch) -> None:
    monkeypatch.setattr(package, "_MAX_PART_BYTES", 500)
    with pytest.raises(package.UnreadablePackageError, match="expanded"):
        package.read_package(_zip({"word/document.xml": "x" * 1000}), kind="word")
    monkeypatch.setattr(package, "_MAX_PART_BYTES", 40 * 1024 * 1024)
    workbook = _zip(
        {
            "xl/sharedStrings.xml": (
                f'<sst xmlns="{package._S}"><si><t>secret wrong value</t></si></sst>'
            ),
            "xl/worksheets/sheet1.xml": (
                f'<worksheet xmlns="{package._S}"><sheetData><row r="1">'
                '<c r="A1" t="s"><v>-1</v></c><c r="B1">'
                '<f t="shared">1+1</f><v>2</v></c></row></sheetData></worksheet>'
            ),
        }
    )

    read = package.read_package(workbook, kind="excel")
    assert "secret" not in read.text and "B1=2" in read.text
    assert any("1 formula" in warning for warning in read.warnings)


def test_office_xml_cannot_hide_entity_declarations_in_utf16() -> None:
    with pytest.raises(package.UnreadablePackageError, match="entities"):
        package._xml(
            '<!DOCTYPE root [<!ENTITY x "expanded">]><root>&x;</root>'.encode("utf-16")
        )


def test_model_copies_with_the_same_filename_are_independent(monkeypatch) -> None:
    import hashlib

    from src.backend.runtime import model_store
    from src.backend.runtime.config import CatalogModel

    model = CatalogModel(
        id="first",
        label="First",
        tier="starter",
        repo="org/first",
        file="model.gguf",
        sha256=hashlib.sha256(b"first").hexdigest(),
        size_bytes=5,
        min_ram_gb=1,
        license="test",
    )
    second = model.model_copy(update={"id": "second"})
    path = model_store.owned_path(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"first")
    assert model_store.installed_path(model) == path
    assert model_store.installed_path(second) is None
    assert not model_store.delete_model(second)
    assert path.read_bytes() == b"first"
    path.write_bytes(b"wrong")
    assert model_store.installed_path(model) is None


def test_read_agreement_is_not_inflated_by_same_method_duplicates() -> None:
    merged = merge_reads(
        [
            DocumentRead(
                method="scrape",
                host="word",
                units=(
                    TextUnit("1", "the full sentence"),
                    TextUnit("2", "the full sentence"),
                ),
            )
        ]
    )
    assert merged.agreement[0].matched == 0
    assert len(merged.units) == 1
    assert (
        edit._combine(
            "slides",
            {"slides": [{"title": "", "body": "", "notes": "speaker notes"}]},
            {"slides": [{"title": "new", "body": "new"}]},
        )["slides"][0]["notes"]
        == "speaker notes"
    )


def test_same_size_tampered_download_is_not_trusted(
    tmp_path: Path, monkeypatch
) -> None:
    from tests.test_runtime import _serve

    data = b"correct model"
    target = tmp_path / "model.gguf"
    target.write_bytes(b"X" * len(data))
    calls = _serve(monkeypatch, data)
    downloads.download_verified(
        "http://example/model",
        target,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )
    assert target.read_bytes() == data and calls
