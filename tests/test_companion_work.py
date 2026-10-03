import json
from uuid import UUID, uuid4

import pytest
from src.backend.common import work_repo
from src.backend.common.db import connection
from src.backend.common.schemas.work import DocumentUpdate
from src.backend.office_reader import capture
from src.backend.tutor.work import document_context
from tests.conftest import configure_test_provider
from tests.factories import add_chunk, make_course


def review_reply(feedback):
    return json.dumps(
        {
            "findings": [
                {
                    "original": (
                        "Democracy needs representation, "
                        "but representation alone is not accountability."
                    ),
                    "feedback": feedback,
                }
            ]
        }
    )


def start(
    client,
    purpose="paper",
    text=(
        "Democracy needs representation, "
        "but representation alone is not accountability."
    ),
):
    course = make_course("Political science").course_id
    root = f"/companion/courses/{course}/work"
    response = client.post(
        root, json={"title": "Representation paper", "purpose": purpose}
    )
    assert response.status_code == 200, response.text
    work = response.json()
    path = f"{root}/{work['session_id']}"
    response = client.put(
        path + "/document",
        json={
            "expected_revision": 0,
            "title": "My draft",
            "text": text,
            "coverage": "document",
        },
    )
    assert response.status_code == 200, response.text
    return course, path, response.json()


def ask(client, path, instruction="Review my argument", **kwargs):
    body = {
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "instruction": instruction,
        "action": "review",
        **kwargs,
    }
    return client.post(path + "/ask", json=body), body


@pytest.mark.parametrize("purpose", ["paper", "slides", "practice", "reference"])
def test_work_is_saved_but_never_becomes_learning_evidence(
    client, monkeypatch, purpose
):
    calls = configure_test_provider(
        monkeypatch,
        review_reply("[D1] Your conclusion needs a clearer connection to the premise."),
    )
    course, path, work = start(client, purpose)
    before = client.get(f"/courses/{course}/learning").json()
    response, _ = ask(client, path)
    assert response.status_code == 200, response.text
    loaded = client.get(path).json()
    assert loaded["document"]["text"] == work["document"]["text"]
    assert loaded["turns"][0]["reply"]["text"] == response.json()["text"]
    assert client.get(f"/courses/{course}/learning").json() == before
    assert client.get(f"/courses/{course}/sources").json() == []
    with connection() as conn:
        for table in (
            "learning_observations",
            "learning_experiments",
            "core_method_observations",
            "learning_teaching_events",
            "practice_runs",
            "source_indexes",
            "passage_windows",
        ):
            assert (
                conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
            )
    assert len(calls) == 1


def test_followup_has_document_and_previous_conversation(client, monkeypatch):
    calls = configure_test_provider(
        monkeypatch,
        review_reply("[D1] Explain how elections connect to accountability."),
    )
    _, path, _ = start(client)
    assert ask(client, path)[0].status_code == 200
    assert ask(client, path, "Why that connection?")[0].status_code == 200
    assert "Explain how elections connect to accountability" in str(calls[-1]["prompt"])
    assert "Democracy needs representation" in str(calls[-1]["prompt"])


def test_document_and_request_revision_prevent_stale_results(client, monkeypatch):
    configure_test_provider(monkeypatch)
    course, path, work = start(client)
    wrong = client.put(
        path + "/document",
        json={"expected_revision": 0, "title": "Wrong", "text": "Changed"},
    )
    assert wrong.status_code == 409
    assert ask(client, path, expected_revision=2)[0].status_code == 409
    from src.backend.common import provider

    def generate(*args, **kwargs):
        with connection() as conn:
            work_repo.update_document(
                conn,
                course,
                UUID(work["session_id"]),
                DocumentUpdate(
                    expected_revision=1,
                    title="Changed draft",
                    text="A different argument",
                ),
            )
            conn.commit()
        return provider.GenerationResult(
            text=review_reply("Review of original draft"),
            model="stub",
            input_tokens=1,
            output_tokens=1,
        )

    monkeypatch.setattr(provider, "generate", generate)
    response, _ = ask(client, path)
    assert response.status_code == 409, response.text
    assert client.get(path).json()["turns"] == []


def test_request_retry_is_idempotent_and_not_reinterpreted(client, monkeypatch):
    calls = configure_test_provider(monkeypatch, review_reply("Review [D1]."))
    _, path, _ = start(client)
    response, body = ask(client, path)
    assert response.status_code == 200
    retry = client.post(path + "/ask", json=body)
    assert retry.json() == response.json()
    assert len(calls) == 1
    assert len(client.get(path).json()["turns"]) == 1
    assert (
        client.post(
            path + "/ask", json={**body, "instruction": "Different request"}
        ).status_code
        == 409
    )


def test_find_returns_exact_course_passages_and_never_cites_draft(client):
    course, path, _ = start(
        client, text="My unsupported claim: democracy means everyone agrees."
    )
    passage = "Democracy requires accountable representation, not unanimous agreement."
    chunk = add_chunk(course, passage, label="Chapter 2, page 14")
    add_chunk(
        make_course("Excluded course").course_id, "Democracy excludes all disagreement."
    )
    response, _ = ask(client, path, "democracy representation", action="find")
    assert response.status_code == 200, response.text
    citations = response.json()["citations"]
    assert len(citations) == 1
    assert citations[0]["text"] == passage
    assert citations[0]["chunk_id"] == str(chunk)
    assert passage in response.json()["text"]


def test_file_reads_tail_and_does_not_ingest(client):
    course, path, _ = start(client)
    content = (
        "Beginning\n"
        + "Middle\n" * 2000
        + "Final counterargument: representation is insufficient."
    )
    response = client.post(
        path + "/file",
        data={"expected_revision": "1"},
        files={"file": ("paper.md", content.encode())},
    )
    assert response.status_code == 200, response.text
    assert response.json()["document"]["text"] == content
    assert client.get(f"/courses/{course}/sources").json() == []
    context, coverage = document_context(
        content, "Final counterargument representation insufficient"
    )
    assert "Final counterargument" in context
    assert not coverage.complete
    assert coverage.included_sections[-1] == coverage.total_sections


def test_wrong_course_selection_and_bad_citations_fail_closed(client, monkeypatch):
    configure_test_provider(
        monkeypatch, review_reply("Invented academic support [999].")
    )
    _, path, _ = start(client)
    assert ask(client, path)[0].status_code == 422
    assert (
        ask(client, path, selection="Text from another document")[0].status_code == 422
    )
    other = make_course().course_id
    session_id = path.split("/")[-1]
    assert (
        client.get(f"/companion/courses/{other}/work/{session_id}").status_code == 404
    )


def test_office_shares_same_work_session_without_learning_writes(client):
    from src.backend.api.office import publish_work
    from src.backend.common.schemas.work import DocumentInput, WorkPublish

    course = make_course().course_id
    payload = WorkPublish(
        course_id=course,
        document=DocumentInput(
            title="Word draft", text="Body and final paragraph", coverage="partial"
        ),
    )
    work = publish_work(payload)
    path = f"/companion/courses/{course}/work/{work.session_id}"
    assert client.get(path).json()["document"]["text"] == "Body and final paragraph"
    payload.session_id = work.session_id
    payload.expected_revision = work.revision
    payload.document.text = "Updated final paragraph"
    updated = publish_work(payload)
    assert updated.revision == 2
    assert client.get(path).json()["document"]["origin"] == "office"


def test_capture_reports_partial_scope_and_rejects_changed_window(monkeypatch):
    window = capture.CaptureWindow(handle=42, process_id=123, title="Paper")
    monkeypatch.setattr(capture, "list_windows", lambda: [window])
    monkeypatch.setattr(
        capture,
        "_run",
        lambda *args: {"text": "Full exposed body", "image": "", "limited": False},
    )
    document = capture.capture(window)
    assert document.coverage == "partial"
    assert document.origin == "accessibility"
    assert document.warnings
    monkeypatch.setattr(capture, "list_windows", lambda: [])
    with pytest.raises(capture.CaptureUnavailableError):
        capture.capture(window)


def test_archive_preserves_snapshots_references_and_remaps_identity(
    client, monkeypatch
):
    from src.backend.common.archive_notebook import export_notebook, import_notebook

    course, path, _ = start(client)
    add_chunk(course, "Democracy needs accountability.")
    assert ask(client, path, "democracy", action="find")[0].status_code == 200
    archive = export_notebook(course)
    assert len(archive.work_sessions) == 1
    other = make_course("Imported").course_id
    # Exercise the same notebook remapping seam used by real .course imports.
    source_id = UUID(archive.citations[0].source_id.hex)
    from tests.factories import insert_source

    new_source = insert_source(other)
    with connection() as conn:
        import_notebook(conn, other, archive, {source_id: new_source})
        conn.commit()
        imported = work_repo.list_sessions(conn, other)[0]
        restored = work_repo.session(conn, other, imported.session_id)
    assert str(restored.session_id) != path.split("/")[-1]
    assert restored.document.text == archive.work_sessions[0].documents[0].text
    assert (
        restored.turns[0].reply.citations[0].text == "Democracy needs accountability."
    )
    assert restored.turns[0].reply.citations[0].source_id == str(new_source)
    assert (
        restored.turns[0].reply.citations[0].chunk_id
        != archive.work_sessions[0].turns[0].reply.citations[0].chunk_id
    )


def test_deleting_work_keeps_course_sources_and_removes_snapshots(client):
    course, path, _ = start(client)
    add_chunk(course, "Democracy requires accountability.")
    assert client.delete(path).status_code == 200
    assert client.get(path).status_code == 404
    with connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM work_documents").fetchone()["n"]
            == 0
        )
    assert len(client.get(f"/courses/{course}/sources").json()) == 1


def test_course_file_round_trip_preserves_work_documents_and_references(client):
    from pathlib import Path

    from tests.factories import insert_chunk

    course, path, _ = start(client)
    upload = client.post(
        f"/courses/{course}/sources",
        data={"source_type": "notes"},
        files={
            "file": ("reading.txt", b"Democracy requires accountability.", "text/plain")
        },
    )
    assert upload.status_code == 201
    source_id = UUID(upload.json()["source_id"])
    insert_chunk(source_id, "Democracy requires accountability.")
    with connection() as conn:
        conn.execute(
            "UPDATE sources SET status = 'indexed' WHERE source_id = ?", (source_id,)
        )
        conn.commit()
    assert (
        ask(client, path, "democracy accountability", action="find")[0].status_code
        == 200
    )
    exported = client.post(f"/courses/{course}/export")
    assert exported.status_code == 200
    with Path(exported.json()["path"]).open("rb") as handle:
        imported = client.post(
            "/courses/import",
            files={"file": ("work.course", handle, "application/zip")},
        )
    assert imported.status_code == 201, imported.text
    new_course = imported.json()["course"]["course_id"]
    summaries = client.get(f"/companion/courses/{new_course}/work").json()
    restored = client.get(
        f"/companion/courses/{new_course}/work/{summaries[0]['session_id']}"
    ).json()
    assert restored["document"]["text"] == client.get(path).json()["document"]["text"]
    assert (
        restored["turns"][0]["reply"]["citations"][0]["text"]
        == "Democracy requires accountability."
    )


def test_scanned_pdf_is_not_mistaken_for_readable_document(client):
    import io

    from pypdf import PdfWriter

    _, path, _ = start(client)
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=600)
    stream = io.BytesIO()
    writer.write(stream)
    response = client.post(
        path + "/file",
        data={"expected_revision": "1"},
        files={"file": ("scan.pdf", stream.getvalue(), "application/pdf")},
    )
    assert response.status_code == 422
    assert client.get(path).json()["revision"] == 1


def test_revision_proposes_real_replacement_and_never_changes_draft(
    client, monkeypatch
):
    original = "Representation guarantees accountability."
    edit = {
        "original": original,
        "replacement": "Representation alone does not ensure accountability. [1]",
        "explanation": (
            "The course distinguishes representation from accountability. [1]"
        ),
    }
    configure_test_provider(monkeypatch, json.dumps(edit))
    course, path, work = start(client, text=original)
    add_chunk(course, "Representation alone does not ensure accountability.")
    response, body = ask(client, path, "Fix my unsupported claim", action="revise")
    assert response.status_code == 200, response.text
    assert response.json()["proposed_edit"] == edit
    assert edit["replacement"] in response.json()["text"]
    assert client.get(path).json()["document"] == work["document"]
    assert client.post(path + "/ask", json=body).json() == response.json()
    with connection() as conn:
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM learning_observations").fetchone()[
                "n"
            ]
            == 0
        )


@pytest.mark.parametrize(
    "generated",
    [
        "You should revise your claim to distinguish representation "
        "from accountability.",
        json.dumps(
            {
                "original": "A made-up passage",
                "replacement": "New wording",
                "explanation": "Fixes it",
            }
        ),
        json.dumps(
            {
                "original": "Representation alone is insufficient.",
                "replacement": "Representation alone is insufficient.",
                "explanation": "Already good",
            }
        ),
        json.dumps(
            {
                "original": "Representation alone is insufficient.",
                "replacement": "   ",
                "explanation": "Removed it",
            }
        ),
    ],
)
def test_revision_rejects_critique_fabricated_passage_and_empty_changes(
    client, monkeypatch, generated
):
    configure_test_provider(monkeypatch, generated)
    _, path, _ = start(client, text="Representation alone is insufficient.")
    response, _ = ask(client, path, action="revise")
    assert response.status_code == 422, response.text
    assert client.get(path).json()["turns"] == []


def test_revision_stays_within_selected_passage(client, monkeypatch):
    configure_test_provider(
        monkeypatch,
        json.dumps(
            {
                "original": "The conclusion needs work.",
                "replacement": "A new conclusion.",
                "explanation": "Clearer",
            }
        ),
    )
    _, path, _ = start(
        client, text="The introduction needs work. The conclusion needs work."
    )
    response, _ = ask(
        client, path, action="revise", selection="The introduction needs work."
    )
    assert response.status_code == 422
    assert client.get(path).json()["turns"] == []


def test_archived_work_missing_sources_stays_inspectable_without_old_links(client):
    from src.backend.common.work_archive import export_work, import_work

    course, path, _ = start(client)
    add_chunk(course, "Representation alone does not ensure accountability.")
    assert ask(client, path, "representation", action="find")[0].status_code == 200
    imported_course = make_course("Imported without source").course_id
    second_course = make_course("Second import").course_id
    with connection() as conn:
        archived = export_work(conn, course)
        old_citation = archived[0].turns[0].reply.citations[0]
        import_work(conn, imported_course, archived, {}, {}, {})
        restored = work_repo.session(
            conn,
            imported_course,
            work_repo.list_sessions(conn, imported_course)[0].session_id,
        )
        quote = restored.turns[0].reply.citations[0]
        assert quote.text == old_citation.text
        assert quote.chunk_id != old_citation.chunk_id
        assert quote.source_id is None
        assert restored.turns[0].reply.trace_id is None
        # A second export/import retains the snapshot without resurrecting old IDs.
        again = export_work(conn, imported_course)
        import_work(conn, second_course, again, {}, {}, {})
        second = work_repo.session(
            conn,
            second_course,
            work_repo.list_sessions(conn, second_course)[0].session_id,
        )
        assert second.turns[0].reply.citations[0].text == old_citation.text
        assert second.turns[0].reply.citations[0].source_id is None
        assert second.turns[0].reply.citations[0].chunk_id != quote.chunk_id


def test_review_cannot_mistake_course_evidence_for_student_claim(client, monkeypatch):
    configure_test_provider(
        monkeypatch,
        json.dumps(
            {
                "findings": [
                    {
                        "original": (
                            "Representation alone does not ensure accountability."
                        ),
                        "feedback": "This is the student's unsupported claim. [1]",
                    }
                ]
            }
        ),
    )
    course, path, _ = start(client, text="Representation guarantees accountability.")
    add_chunk(course, "Representation alone does not ensure accountability.")
    response, _ = ask(client, path)
    assert response.status_code == 422
    assert client.get(path).json()["turns"] == []
