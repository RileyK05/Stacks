"""Saved chats (docs/plan-notebook.md §4.2): unlimited conversations per
course, each with its own model pick and source selection.

Sending a message answers it exactly like the one-off ask endpoint —
grounded, cited, gated — with the chat's context (tutor/chat.py) and
records both halves of the turn. "Nothing relevant in the material" is a
real outcome of the conversation and is recorded as the reply; a provider
that is down (503) or a reached budget (402) is not, so the question can
simply be sent again.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from src.backend.api.tutor import AnswerView, answer_view
from src.backend.common import (
    conversations_repo,
    courses_repo,
    provider,
    providers,
    sources_repo,
    usage_repo,
)
from src.backend.common.conversations_repo import Conversation, Message
from src.backend.common.db import connection
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.tutor import answer as tutor_answer
from src.backend.tutor import chat

router = APIRouter(prefix="/courses/{course_id}/conversations", tags=["conversations"])


class ModelChoiceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection: str = Field(min_length=1, max_length=providers.CONNECTION_ID_MAX)
    model: str | None = Field(default=None, max_length=200)


class ConversationSummaryView(BaseModel):
    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    model_choice: ModelChoiceView | None
    # None: every source in the course.
    source_ids: list[str] | None


class MessageView(BaseModel):
    message_id: str
    seq: int
    role: str
    text: str
    created_at: datetime
    # The assistant's answer as the ask endpoint returns it (citations,
    # workspace items, model...). None for the student's messages and for
    # a "nothing relevant found" reply.
    answer: AnswerView | None = None
    no_match: bool = False


class ConversationView(ConversationSummaryView):
    messages: list[MessageView]


class TurnView(BaseModel):
    conversation: ConversationSummaryView
    question: MessageView
    reply: MessageView


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=conversations_repo.TITLE_MAX_LENGTH)


class ConversationUpdate(BaseModel):
    """Only the fields sent are changed; `model_choice: null` returns the
    chat to Settings' model, `source_ids: null` to every source."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None, max_length=conversations_repo.TITLE_MAX_LENGTH
    )
    model_choice: ModelChoiceView | None = None
    source_ids: list[UUID] | None = Field(default=None, max_length=1000)


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    bigger_model: bool = False


def _summary_view(conversation: Conversation) -> ConversationSummaryView:
    return ConversationSummaryView(
        conversation_id=str(conversation.conversation_id),
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=conversation.message_count,
        model_choice=(
            ModelChoiceView.model_validate(conversation.model_choice)
            if conversation.model_choice
            else None
        ),
        source_ids=(
            [str(value) for value in conversation.source_ids]
            if conversation.source_ids is not None
            else None
        ),
    )


def _message_view(message: Message) -> MessageView:
    payload = message.payload
    answer = None
    if message.role == "assistant" and not payload.get("no_match"):
        answer = AnswerView.model_validate({**payload, "text": message.text})
    return MessageView(
        message_id=str(message.message_id),
        seq=message.seq,
        role=message.role,
        text=message.text,
        created_at=message.created_at,
        answer=answer,
        no_match=bool(payload.get("no_match")),
    )


def _require_course(course_id: UUID) -> None:
    if courses_repo.get_course(course_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")


def _require_conversation(course_id: UUID, conversation_id: UUID) -> Conversation:
    _require_course(course_id)
    conversation = conversations_repo.get_conversation(course_id, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return conversation


@router.get("", response_model=list[ConversationSummaryView])
def list_conversations(course_id: UUID) -> list[ConversationSummaryView]:
    _require_course(course_id)
    return [_summary_view(c) for c in conversations_repo.list_conversations(course_id)]


@router.post(
    "", response_model=ConversationSummaryView, status_code=status.HTTP_201_CREATED
)
def create_conversation(
    course_id: UUID, payload: ConversationCreate
) -> ConversationSummaryView:
    _require_course(course_id)
    return _summary_view(conversations_repo.create(course_id, payload.title))


@router.get("/{conversation_id}", response_model=ConversationView)
def get_conversation(course_id: UUID, conversation_id: UUID) -> ConversationView:
    conversation = _require_conversation(course_id, conversation_id)
    with connection() as conn:
        history = conversations_repo.messages(conn, conversation_id)
    return ConversationView(
        **_summary_view(conversation).model_dump(),
        messages=[_message_view(m) for m in history],
    )


@router.patch("/{conversation_id}", response_model=ConversationSummaryView)
def update_conversation(
    course_id: UUID, conversation_id: UUID, payload: ConversationUpdate
) -> ConversationSummaryView:
    current = _require_conversation(course_id, conversation_id)
    sent = payload.model_fields_set
    model_choice = current.model_choice
    if "model_choice" in sent:
        model_choice = None
        if payload.model_choice is not None:
            if providers.get_connection(payload.model_choice.connection) is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown connection"
                )
            model_choice = payload.model_choice.model_dump(exclude_none=True)
    source_ids = current.source_ids
    if "source_ids" in sent:
        source_ids = None
        if payload.source_ids is not None:
            if not payload.source_ids:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "choose at least one source",
                )
            known = {s.source_id for s in sources_repo.list_sources(course_id)}
            if not set(payload.source_ids) <= known:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "a chosen source is not in this course",
                )
            source_ids = tuple(dict.fromkeys(payload.source_ids))
    updated = conversations_repo.update(
        course_id,
        conversation_id,
        title=payload.title if payload.title is not None else current.title,
        model_choice=model_choice,
        source_ids=source_ids,
    )
    assert updated is not None
    return _summary_view(updated)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(course_id: UUID, conversation_id: UUID) -> None:
    _require_course(course_id)
    if not conversations_repo.delete(course_id, conversation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")


@router.post("/{conversation_id}/messages", response_model=TurnView)
def send_message(
    course_id: UUID,
    conversation_id: UUID,
    payload: SendMessage,
    background: BackgroundTasks,
) -> TurnView:
    conversation = _require_conversation(course_id, conversation_id)
    with connection() as conn:
        history = conversations_repo.messages(conn, conversation_id)
    context = chat.context_for(conversation, history)
    search = chat.retrieval_query(payload.question, context)
    choice = (
        providers.ProviderChoice.model_validate(conversation.model_choice)
        if conversation.model_choice
        else None
    )
    try:
        # Embed before opening the connection: no database needed for it.
        query_embedding = provider.embed_query(search)
        with connection() as conn:
            try:
                result = tutor_answer.answer_question(
                    conn,
                    course_id,
                    payload.question,
                    load_retrieval_policy(),
                    query_embedding=query_embedding,
                    embedding_model=load_embedding_policy().model,
                    bigger=payload.bigger_model,
                    choice=choice,
                    conversation=context.render(),
                    source_ids=conversation.source_ids,
                    search_query=search,
                )
            except tutor_answer.NothingRelevantFoundError as err:
                asked, replied = conversations_repo.add_turn(
                    conn,
                    conversation_id,
                    question=payload.question,
                    answer=str(err),
                    trace_id=None,
                    payload={"no_match": True},
                )
            else:
                view = answer_view(result, bigger=payload.bigger_model)
                asked, replied = conversations_repo.add_turn(
                    conn,
                    conversation_id,
                    question=payload.question,
                    answer=view.text,
                    trace_id=result.trace_id,
                    payload=view.model_dump(mode="json", exclude={"text"}),
                )
            conn.commit()
            history = conversations_repo.messages(conn, conversation_id)
            updated = conversations_repo.load(conn, course_id, conversation_id)
    except provider.ProviderUnavailableError as err:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(err)) from err
    except usage_repo.BudgetExceededError as err:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(err)) from err
    assert updated is not None
    pending = chat.pending_summary(updated, history)
    if pending is not None:
        background.add_task(chat.summarize, course_id, conversation_id, pending)
    return TurnView(
        conversation=_summary_view(updated),
        question=_message_view(asked),
        reply=_message_view(replied),
    )
