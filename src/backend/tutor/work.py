"""Document assistance: working material is never learning evidence or knowledge."""

from __future__ import annotations

import dataclasses
import json
import re
from uuid import UUID

from src.backend.common import provider, work_repo
from src.backend.common.companion_config import load_companion_policy
from src.backend.common.db import connection
from src.backend.common.prompt_registry import (
    grounded_prompt,
    load_prompt,
    strip_fence_echo,
)
from src.backend.common.schemas.work import (
    ContextCoverage,
    DocumentReview,
    ProposedEdit,
    WorkAsk,
    WorkCitation,
    WorkReply,
    WorkSession,
)
from src.backend.retrieval import funnel, rerank, trace
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.student_model import learning
from src.backend.tutor import answer as tutor_answer
from src.backend.tutor.compose import parse_json_object
from src.backend.tutor.office import NotAllowedError, _citations, is_graded_request


def document_context(text: str, query: str) -> tuple[str, ContextCoverage]:
    policy = load_companion_policy()
    sections = [
        text[i : i + policy.section_chars]
        for i in range(0, len(text), policy.section_chars)
    ]
    words = set(re.findall(r"\w{3,}", query.casefold()))
    if len(text) <= policy.document_context_chars:
        chosen = list(range(len(sections)))
    else:
        ranked = sorted(
            range(len(sections)),
            key=lambda i: (
                -len(words & set(re.findall(r"\w{3,}", sections[i].casefold()))),
                i,
            ),
        )
        chosen = sorted(
            ranked[
                : max(1, policy.document_context_chars // (policy.section_chars + 40))
            ]
        )
    content = "\n\n".join(f"[D{i + 1}] {sections[i]}" for i in chosen)
    coverage = ContextCoverage(
        total_sections=len(sections),
        included_sections=[i + 1 for i in chosen],
        complete=len(chosen) == len(sections),
    )
    return content, coverage


def _history(work: WorkSession) -> list[dict[str, str]]:
    budget = load_companion_policy().history_context_chars
    result: list[dict[str, str]] = []
    for turn in reversed(work.turns):
        text = turn.reply.text
        instruction = turn.instruction or turn.action
        if len(text) + len(instruction) > budget:
            break
        result.insert(
            0,
            {
                "request": instruction,
                "reply": text,
                "snapshot": str(turn.document_revision),
            },
        )
        budget -= len(text) + len(instruction)
    return result


def answer(course_id: UUID, session_id: UUID, request: WorkAsk) -> WorkReply:
    with connection() as conn:
        work = work_repo.session(conn, course_id, session_id)
        previous = work_repo.existing_reply(conn, session_id, request)
        if previous:
            return previous
    if work.revision != request.expected_revision:
        raise work_repo.WorkConflictError(
            "The document changed elsewhere. Reload this session before asking."
        )
    if work.document is None:
        raise ValueError("Connect a document first.")
    if request.selection and request.selection not in work.document.text:
        raise ValueError(
            "The selected passage is not in the connected document snapshot."
        )
    if is_graded_request(request.instruction, ""):
        raise NotAllowedError(
            "Stacks can review your reasoning, find references, and suggest "
            "edits to your draft. It cannot write a whole assignment for submission."
        )
    previous_question = work.turns[-1].instruction if work.turns else ""
    query = request.instruction or request.selection or previous_question or work.title
    document, coverage = document_context(work.document.text, query)
    search = f"{query}\n{request.selection or document[:1200]}"
    embedding = tutor_answer.embed_search(search)
    with connection() as conn:
        result = funnel.retrieve(
            conn, course_id, search, load_retrieval_policy(), query_embedding=embedding
        )
        candidates = rerank.select_for_generation(search, result.candidates)
        kept = []
        remaining = load_companion_policy().source_context_chars
        for candidate in candidates:
            if len(candidate.text) > remaining:
                continue
            kept.append(candidate)
            remaining -= len(candidate.text)
        used = dataclasses.replace(result, candidates=tuple(kept))
        citations = [
            WorkCitation(**dataclasses.asdict(c)) for c in _citations(conn, kept)
        ]
        _, behavior, _ = learning.adaptation(
            conn, course_id, query, source_ids=[c.source_id for c in kept]
        )
    proposed_edit = None
    if request.action == "find":
        if not citations:
            raise ValueError(
                "No relevant passages were found in this course. Try a more "
                "specific claim or add a source in the library."
            )
        text = "\n\n".join(
            f"[{c.number}] {c.filename} · {c.label}\n\n{c.text}" for c in citations
        )
        model = "extractive"
    else:
        material = json.dumps(
            {
                "action": request.action,
                "request": request.instruction,
                "purpose": work.purpose,
                "document_title": work.document.title,
                "snapshot_revision": work.revision,
                "capture_coverage": work.document.coverage,
                "capture_warnings": work.document.warnings,
                "document_sections": document,
                "document_context_coverage": coverage.model_dump(),
                "selected_passage": request.selection,
                "recent_conversation": _history(work),
                "course_evidence": [
                    {**c.model_dump(), "citation": f"[{c.number}]"} for c in citations
                ],
            },
            ensure_ascii=False,
        )
        instruction = load_prompt("companion_work") + "\n" + behavior
        response_schema = None
        if request.action == "revise":
            instruction += "\n" + load_prompt("companion_revision")
            response_schema = ProposedEdit.model_json_schema()
        elif request.action == "review":
            instruction += "\n" + load_prompt("companion_review")
            response_schema = DocumentReview.model_json_schema()
        generation = provider.generate(
            "tutor_answer",
            grounded_prompt(instruction, material),
            course_id=course_id,
            response_schema=response_schema,
        )
        text, model = strip_fence_echo(generation.text), generation.model
        cited_text = text
        scope = request.selection or document
        if request.action == "review":
            parsed = parse_json_object(text)
            if parsed is None:
                raise ValueError(
                    "The model did not identify draft passages to review. Try again."
                )
            review = DocumentReview.model_validate(parsed)
            if any(
                not finding.original.strip()
                or not finding.feedback.strip()
                or finding.original not in work.document.text
                or finding.original not in scope
                for finding in review.findings
            ):
                raise ValueError(
                    "The review referred to a passage outside the reviewed draft. "
                    "Try again or select a passage."
                )
            cited_text = "\n".join(f.feedback for f in review.findings)
            text = "\n\n".join(
                f"**Draft passage**\n\n{f.original}\n\n**Feedback**\n\n{f.feedback}"
                for f in review.findings
            )
        if request.action == "revise":
            parsed = parse_json_object(text)
            if parsed is None:
                raise ValueError(
                    "The model did not provide a proposed replacement. Try again."
                )
            proposed_edit = ProposedEdit.model_validate(parsed)
            if (
                not proposed_edit.original.strip()
                or not proposed_edit.replacement.strip()
                or not proposed_edit.explanation.strip()
                or proposed_edit.original not in work.document.text
                or proposed_edit.original not in scope
                or proposed_edit.original.strip() == proposed_edit.replacement.strip()
            ):
                raise ValueError(
                    "The proposed edit did not replace an exact passage from "
                    "the reviewed draft. Try again or select a passage."
                )
            cited_text = proposed_edit.replacement + "\n" + proposed_edit.explanation
            text = (
                f"**Original passage**\n\n{proposed_edit.original}\n\n"
                f"**Proposed replacement**\n\n{proposed_edit.replacement}\n\n"
                f"**Why this edit**\n\n{proposed_edit.explanation}"
            )
        numbers = {int(n) for n in re.findall(r"(?<!D)\[(\d+)\]", cited_text)}
        if (
            not text.strip()
            or not numbers.issubset({c.number for c in citations})
            or (
                citations
                and request.action in {"review", "revise", "explain"}
                and not numbers
            )
        ):
            raise ValueError(
                "The answer contained an unsupported source reference. Try again."
            )
    with connection() as conn:
        stored = trace.record_trace(conn, course_id, search, used)
        reply = WorkReply(
            text=text,
            model=model,
            citations=citations,
            trace_id=str(stored.trace_id),
            coverage=coverage,
            document_revision=work.revision,
            proposed_edit=proposed_edit,
        )
        saved = work_repo.save_reply(conn, course_id, session_id, request, reply)
        conn.commit()
        return saved
