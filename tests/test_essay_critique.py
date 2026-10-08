import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from src.backend.common.db import connection
from src.backend.common.prompt_registry import UNTRUSTED_BEGIN
from src.backend.common.schemas.work import CritiqueResult
from src.backend.common.work_archive import export_work, import_work
from src.backend.common.work_repo import list_sessions, session
from src.backend.retrieval.funnel import Candidate
from src.backend.tutor.critique import (
    band_name,
    critique_context,
    critique_instruction,
    finding_cap,
    reserve_course_evidence,
)
from tests.conftest import configure_test_provider
from tests.factories import add_chunk, chunk_source_locator, make_course

DRAFT = (
    "Democracy needs representation, but representation alone is not accountability."
)


def _candidate(text: str, source_type: str, rank: float = 0) -> Candidate:
    return Candidate(
        chunk_id=uuid4(),
        source_id=uuid4(),
        locator_id=None,
        chunk_index=0,
        text=text,
        layers=frozenset({"keyword"}),
        rank=rank,
        source_type=source_type,
    )


def _finding(original: str, feedback: str, **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "original": original,
        "feedback": feedback,
        "dimension": "reasoning",
        "grounding": "craft",
        "fallacy": "none",
    }
    body.update(extra)
    return body


def start(client: TestClient, purpose: str = "paper", text: str = DRAFT):
    course = make_course("Political science").course_id
    root = f"/companion/courses/{course}/work"
    created = client.post(root, json={"title": "Essay", "purpose": purpose})
    assert created.status_code == 200, created.text
    path = f"{root}/{created.json()['session_id']}"
    document = client.put(
        path + "/document",
        json={
            "expected_revision": 0,
            "title": "Draft",
            "text": text,
            "coverage": "document",
        },
    )
    assert document.status_code == 200, document.text
    return course, path


def ask(client: TestClient, path: str, revision: int = 1, **extra: object):
    body = {
        "request_id": str(uuid4()),
        "expected_revision": revision,
        "action": "critique",
        "instruction": "Critique the draft",
        "critic_score": 50,
        "essay_genre": "argumentative",
        **extra,
    }
    return client.post(path + "/ask", json=body), body


def test_caps_follow_the_harshness_anchors() -> None:
    assert finding_cap(10) == 2
    assert finding_cap(50) == 5
    assert finding_cap(100) == 8
    assert band_name(10) == "rough"
    assert band_name(50) == "strong"
    assert band_name(100) == "severe"


def test_prompt_uses_only_the_selected_band_and_lens() -> None:
    markers = {
        10: "Wordiness, a clumsy sentence, and a missing comma stay off the page.",
        50: "A weak warrant is in range.",
        100: "Wording is blunt and praise is omitted.",
    }
    lenses = {
        "argumentative": "Press the claim, the warrant, and the counterargument.",
        "analytical": "Press whether the interpretation is tied to the quoted text.",
        "research": "Press synthesis versus summary",
        "comparative": "Press whether both sides are compared.",
        "creative": "Press character motive, scene pressure, stakes",
        "reflective": "Press a specific experience against a general slogan",
        "rhetorical": "Press audience, purpose, and whether the draft",
    }
    for score, sentence in markers.items():
        text = critique_instruction(score, "argumentative", "")
        assert sentence in text
        for other in markers.values():
            if other != sentence:
                assert other not in text
        assert lenses["argumentative"] in text
        for genre, lens in lenses.items():
            if genre != "argumentative":
                assert lens not in text


def test_syllabus_passage_is_reserved_ahead_of_a_higher_ranked_note() -> None:
    notes = _candidate("A higher ranked lecture note about elections.", "notes", 1)
    syllabus = _candidate(
        "Required reading: Gonzalez on accountability.", "syllabus", 0
    )
    chosen, present = reserve_course_evidence(
        [notes],
        [notes, syllabus],
        "Gonzalez accountability",
        source_budget=5000,
        syllabus_chars=1800,
        syllabus_chunks=2,
    )
    assert present
    assert chosen[0].source_type == "syllabus"
    assert notes in chosen[1:]


def test_short_draft_is_a_complete_review_and_unread_sections_are_separate() -> None:
    text, coverage = critique_context(
        "A short thesis.",
        query="thesis",
        score=100,
        selection="",
        syllabus_text="",
        avoid=set(),
    )
    assert coverage.complete
    assert "[D1]" in text
    long = "word " * 4000
    partial, partial_coverage = critique_context(
        long,
        query="word",
        score=100,
        selection="",
        syllabus_text="",
        avoid=set(),
    )
    assert not partial_coverage.complete
    assert 1 in partial_coverage.included_sections
    assert partial_coverage.total_sections in partial_coverage.included_sections
    with pytest.raises(ValueError, match="already covered"):
        critique_context(
            long,
            query="word",
            score=100,
            selection="",
            syllabus_text="",
            avoid=set(partial_coverage.included_sections)
            if False
            else set(range(1, partial_coverage.total_sections + 1)),
        )
    unread, unread_coverage = critique_context(
        long,
        query="word",
        score=10,
        selection="",
        syllabus_text="",
        avoid={1},
    )
    assert 1 not in unread_coverage.included_sections
    assert "[D1]" not in unread
    assert unread_coverage.included_sections


def test_score_outside_the_scale_is_rejected(client: TestClient) -> None:
    _, path = start(client)
    response, _ = ask(client, path, critic_score=9)
    assert response.status_code == 422
    response, _ = ask(client, path, critic_score=101)
    assert response.status_code == 422
    assert client.get(path).json()["turns"] == []


def test_rewrite_request_saves_nothing(client: TestClient, monkeypatch) -> None:
    calls = configure_test_provider(monkeypatch, "{}")
    _, path = start(client)
    for instruction in ("Rewrite this paragraph", "write the essay"):
        response, _ = ask(client, path, instruction=instruction)
        assert response.status_code == 422, response.text
    assert calls == []
    assert client.get(path).json()["turns"] == []


def test_invalid_quotes_and_grounding_save_nothing(
    client: TestClient, monkeypatch
) -> None:
    course, path = start(client)
    add_chunk(course, "Representation alone does not ensure accountability.")
    cases = [
        _finding(
            "Representation alone does not ensure accountability.",
            "This is not the student's sentence.",
        ),
        _finding(DRAFT, "The warrant is thin."),
        _finding(DRAFT, "The motive is unearned. [9]"),
        _finding(DRAFT, "The claim is a straw man of the reading.", fallacy="nope"),
        {
            "findings": [
                _finding(DRAFT, "The warrant is thin."),
            ],
            "replacement": "A rewritten essay.",
        },
    ]
    # The second case is a course judgment with no citation. The third cites
    # a number the course did not supply. The fourth is not a known fallacy.
    cases[1]["grounding"] = "course"
    for payload in cases:
        body = payload if "findings" in payload else {"findings": [payload]}
        configure_test_provider(monkeypatch, json.dumps(body))
        response, _ = ask(client, path)
        assert response.status_code == 422, response.text
        assert client.get(path).json()["turns"] == []


def test_creative_fallacy_and_cap_and_clean_pass(
    client: TestClient, monkeypatch
) -> None:
    _, path = start(client)
    configure_test_provider(
        monkeypatch,
        json.dumps(
            {"findings": [_finding(DRAFT, "This is a straw man.", fallacy="straw_man")]}
        ),
    )
    response, _ = ask(client, path, essay_genre="creative")
    assert response.status_code == 422, response.text
    configure_test_provider(
        monkeypatch,
        json.dumps(
            {
                "findings": [
                    _finding(DRAFT[:20], "The opening promise is missing."),
                    _finding(DRAFT[20:40], "The warrant stops early."),
                    _finding(DRAFT[40:], "The ending does not land."),
                ]
            }
        ),
    )
    response, _ = ask(client, path, critic_score=10, essay_genre="creative")
    assert response.status_code == 200, response.text
    critique = CritiqueResult.model_validate(response.json()["critique"])
    assert critique.critic_score == 10
    assert len(critique.findings) == 2
    assert critique.findings[0].original == DRAFT[:20]
    configure_test_provider(monkeypatch, json.dumps({"findings": []}))
    response, _ = ask(client, path, critic_score=100, essay_genre="creative")
    assert response.status_code == 200, response.text
    empty = CritiqueResult.model_validate(response.json()["critique"])
    assert empty.findings == []
    assert "No grounded objection" in empty.note
    assert empty.coverage.complete


def test_second_pass_marks_edited_and_remaining_quotes(
    client: TestClient, monkeypatch
) -> None:
    kept = "The thesis is that representation is enough."
    dropped = "The city council example proves the point."
    _, path = start(client, text=f"{kept} {dropped}")
    calls = configure_test_provider(
        monkeypatch,
        json.dumps(
            {
                "findings": [
                    _finding(kept, "The thesis overclaims."),
                    _finding(dropped, "The example does not show the thesis."),
                ]
            }
        ),
    )
    assert ask(client, path)[0].status_code == 200
    updated = client.put(
        path + "/document",
        json={
            "expected_revision": 1,
            "title": "Draft",
            "text": f"{kept} A later sentence repairs the example.",
            "coverage": "document",
        },
    )
    assert updated.status_code == 200, updated.text
    calls = configure_test_provider(
        monkeypatch,
        json.dumps(
            {
                "findings": [
                    _finding(
                        "A later sentence repairs the example.",
                        "The repair still does not name a mechanism.",
                    )
                ]
            }
        ),
    )
    response, _ = ask(client, path, revision=2)
    assert response.status_code == 200, response.text
    prompt = str(calls[-1]["prompt"])
    assert f'"original": "{kept}"' in prompt
    assert '"status": "still_present"' in prompt
    assert f'"original": "{dropped}"' in prompt
    assert '"status": "passage_changed"' in prompt
    critique = CritiqueResult.model_validate(response.json()["critique"])
    statuses = {item.original: item.status for item in critique.prior}
    assert statuses[kept] == "still_present"
    assert statuses[dropped] == "passage_changed"


def test_syllabus_context_is_labeled_and_absence_is_explicit(
    client: TestClient, monkeypatch
) -> None:
    course, path = start(client)
    notes = add_chunk(course, "Democracy needs representation in the lecture.")
    syllabus = add_chunk(course, "Required reading: Democracy needs representation.")
    source_id, _ = chunk_source_locator(syllabus)
    with connection() as conn:
        conn.execute(
            "UPDATE sources SET source_type = 'syllabus' WHERE source_id = ?",
            (source_id,),
        )
        conn.commit()
    calls = configure_test_provider(
        monkeypatch,
        json.dumps(
            {
                "findings": [
                    _finding(
                        DRAFT,
                        "The draft names representation but not the required "
                        "reading. [1]",
                        grounding="course",
                        dimension="requirements",
                    )
                ]
            }
        ),
    )
    response, _ = ask(client, path)
    assert response.status_code == 200, response.text
    _instruction, material = str(calls[-1]["prompt"]).split(UNTRUSTED_BEGIN, 1)
    assert '"syllabus_in_context": true' in material
    assert '"role": "requirement"' in material
    assert notes
    missing, missing_path = start(client)
    add_chunk(missing, "Democracy needs representation in the lecture.")
    calls = configure_test_provider(
        monkeypatch,
        json.dumps({"findings": [_finding(DRAFT, "The opening promise is broad.")]}),
    )
    response, _ = ask(client, missing_path)
    assert response.status_code == 200, response.text
    assert response.json()["critique"]["syllabus_in_context"] is False
    assert '"syllabus_in_context": false' in str(calls[-1]["prompt"])


def test_critique_does_not_write_learning_rows(client: TestClient, monkeypatch) -> None:
    configure_test_provider(
        monkeypatch, json.dumps({"findings": [_finding(DRAFT, "The warrant is thin.")]})
    )
    course, path = start(client)
    before = client.get(f"/courses/{course}/learning").json()
    assert ask(client, path)[0].status_code == 200
    assert client.get(f"/courses/{course}/learning").json() == before
    with connection() as conn:
        for table in (
            "learning_observations",
            "learning_experiments",
            "core_method_observations",
            "learning_teaching_events",
            "practice_runs",
        ):
            assert (
                conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
            )


def test_settings_patch_and_archive_keep_the_critic(
    client: TestClient, monkeypatch
) -> None:
    configure_test_provider(
        monkeypatch,
        json.dumps(
            {"findings": [_finding(DRAFT, "The character of the argument is thin.")]}
        ),
    )
    course, path = start(client)
    patched = client.patch(path, json={"critic_score": 80, "essay_genre": "creative"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["critic_score"] == 80
    assert patched.json()["essay_genre"] == "creative"
    asked = ask(client, path, critic_score=80, essay_genre="creative")
    assert asked[0].status_code == 200
    imported = make_course("Imported").course_id
    with connection() as conn:
        archived = export_work(conn, course)
        import_work(conn, imported, archived, {}, {}, {})
        restored = session(conn, imported, list_sessions(conn, imported)[0].session_id)
        conn.commit()
    assert restored.critic_score == 80
    assert restored.essay_genre == "creative"
    assert restored.turns[0].reply.critique is not None
    assert (
        restored.turns[0]
        .reply.critique.findings[0]
        .feedback.startswith("The character")
    )


def test_office_critique_has_nothing_to_insert(monkeypatch) -> None:
    from src.backend.office_addin.app import create_office

    configure_test_provider(
        monkeypatch, json.dumps({"findings": [_finding(DRAFT, "The warrant is thin.")]})
    )
    office = TestClient(create_office())
    course = str(make_course("Political science").course_id)
    published = office.post(
        "/work-document",
        json={
            "course_id": course,
            "purpose": "paper",
            "document": {
                "title": "Draft",
                "text": DRAFT,
                "origin": "office",
                "coverage": "document",
                "warnings": [],
                "external_id": "essay-1",
            },
        },
    )
    assert published.status_code == 200, published.text
    work = published.json()
    response = office.post(
        "/critique",
        json={
            "course_id": course,
            "session_id": work["session_id"],
            "host": "word",
            "request_id": str(uuid4()),
            "expected_revision": work["revision"],
            "critic_score": 100,
            "essay_genre": "argumentative",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "critique"
    assert body["insert_text"] == ""
    assert body["critique"]["findings"]
    refused = office.post(
        "/critique",
        json={
            "course_id": course,
            "session_id": work["session_id"],
            "host": "excel",
            "request_id": str(uuid4()),
            "expected_revision": work["revision"],
            "critic_score": 50,
            "essay_genre": "argumentative",
        },
    )
    assert refused.status_code == 422
