"""What a saved chat hands the model.

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
from src.backend.common.providers import ProviderChoice
from src.backend.tutor.compose import (
    Intent,
    asks_for_overview,
    classify_intent,
    retrieval_topic,
)

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

_CITATIONS = re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]")


@dataclass(frozen=True)
class ChatContext:
    summary: str
    recent: tuple[tuple[str, str], ...]
    # The student's latest questions, newest first.
    previous_questions: tuple[str, ...] = ()
    # True when the source selection changed within this chat, so earlier
    # turns may cite facts from a source no longer selected.
    scope_revised: bool = False
    teaching_trace_ids: tuple[UUID, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.summary and not self.recent

    def render(self) -> str:
        """The conversation block that precedes the question, fenced as
        data with the course text. Old citation numbers are dropped: they
        pointed at a different numbered list than the one the model reads
        now."""
        parts: list[str] = []
        if self.summary:
            parts.append(f"Summary of the earlier conversation:\n{self.summary}")
        if self.recent:
            lines = [f"{_speaker(role)}: {text}" for role, text in self.recent]
            parts.append("Most recent turns:\n" + "\n".join(lines))
        return "\n\n".join(parts)

    def scope_note(self) -> str:
        """Trusted instruction text appended after a source-scope change
        (B-02). It must not sit inside the data fence, where the model is
        told to ignore directions."""
        if not self.scope_revised:
            return ""
        return load_prompt("conversation_scope_change")


def _speaker(role: str) -> str:
    return "Student" if role == "user" else "Tutor"


def _excerpt(text: str) -> str:
    plain = " ".join(_CITATIONS.sub("", text).split())
    plain = re.sub(r"\s+([.,!?;:])", r"\1", plain)
    if len(plain) <= EXCERPT_CHARS:
        return plain
    prefix = plain[: EXCERPT_CHARS - 1]
    return (prefix.rsplit(" ", 1)[0] if " " in prefix else prefix) + "…"


def _turn_text(message: Message) -> str:
    """What a turn contributes to the context: its text, plus what the tutor
    put in the workspace beside it. A quiz's questions are not in the chat
    text, so without them "explain question 2" would have nothing to explain."""
    text = _excerpt(message.text)
    items = message.payload.get("workspace") if message.role == "assistant" else None
    notes: list[str] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        note = f"{item.get('type', 'item')}" + (f' "{title}"' if title else "")
        questions = item.get("questions")
        if isinstance(questions, list):
            listed = []
            for number, question in enumerate(questions[:6], start=1):
                if not isinstance(question, dict):
                    continue
                options = question.get("options") or []
                answer = question.get("answer")
                key = (
                    options[answer]
                    if isinstance(answer, int) and 0 <= answer < len(options)
                    else "?"
                )
                listed.append(f"{number}. {question.get('prompt', '')} (answer: {key})")
            if listed:
                note += ": " + " ".join(listed)
        notes.append(_excerpt(note))
    if notes:
        text += " [Shown in the workspace: " + "; ".join(notes) + "]"
    return text


def context_for(conversation: Conversation, history: Sequence[Message]) -> ChatContext:
    recent = history[-RECENT_MESSAGES:]
    # Small talk ("hi", "thanks") says nothing about the topic to search for.
    asked = [
        m.text
        for m in reversed(history)
        if m.role == "user" and classify_intent(m.text) is not Intent.CHAT
    ]
    # A scope revision at seq 0 means the selection changed before any
    # turn was recorded, so there is nothing earlier to distrust. Any
    # other revision has earlier turns that may cite an excluded source.
    scope_revised = bool(conversation.scope_revised_seq) and any(
        m.seq <= conversation.scope_revised_seq for m in history
    )
    return ChatContext(
        summary=conversation.summary,
        recent=tuple((m.role, _turn_text(m)) for m in recent),
        previous_questions=tuple(asked[:FOLLOW_UP_LOOKBACK]),
        scope_revised=scope_revised,
        teaching_trace_ids=tuple(
            m.trace_id
            for m in history
            if m.role == "assistant" and m.trace_id is not None
        ),
    )


def retrieval_query(question: str, context: ChatContext | None) -> str:
    """What to search the course for. A request for a quiz or study guide is
    searched by its subject alone; one that names none ("quiz me on that")
    takes the subject of the chat so far."""
    previous = context.previous_questions if context is not None else ()
    if asks_for_overview(question):
        return question
    topic = retrieval_topic(question)
    if not topic.strip():
        return "\n".join(previous) if previous else question
    if not previous or len(topic.split()) > FOLLOW_UP_MAX_WORDS:
        return topic
    return "\n".join((topic, *previous))


def wants_overview(question: str, context: ChatContext | None) -> bool:
    """Whether the question is about the course as a whole: asked so ("what
    is this course about?"), or a request for a quiz, study guide... that
    names no subject in a chat that has none yet."""
    if asks_for_overview(question):
        return True
    if classify_intent(question) in (Intent.ANSWER, Intent.GRADED, Intent.CHAT):
        return False
    previous = context.previous_questions if context is not None else ()
    return not retrieval_topic(question).strip() and not previous


@dataclass(frozen=True)
class PendingSummary:
    previous: str
    transcript: str
    through: int
    # True when this folds turns from before a source-scope change: the
    # summary must keep the topic but drop the facts (B-02).
    scope_changed: bool = False


def pending_summary(
    conversation: Conversation, history: Sequence[Message]
) -> PendingSummary | None:
    """The turns that have scrolled out of the recent window but are not in
    the summary yet, once there is at least one full exchange of them.

    If the source selection changed after those turns and they are not
    summarized yet, they are summarized first and only — a topic-only
    summary (B-02) — so the model never re-asserts a fact from a source
    the student has since excluded."""
    older = [
        m for m in history[:-RECENT_MESSAGES] if m.seq > conversation.summary_through
    ]
    scope_changed = False
    revised = conversation.scope_revised_seq
    if revised and conversation.summary_through < revised:
        # Fold only the pre-change turns, and stop the summary there so
        # the post-change turns are summarized against current material.
        older = [m for m in older if m.seq <= revised]
        scope_changed = True
    if not older:
        return None
    transcript = "\n".join(f"{_speaker(m.role)}: {_turn_text(m)}" for m in older)
    return PendingSummary(
        previous=conversation.summary,
        transcript=transcript,
        through=older[-1].seq,
        scope_changed=scope_changed,
    )


def summarize(
    course_id: UUID,
    conversation_id: UUID,
    pending: PendingSummary,
    choice: ProviderChoice | None = None,
) -> None:
    """Fold the pending turns into the rolling summary. Runs after the
    answer is returned; a failure only means the next turn tries again. The
    chat's own model does it: the conversation never goes to a provider the
    student did not pick for this chat."""
    material = (
        f"Current summary:\n{pending.previous or '(none yet)'}\n\n"
        f"New turns:\n{pending.transcript}"
    )
    instruction = (
        "scope_change_summary" if pending.scope_changed else "conversation_summary"
    )
    try:
        result = provider.generate(
            "conversation_summary",
            grounded_prompt(load_prompt(instruction), material),
            course_id=course_id,
            choice=choice,
        )
    except Exception:  # noqa: BLE001 - best effort; retried next turn
        logger.warning("conversation summary failed", exc_info=True)
        return
    summary = " ".join(result.text.split())
    if len(summary) > SUMMARY_MAX_CHARS:
        prefix = summary[: SUMMARY_MAX_CHARS - 1]
        summary = (prefix.rsplit(" ", 1)[0] if " " in prefix else prefix) + "…"
    if summary:
        conversations_repo.set_summary(conversation_id, summary, pending.through)
