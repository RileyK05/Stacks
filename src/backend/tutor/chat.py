"""What a saved chat hands the model (docs/plan-notebook.md §4.2).

A small model has little context to spare, so a chat is not replayed in
full: the model reads a rolling summary of the earlier turns plus the most
recent exchanges. Both sit inside the fenced material with the course
text — they are context, not instructions, and they are never a source:
answers still cite only the numbered course material.

Follow-ups ("what about the second one?") carry little to search on, so a
short question is searched together with the two before it — two, so a
chain of follow-ups ("why?", "an example?") keeps the topic that started
it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from src.backend.common import conversations_repo, provider
from src.backend.common.conversations_repo import Conversation, Message
from src.backend.common.prompt_registry import grounded_prompt, load_prompt

logger = logging.getLogger(__name__)

# The last two exchanges are shown verbatim; everything before them lives
# in the rolling summary.
RECENT_MESSAGES = 4
# How much of an earlier answer the model re-reads. Answers can be long;
# the gist is enough to resolve "it" and "the second one".
EXCERPT_CHARS = 600
# A question this short is probably a follow-up and is searched together
# with the previous questions.
FOLLOW_UP_MAX_WORDS = 12
FOLLOW_UP_LOOKBACK = 2
SUMMARY_MAX_CHARS = 1200

_CITATIONS = re.compile(r"\s*\[\d+(?:\s*[,–-]\s*\d+)*\]")


@dataclass(frozen=True)
class ChatContext:
    summary: str
    recent: tuple[tuple[str, str], ...]
    # The student's latest questions, newest first.
    previous_questions: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.summary and not self.recent

    def render(self) -> str:
        """The conversation block that precedes the question in the
        prompt. Old citation numbers are dropped: they pointed at a
        different numbered list than the one the model reads now."""
        parts: list[str] = []
        if self.summary:
            parts.append(f"Summary of the earlier conversation:\n{self.summary}")
        if self.recent:
            lines = [f"{_speaker(role)}: {text}" for role, text in self.recent]
            parts.append("Most recent turns:\n" + "\n".join(lines))
        return "\n\n".join(parts)


def _speaker(role: str) -> str:
    return "Student" if role == "user" else "Tutor"


def _excerpt(text: str) -> str:
    plain = " ".join(_CITATIONS.sub("", text).split())
    if len(plain) <= EXCERPT_CHARS:
        return plain
    return plain[: EXCERPT_CHARS - 1].rsplit(" ", 1)[0] + "…"


def context_for(conversation: Conversation, history: Sequence[Message]) -> ChatContext:
    recent = history[-RECENT_MESSAGES:]
    asked = [m.text for m in reversed(history) if m.role == "user"]
    return ChatContext(
        summary=conversation.summary,
        recent=tuple((m.role, _excerpt(m.text)) for m in recent),
        previous_questions=tuple(asked[:FOLLOW_UP_LOOKBACK]),
    )


def retrieval_query(question: str, context: ChatContext | None) -> str:
    if context is None or not context.previous_questions:
        return question
    if len(question.split()) > FOLLOW_UP_MAX_WORDS:
        return question
    return "\n".join((question, *context.previous_questions))


@dataclass(frozen=True)
class PendingSummary:
    previous: str
    transcript: str
    through: int


def pending_summary(
    conversation: Conversation, history: Sequence[Message]
) -> PendingSummary | None:
    """The turns that have scrolled out of the recent window but are not in
    the summary yet, once there is at least one full exchange of them."""
    older = [
        m for m in history[:-RECENT_MESSAGES] if m.seq > conversation.summary_through
    ]
    if len(older) < 2:
        return None
    transcript = "\n".join(f"{_speaker(m.role)}: {_excerpt(m.text)}" for m in older)
    return PendingSummary(
        previous=conversation.summary, transcript=transcript, through=older[-1].seq
    )


def summarize(course_id: UUID, conversation_id: UUID, pending: PendingSummary) -> None:
    """Fold the pending turns into the rolling summary. Runs after the
    answer is returned; a failure only means the next turn tries again."""
    material = (
        f"Current summary:\n{pending.previous or '(none yet)'}\n\n"
        f"New turns:\n{pending.transcript}"
    )
    try:
        result = provider.generate(
            "conversation_summary",
            grounded_prompt(load_prompt("conversation_summary"), material),
            course_id=course_id,
        )
    except Exception:  # noqa: BLE001 - best effort; retried next turn
        logger.warning("conversation summary failed", exc_info=True)
        return
    summary = " ".join(result.text.split())[:SUMMARY_MAX_CHARS]
    if summary:
        conversations_repo.set_summary(conversation_id, summary, pending.through)
