"""The chat as a student meets it: small talk, requests about the whole
course, and the failures a second try fixes. Each test is a message the
saved-chat endpoint used to answer badly (or refuse)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from src.backend.common import provider, providers
from src.backend.common.conversations_repo import Conversation, Message
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.tutor import chat
from src.backend.tutor.compose import (
    Intent,
    asks_for_overview,
    classify_intent,
    compose_chat,
    retrieval_topic,
)
from tests.conftest import configure_test_provider
from tests.factories import add_chunk

ANSWER = "Linearity preserves addition and scaling [1]."
HELLO = "Hello! I'm ready when you are."


def _course(client: TestClient, *texts: str) -> str:
    course_id: str = client.post("/courses", json={"name": "Linear algebra"}).json()[
        "course_id"
    ]
    model = load_embedding_policy().model
    for text in texts:
        add_chunk(UUID(course_id), text, embedding=[0.1, 0.2], embedding_model=model)
    return course_id


def _chat(client: TestClient, course_id: str) -> str:
    response = client.post(f"/courses/{course_id}/conversations", json={})
    assert response.status_code == 201, response.text
    conversation_id: str = response.json()["conversation_id"]
    return conversation_id


def _send(client: TestClient, course_id: str, chat_id: str, question: str):
    return client.post(
        f"/courses/{course_id}/conversations/{chat_id}/messages",
        json={"question": question},
    )


def _no_search(monkeypatch: pytest.MonkeyPatch) -> None:
    def embedded(text: str) -> list[float]:
        raise AssertionError("small talk and overviews must not embed a query")

    monkeypatch.setattr(provider, "embed_query", embedded)


# -- small talk ---------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "hi",
        "Hello!",
        "hey there",
        "Good morning",
        "thanks",
        "Thank you so much!",
        "ok",
        "echo hello",
        "test",
        "testing 123",
        "what can you do?",
        "how are you",
        "who are you?",
        "help",
    ],
)
def test_small_talk_is_recognised(message: str) -> None:
    assert classify_intent(message) is Intent.CHAT


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("What is an echo chamber?", Intent.ANSWER),
        ("hi, what is linearity?", Intent.ANSWER),
        ("test me on chapter 1", Intent.QUIZ),
        ("help me understand eigenvalues", Intent.ANSWER),
        ("thanks, now make a table of the theorems", Intent.ANSWER),
        ("make me a study guide", Intent.DOCUMENT),
        ("and a quiz on that", Intent.QUIZ),
        ("now make a table comparing bases", Intent.SHEET),
    ],
)
def test_a_real_request_is_never_mistaken_for_small_talk(
    message: str, intent: Intent
) -> None:
    assert classify_intent(message) is intent


def test_small_talk_gets_a_reply_from_the_model_without_any_search(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "echo hello" in a course with nothing in it was refused as "nothing
    relevant found"; and "hi" in a full one was answered from random
    passages."""
    _no_search(monkeypatch)
    course_id = client.post("/courses", json={"name": "Empty"}).json()["course_id"]
    calls = configure_test_provider(monkeypatch, HELLO)
    chat_id = _chat(client, course_id)

    turn = _send(client, course_id, chat_id, "echo hello")
    assert turn.status_code == 200, turn.text
    reply = turn.json()["reply"]
    assert reply["no_match"] is False
    assert reply["text"] == HELLO
    assert reply["answer"]["chunk_ids"] == [] and reply["answer"]["trace_id"] == ""
    assert len(calls) == 1
    prompt = str(calls[0]["prompt"])
    assert "Student message: echo hello" in prompt
    assert "Course material" not in prompt, "nothing to look up, nothing to cite"
    assert "Empty" in prompt, "the model knows which course this is"

    opened = client.get(f"/courses/{course_id}/conversations/{chat_id}").json()
    assert [m["role"] for m in opened["messages"]] == ["user", "assistant"]
    assert opened["messages"][1]["text"] == HELLO


def test_small_talk_in_a_full_course_is_not_answered_from_its_passages(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_search(monkeypatch)
    course_id = _course(client, "linearity means preserving addition and scaling.")
    calls = configure_test_provider(monkeypatch, HELLO)
    chat_id = _chat(client, course_id)
    reply = _send(client, course_id, chat_id, "hi").json()["reply"]
    assert reply["answer"]["chunk_ids"] == []
    assert "preserving addition" not in str(calls[0]["prompt"])


def test_small_talk_says_nothing_about_the_topic_of_the_next_question() -> None:
    def message(seq: int, role: str, text: str) -> Message:
        return Message(
            message_id=uuid4(),
            conversation_id=uuid4(),
            seq=seq,
            role=role,
            text=text,
            trace_id=None,
            created_at=datetime.now(UTC),
        )

    history = [
        message(1, "user", "What is a basis?"),
        message(2, "assistant", "A basis spans the space."),
        message(3, "user", "thanks!"),
        message(4, "assistant", "You're welcome."),
    ]
    conversation = Conversation(
        conversation_id=uuid4(),
        course_id=uuid4(),
        title="",
        model_choice=None,
        source_ids=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        message_count=4,
    )
    context = chat.context_for(conversation, history)
    assert context.previous_questions == ("What is a basis?",)
    assert chat.retrieval_query("and its dimension?", context) == (
        "and its dimension?\nWhat is a basis?"
    )


def test_compose_chat_prompt_carries_the_conversation_but_no_material() -> None:
    prompts: list[str] = []

    def generate(task: str, prompt: str, *, response_schema: Any = None) -> str:
        prompts.append(prompt)
        return HELLO

    text = compose_chat(
        "thanks", generate, conversation="Student: what is a basis?", course_name="LA"
    )
    assert text == HELLO
    assert "Student: what is a basis?" in prompts[0]
    assert "Student message: thanks" in prompts[0]
    assert "UNTRUSTED_COURSE_MATERIAL begin" in prompts[0], "the message is data"


# -- requests about the whole course ------------------------------------


def test_request_words_are_not_what_is_searched_for() -> None:
    assert retrieval_topic("make me a study guide on Weber") == "Weber"
    assert retrieval_topic("quiz me on the CPI") == "CPI"
    assert retrieval_topic("make me a study guide") == ""
    assert retrieval_topic("What is the CPI?") == "What is the CPI?"
    assert chat.retrieval_query("make me a study guide on Weber", None) == "Weber"


def test_a_request_without_a_subject_takes_the_subject_of_the_chat() -> None:
    context = chat.ChatContext(
        summary="", recent=(), previous_questions=("What is a basis?",)
    )
    assert chat.retrieval_query("quiz me on that", context) == "What is a basis?"
    assert chat.wants_overview("quiz me on that", context) is False
    assert chat.wants_overview("quiz me on that", None) is True
    assert chat.wants_overview("quiz me on the CPI", None) is False
    assert chat.wants_overview("What is the CPI?", None) is False


@pytest.mark.parametrize(
    "question",
    [
        "what is this course about?",
        "What's the course about",
        "what does this course cover?",
        "what topics are covered?",
        "summarize the whole course",
        "give me an overview of the material",
    ],
)
def test_questions_about_the_course_as_a_whole(question: str) -> None:
    assert asks_for_overview(question)


def test_what_is_this_course_about_reads_a_spread_of_every_source(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Searching for the words "course about" found whichever passage sat
    nearest to them; the answer must see each source."""
    _no_search(monkeypatch)
    course_id = _course(
        client,
        "alpha source: vectors and spans.",
        "beta source: matrices and maps.",
        "gamma source: eigenvalues.",
    )
    calls = configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)
    turn = _send(client, course_id, chat_id, "what is this course about?")
    assert turn.status_code == 200, turn.text
    prompt = str(calls[0]["prompt"])
    assert all(name in prompt for name in ("alpha source", "beta source", "gamma"))
    answer = turn.json()["reply"]["answer"]
    assert len(answer["chunk_ids"]) == 3 and answer["trace_id"]
    citations = client.get(
        f"/courses/{course_id}/traces/{answer['trace_id']}/citations"
    ).json()
    assert len(citations) == 3


def test_a_study_guide_with_no_subject_is_built_from_the_whole_course(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_search(monkeypatch)
    course_id = _course(client, "alpha source: vectors.", "beta source: matrices.")
    item = {
        "type": "document",
        "title": "Guide",
        "content": "# Guide\n- vectors [1]\n- matrices [2]",
        "sources": [1, 2],
    }
    calls = configure_test_provider(
        monkeypatch, json.dumps({"reply": "Here it is.", "item": item})
    )
    chat_id = _chat(client, course_id)
    turn = _send(client, course_id, chat_id, "make me a study guide")
    assert turn.status_code == 200, turn.text
    prompt = str(calls[0]["prompt"])
    assert "alpha source" in prompt and "beta source" in prompt
    workspace = turn.json()["reply"]["answer"]["workspace"]
    assert [w["type"] for w in workspace] == ["document"]


def test_the_overview_of_a_narrowed_chat_stays_inside_its_sources(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client, "alpha source: vectors.", "beta source: matrices.")
    from src.backend.common import sources_repo

    keep = sources_repo.list_sources(UUID(course_id))[0]
    kept_text = "alpha" if "alpha" in _chunk_text(keep.source_id) else "beta"
    calls = configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)
    client.patch(
        f"/courses/{course_id}/conversations/{chat_id}",
        json={"source_ids": [str(keep.source_id)]},
    )
    _send(client, course_id, chat_id, "what is this course about?")
    prompt = str(calls[0]["prompt"])
    other = "beta" if kept_text == "alpha" else "alpha"
    assert f"{kept_text} source" in prompt and f"{other} source" not in prompt


def _chunk_text(source_id: UUID) -> str:
    from src.backend.common.db import connection

    with connection() as conn:
        row = conn.execute(
            "SELECT text FROM chunks WHERE source_id = ?", (source_id,)
        ).fetchone()
    return str(row["text"])


# -- failures a second try fixes ----------------------------------------


def test_an_empty_model_reply_is_tried_once_more(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client, "linearity means preserving addition and scaling.")
    configure_test_provider(monkeypatch, ANSWER)
    replies = iter(["", ANSWER])
    prompts: list[str] = []

    def flaky(task, endpoint, prompt, *, images=None, response_schema=None):
        prompts.append(prompt)
        return next(replies), 10, 5

    monkeypatch.setattr(provider, "_call_provider", flaky)
    chat_id = _chat(client, course_id)
    turn = _send(client, course_id, chat_id, "What is linearity?")
    assert turn.status_code == 200, turn.text
    assert turn.json()["reply"]["text"] == ANSWER
    assert len(prompts) == 2 and prompts[0] == prompts[1]


def test_two_empty_replies_in_a_row_still_fail_and_record_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client, "linearity means preserving addition and scaling.")
    configure_test_provider(monkeypatch, "")
    chat_id = _chat(client, course_id)
    turn = _send(client, course_id, chat_id, "What is linearity?")
    assert turn.status_code == 503
    assert "no usable answer" in turn.json()["detail"]
    opened = client.get(f"/courses/{course_id}/conversations/{chat_id}").json()
    assert opened["messages"] == [], "so the same question can simply be sent again"


def test_an_answer_cut_off_at_the_output_limit_is_asked_for_again_briefly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client, "linearity means preserving addition and scaling.")
    configure_test_provider(monkeypatch, ANSWER)
    prompts: list[str] = []

    def cut_off(task, endpoint, prompt, *, images=None, response_schema=None):
        prompts.append(prompt)
        if len(prompts) == 1:
            raise provider.ModelOutputTruncatedError("cut off")
        return ANSWER, 10, 5

    monkeypatch.setattr(provider, "_call_provider", cut_off)
    chat_id = _chat(client, course_id)
    turn = _send(client, course_id, chat_id, "What is linearity?")
    assert turn.status_code == 200, turn.text
    assert "much more briefly" in prompts[1] and "much more briefly" not in prompts[0]


def test_a_missing_embedding_model_degrades_to_keyword_search(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first question of a session loads the embedding model; if that
    fails, the tutor must still answer from what keywords find."""
    course_id = _course(client, "linearity means preserving addition and scaling.")
    calls = configure_test_provider(monkeypatch, ANSWER)

    def unavailable(text: str) -> list[float]:
        raise provider.ProviderUnavailableError("embedding model unavailable")

    monkeypatch.setattr(provider, "embed_query", unavailable)
    chat_id = _chat(client, course_id)
    turn = _send(client, course_id, chat_id, "What is linearity?")
    assert turn.status_code == 200, turn.text
    assert "preserving addition" in str(calls[0]["prompt"])


def test_a_blank_question_is_refused_before_anything_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = _course(client, "linearity means preserving addition and scaling.")
    calls = configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)
    assert _send(client, course_id, chat_id, "   \n ").status_code == 422
    assert (
        client.post(f"/courses/{course_id}/ask", json={"question": "  "}).status_code
        == 422
    )
    assert calls == []


# -- what the model is told about the chat -------------------------------


def test_the_chat_summary_is_written_by_the_chats_own_model(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    _memory_keyring: dict[str, str],
) -> None:
    """A chat pinned to a private model must not have its conversation sent
    to whatever provider Settings points at."""
    course_id = _course(client, "linearity means preserving addition and scaling.")
    calls = configure_test_provider(monkeypatch, ANSWER)
    local = providers.add_connection("ollama", name="Mine")
    chat_id = _chat(client, course_id)
    client.patch(
        f"/courses/{course_id}/conversations/{chat_id}",
        json={"model_choice": {"connection": local.id, "model": "llama-test"}},
    )
    for question in ("What is linearity?", "Why?", "An example?"):
        assert _send(client, course_id, chat_id, question).status_code == 200
    summaries = [c for c in calls if c["task"] == "conversation_summary"]
    assert len(summaries) == 1
    endpoint = summaries[0]["endpoint"]
    assert (endpoint.connection, endpoint.model) == (local.id, "llama-test")


def test_a_follow_up_can_refer_to_a_quiz_shown_beside_the_chat() -> None:
    quiz = {
        "type": "quiz",
        "title": "Bases",
        "questions": [
            {
                "prompt": "What does a basis do?",
                "options": ["Spans the space", "Nothing"],
                "answer": 0,
                "sources": [1],
            }
        ],
    }
    reply = Message(
        message_id=uuid4(),
        conversation_id=uuid4(),
        seq=2,
        role="assistant",
        text="Here you go.",
        trace_id=None,
        created_at=datetime.now(UTC),
        payload={"workspace": [quiz]},
    )
    conversation = Conversation(
        conversation_id=uuid4(),
        course_id=uuid4(),
        title="",
        model_choice=None,
        source_ids=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        message_count=2,
    )
    rendered = chat.context_for(conversation, [reply]).render()
    assert 'quiz "Bases"' in rendered
    assert "1. What does a basis do? (answer: Spans the space)" in rendered


def test_the_ask_endpoint_answers_small_talk_too(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_search(monkeypatch)
    course_id = client.post("/courses", json={"name": "Empty"}).json()["course_id"]
    configure_test_provider(monkeypatch, HELLO)
    answer = client.post(f"/courses/{course_id}/ask", json={"question": "hi"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["text"] == HELLO and answer.json()["trace_id"] == ""


# -- searching ------------------------------------------------------------


def test_words_with_accents_are_searched_whole() -> None:
    """ "sociología" was cut into "sociolog" + "a" and "Émile" into "mile":
    tokens that match nothing the (diacritic-folding) index holds."""
    from src.backend.retrieval.funnel import _keyword_tokens

    assert "sociología" in _keyword_tokens("¿Qué es la sociología?")
    assert _keyword_tokens("Émile Durkheim") == ["émile", "durkheim"]
    assert _keyword_tokens("Café f(x) = x^2") == ["café"]
    assert _keyword_tokens("什么是社会学") == ["什么是社会学"]


def test_a_question_with_accents_finds_its_passage(client: TestClient) -> None:
    from src.backend.common.db import connection
    from src.backend.retrieval import funnel

    course_id = UUID(client.post("/courses", json={"name": "Soc"}).json()["course_id"])
    add_chunk(course_id, "Émile Durkheim studied suicide and social solidarity.")
    add_chunk(course_id, "Unrelated passage about bases.")
    with connection() as conn:
        found = funnel.keyword_seam(conn, course_id, "Who was Emile Durkheim?", 10)
        accented = funnel.keyword_seam(conn, course_id, "Who was Émile Durkheim?", 10)
    assert len(found) == 1 and len(accented) == 1


def test_an_overview_falls_back_to_searching_when_nothing_is_embedded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = client.post("/courses", json={"name": "LA"}).json()["course_id"]
    add_chunk(UUID(course_id), "linearity means preserving addition and scaling.")
    calls = configure_test_provider(monkeypatch, ANSWER)
    chat_id = _chat(client, course_id)
    turn = _send(client, course_id, chat_id, "what is this course about linearity?")
    assert turn.status_code == 200, turn.text
    assert turn.json()["reply"]["no_match"] is False
    assert "preserving addition" in str(calls[0]["prompt"])
