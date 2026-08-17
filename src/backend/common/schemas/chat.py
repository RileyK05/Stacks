from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field
from src.backend.common.schemas.base import BaseRecord, _new_id, _now


class Conversation(BaseRecord):
    """A chat session with the tutor, stored in two forms for two audiences."""

    conversation_id: UUID = Field(default_factory=_new_id)
    user_id: UUID
    course_id: UUID
    title: str
    created_at: datetime = Field(default_factory=_now)


class ConversationTurn(BaseRecord):
    """One message in a conversation. `role` is 'user' or 'assistant'."""

    turn_id: UUID = Field(default_factory=_new_id)
    conversation_id: UUID
    role: str
    content: str
    created_at: datetime = Field(default_factory=_now)


class ChatSummary(BaseRecord):
    """A compressed summary of the conversation for LLM context.

    Regenerated when the conversation grows past the compress threshold, so the
    model always prompts against current context.
    """

    summary_id: UUID = Field(default_factory=_new_id)
    conversation_id: UUID
    summary: str
    version: int
    created_at: datetime = Field(default_factory=_now)
