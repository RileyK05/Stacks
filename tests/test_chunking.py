import uuid as uuid_module

import pytest
from src.backend.ingest.chunking import chunk_text
from src.backend.ingest.extract import LocatorSpan

TEXT = " ".join(f"Sentence {i} talks about topic {i % 5}." for i in range(200))


def _locators(text: str) -> tuple[LocatorSpan, ...]:
    return (
        LocatorSpan(
            locator_id=uuid_module.uuid4(),
            locator_type="line_range",
            start=0,
            end=len(text) // 2,
            label="lines 1-10",
        ),
        LocatorSpan(
            locator_id=uuid_module.uuid4(),
            locator_type="line_range",
            start=len(text) // 2,
            end=len(text),
            label="lines 11-20",
        ),
    )


def test_chunks_are_token_bounded() -> None:
    spans = chunk_text(TEXT, (), max_tokens=100)
    assert spans
    for span in spans:
        assert len(span.text) <= 100 * 4


def test_chunks_are_consecutive_and_complete() -> None:
    spans = chunk_text(TEXT, (), max_tokens=100)
    joined = " ".join(span.text for span in spans)
    for token in TEXT.split():
        assert token in joined


def test_chunks_map_to_overlapping_locators() -> None:
    locators = _locators(TEXT)
    spans = chunk_text(TEXT, locators, max_tokens=100)
    for span in spans:
        assert span.locator_ids, "every chunk must cite at least one locator"
    referenced = {lid for span in spans for lid in span.locator_ids}
    assert referenced == {locator.locator_id for locator in locators}


def test_chunk_indices_are_sequential() -> None:
    spans = chunk_text(TEXT, (), max_tokens=100)
    assert [span.chunk_index for span in spans] == list(range(len(spans)))


def test_short_text_is_single_chunk() -> None:
    spans = chunk_text("one sentence only", (), max_tokens=100)
    assert len(spans) == 1
    assert spans[0].text == "one sentence only"


def test_empty_text_yields_no_chunks() -> None:
    assert chunk_text("", (), max_tokens=100) == ()


def test_rejects_zero_tokens() -> None:
    with pytest.raises(ValueError):
        chunk_text(TEXT, (), max_tokens=0)


def test_no_chunk_splits_midword() -> None:
    spans = chunk_text(TEXT, (), max_tokens=100)
    for span in spans:
        assert not span.text[0].islower() or span.text.startswith(TEXT[:1])


def test_chunk_offsets_align_with_text() -> None:
    spans = chunk_text(TEXT, (), max_tokens=100)
    for span in spans:
        assert TEXT[span.start : span.end].strip() == span.text
