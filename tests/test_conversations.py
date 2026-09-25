"""Saved chats (docs/plan-notebook.md §4.2): conversations API, chat
context for the model, source selection, per-chat model, rolling summary."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from src.backend.common import conversations_repo, provider, providers
from src.backend.common.db import connection
from src.backend.common.providers import ProviderChoice, TaskClass
from src.backend.tutor import chat
from tests.conftest import configure_test_provider
from tests.factories import add_chunk, chunk_source_locator

ANSWER = "Linearity preserves addition and scaling [1]."


def _course(client: TestClient) -> str:
    course_id: str = client.post("/courses", json={"name": "Linear algebra"}).json()[
        "course_id"
    ]
    add_chunk(UUID(course_id), "linearity means preserving addition and scaling.")
    return course_id


def _chat(client: TestClient, course_id: str, **body: Any) -> str:
    response = client.post(f"/courses/{course_id}/conversations", json=body)
    assert response.status_code == 201, response.text
    conversation_id: str = response.json()["conversation_id"]
    return conversation_id


def _send(
    client: TestClient, course_id: str, chat_id: str, question: str, **extra: Any
):
    response = client.post(
        f"/courses/{course_id}/conversations/{chat_id}/messages",
        json={"question": question, **extra},
    )
    return response


def test_a_chat_is_saved_and_titled_from_its_first_question(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)

    turn = _send(client, course_id, chat_id, "What is linearity?")
    assert turn.status_code == 200, turn.text
    body = turn.json()
    assert body["question"]["role"] == "user"
    assert body["reply"]["answer"]["text"] == ANSWER
    assert body["reply"]["answer"]["chunk_ids"]
    assert body["conversation"]["title"] == "What is linearity?"

    opened = client.get(f"/courses/{course_id}/conversations/{chat_id}").json()
    assert [m["role"] for m in opened["messages"]] == ["user", "assistant"]
    trace_id = opened["messages"][1]["answer"]["trace_id"]
    citations = client.get(f"/courses/{course_id}/traces/{trace_id}/citations")
    assert citations.status_code == 200 and len(citations.json()) == 1, (
        "an old answer still opens its sources"
    )

    listed = client.get(f"/courses/{course_id}/conversations").json()
    assert [(c["conversation_id"], c["message_count"]) for c in listed] == [
        (chat_id, 2)
    ]


def test_unlimited_chats_listed_newest_first(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    configure_test_provider(monkeypatch, ANSWER)
    first = _chat(client, course_id, title="Exam prep")
    second = _chat(client, course_id)
    _send(client, course_id, first, "What is linearity?")
    listed = [
        c["conversation_id"]
        for c in client.get(f"/courses/{course_id}/conversations").json()
    ]
    assert listed == [first, second]
    titles = {
        c["conversation_id"]: c["title"]
        for c in client.get(f"/courses/{course_id}/conversations").json()
    }
    assert titles[first] == "Exam prep", "a chosen title is kept"


def test_follow_ups_see_the_conversation_but_cite_only_material(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    calls = configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)
    _send(client, course_id, chat_id, "What is linearity?")
    _send(client, course_id, chat_id, "Give an example of it")

    first, second = (str(call["prompt"]) for call in calls)
    assert "Conversation so far" not in first
    assert "Conversation so far (context only)" in second
    assert "Student: What is linearity?" in second
    # Earlier citation numbers are dropped: they pointed at another list.
    assert "Tutor: Linearity preserves addition and scaling." in second
    fence = second.index("UNTRUSTED_COURSE_MATERIAL begin")
    assert second.index("Conversation so far") > fence, (
        "the conversation is inside the fence, as data"
    )


def test_chat_answers_skip_the_answer_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    calls = configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)
    _send(client, course_id, chat_id, "What is linearity?")
    again = _send(client, course_id, chat_id, "What is linearity?").json()
    assert len(calls) == 2 and again["reply"]["answer"]["cached"] is False


def test_follow_up_search_includes_the_previous_questions() -> None:
    context = chat.ChatContext(
        summary="", recent=(), previous_questions=("Why?", "What is a basis?")
    )
    assert chat.retrieval_query("and its dimension?", context) == (
        "and its dimension?\nWhy?\nWhat is a basis?"
    )
    long_question = (
        "Please explain in detail how the rank nullity theorem connects "
        "to bases and to dimension"
    )
    assert chat.retrieval_query(long_question, context) == long_question
    assert chat.retrieval_query("what?", None) == "what?"


def test_source_selection_narrows_retrieval(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    other = add_chunk(UUID(course_id), "linearity also appears in chapter two.")
    other_source, _ = chunk_source_locator(other)
    calls = configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)

    updated = client.patch(
        f"/courses/{course_id}/conversations/{chat_id}",
        json={"source_ids": [str(other_source)]},
    )
    assert updated.status_code == 200 and updated.json()["source_ids"] == [
        str(other_source)
    ]
    _send(client, course_id, chat_id, "What is linearity?")
    prompt = str(calls[-1]["prompt"])
    assert "chapter two" in prompt and "preserving addition" not in prompt

    reset = client.patch(
        f"/courses/{course_id}/conversations/{chat_id}", json={"source_ids": None}
    )
    assert reset.json()["source_ids"] is None
    empty = client.patch(
        f"/courses/{course_id}/conversations/{chat_id}", json={"source_ids": []}
    )
    assert empty.status_code == 422
    foreign = client.patch(
        f"/courses/{course_id}/conversations/{chat_id}",
        json={"source_ids": ["00000000-0000-0000-0000-000000000001"]},
    )
    assert foreign.status_code == 422


def test_a_chat_can_pin_its_own_model(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    _memory_keyring: dict[str, str],
) -> None:
    course_id = _course(client)
    calls = configure_test_provider(monkeypatch, ANSWER)
    connection = providers.add_connection("openai", name="Work OpenAI")
    _memory_keyring[connection.id] = "sk-test"
    chat_id = _chat(client, course_id)
    pinned = client.patch(
        f"/courses/{course_id}/conversations/{chat_id}",
        json={"model_choice": {"connection": connection.id, "model": "gpt-test"}},
    )
    assert pinned.status_code == 200
    reply = _send(client, course_id, chat_id, "What is linearity?").json()["reply"]
    endpoint = calls[-1]["endpoint"]
    assert (endpoint.connection, endpoint.model) == (connection.id, "gpt-test")
    assert reply["answer"]["model"] == "gpt-test"

    unknown = client.patch(
        f"/courses/{course_id}/conversations/{chat_id}",
        json={"model_choice": {"connection": "nope"}},
    )
    assert unknown.status_code == 422


def test_a_pinned_model_without_its_key_says_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    configure_test_provider(monkeypatch, ANSWER)
    connection = providers.add_connection("openai")
    chat_id = _chat(client, course_id)
    client.patch(
        f"/courses/{course_id}/conversations/{chat_id}",
        json={"model_choice": {"connection": connection.id, "model": "gpt-test"}},
    )
    failed = _send(client, course_id, chat_id, "What is linearity?")
    assert failed.status_code == 503
    assert "this chat's model isn't available" in failed.json()["detail"]
    opened = client.get(f"/courses/{course_id}/conversations/{chat_id}").json()
    assert opened["messages"] == [], "an unanswered question is not recorded"


def test_a_pinned_rate_limited_model_does_not_fall_back(
    monkeypatch: pytest.MonkeyPatch, _memory_keyring: dict[str, str]
) -> None:
    connection = providers.add_connection("openrouter")
    _memory_keyring[connection.id] = "sk-or"
    providers.save_choice(TaskClass.INTERACTIVE, ProviderChoice(preset="local"))

    def limited(task, endpoint, prompt, *, images=None, response_schema=None):
        raise provider.ProviderRateLimitedError("429")

    monkeypatch.setattr(provider, "_call_provider", limited)
    with pytest.raises(provider.ProviderRateLimitedError):
        provider.generate(
            "tutor_answer", "p", choice=ProviderChoice(connection=connection.id)
        )


def test_nothing_relevant_is_recorded_as_the_reply(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = client.post("/courses", json={"name": "Empty"}).json()["course_id"]
    configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)
    turn = _send(client, course_id, chat_id, "What is linearity?")
    assert turn.status_code == 200
    reply = turn.json()["reply"]
    assert reply["no_match"] is True and reply["answer"] is None
    assert "nothing in the course materials" in reply["text"]


def test_older_turns_are_folded_into_a_rolling_summary(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    calls = configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)
    for question in ("What is linearity?", "Why?", "An example?"):
        reply = _send(client, course_id, chat_id, question).json()["reply"]
        assert reply["no_match"] is False, "a follow-up chain keeps its topic"

    summaries = [c for c in calls if c["task"] == "conversation_summary"]
    assert len(summaries) == 1, "the first exchange left the recent window"
    assert "Student: What is linearity?" in str(summaries[0]["prompt"])
    stored = conversations_repo.get_conversation(UUID(course_id), UUID(chat_id))
    assert stored is not None
    assert stored.summary == ANSWER and stored.summary_through == 2

    _send(client, course_id, chat_id, "More on linearity?")
    prompt = str([c for c in calls if c["task"] == "tutor_answer"][-1]["prompt"])
    assert "Summary of the earlier conversation" in prompt


def test_a_failed_summary_never_fails_the_chat(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    configure_test_provider(monkeypatch, ANSWER)
    real = provider._call_provider

    def flaky(task, endpoint, prompt, *, images=None, response_schema=None):
        if task == "conversation_summary":
            raise provider.ProviderUnavailableError("down")
        return real(
            task, endpoint, prompt, images=images, response_schema=response_schema
        )

    monkeypatch.setattr(provider, "_call_provider", flaky)
    chat_id = _chat(client, course_id)
    for question in ("What is linearity?", "Why?", "An example?"):
        assert _send(client, course_id, chat_id, question).status_code == 200


def test_rename_delete_and_course_scoping(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    other_course = client.post("/courses", json={"name": "Other"}).json()["course_id"]
    configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)
    _send(client, course_id, chat_id, "What is linearity?")

    renamed = client.patch(
        f"/courses/{course_id}/conversations/{chat_id}", json={"title": "Week 1"}
    )
    assert renamed.json()["title"] == "Week 1"
    assert (
        client.get(f"/courses/{other_course}/conversations/{chat_id}").status_code
        == 404
    )

    assert (
        client.delete(f"/courses/{course_id}/conversations/{chat_id}").status_code
        == 204
    )
    assert (
        client.get(f"/courses/{course_id}/conversations/{chat_id}").status_code == 404
    )
    with connection() as conn:
        left = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
    assert left == 0, "messages go with their chat"


def test_purging_a_course_removes_its_chats(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client)
    configure_test_provider(monkeypatch, ANSWER)
    _send(client, course_id, _chat(client, course_id), "What is linearity?")
    client.delete(f"/courses/{course_id}")
    assert client.delete(f"/trash/{course_id}").status_code == 204
    with connection() as conn:
        counts = [
            conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in ("conversations", "messages")
        ]
    assert counts == [0, 0]


def test_titles_are_one_trimmed_line() -> None:
    assert (
        conversations_repo.title_from("  What   is\nlinearity? ")
        == "What is linearity?"
    )
    long = conversations_repo.title_from("word " * 40)
    assert len(long) <= conversations_repo.TITLE_MAX_LENGTH and long.endswith("…")


def test_citations_come_back_in_the_order_the_model_numbered_them(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[n] in an answer is the n-th chunk the model read; the citation list
    must use the same order, or "Sources used" shows the wrong excerpt."""
    course_id = _course(client)
    for text in ("linearity in chapter two", "linearity in chapter three"):
        add_chunk(UUID(course_id), text)
    calls = configure_test_provider(monkeypatch, ANSWER)
    reply = _send(client, course_id, _chat(client, course_id), "What is linearity?")
    answer = reply.json()["reply"]["answer"]
    cited = client.get(
        f"/courses/{course_id}/traces/{answer['trace_id']}/citations"
    ).json()
    assert [c["chunk_id"] for c in cited] == answer["chunk_ids"]
    prompt = str(calls[-1]["prompt"])
    numbered = [prompt.index(f"chunk {c['chunk_id']}") for c in cited]
    assert numbered == sorted(numbered), "[1] is the first chunk in the prompt"
