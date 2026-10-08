"""Document assistance: working material is never learning evidence or knowledge."""

from __future__ import annotations

import dataclasses
import json
import re
from uuid import UUID

from src.backend.common import provider, work_repo
from src.backend.common.citations import cited_numbers
from src.backend.common.companion_config import load_companion_policy
from src.backend.common.db import connection
from src.backend.common.prompt_registry import (
    grounded_prompt,
    load_prompt,
    strip_fence_echo,
)
from src.backend.common.queries import get
from src.backend.common.schemas.work import (
    ContextCoverage,
    CritiqueModelOutput,
    CritiqueResult,
    DocumentReview,
    ProposedEdit,
    WorkAsk,
    WorkCitation,
    WorkReply,
    WorkSession,
)
from src.backend.retrieval import funnel, rerank, trace
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.retrieval.labels import attach_passage_context
from src.backend.student_model import learning
from src.backend.tutor import answer as tutor_answer
from src.backend.tutor import critique
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
    if request.action == "critique":
        if work.purpose != "paper":
            raise ValueError("Essay critique is for a paper draft.")
        if critique.refuses_rewrite(request.instruction):
            raise NotAllowedError(
                "The critic comments on your draft. It will not write or "
                "rewrite the essay."
            )
    previous_question = work.turns[-1].instruction if work.turns else ""
    query = request.instruction or request.selection or previous_question or work.title
    if request.action == "critique":
        search = f"{query}\n{request.selection or work.document.text[:1200]}"
    else:
        document, coverage = document_context(work.document.text, query)
        search = f"{query}\n{request.selection or document[:1200]}"
    embedding = tutor_answer.embed_search(search)
    syllabus_in_context = False
    with connection() as conn:
        result = funnel.retrieve(
            conn, course_id, search, load_retrieval_policy(), query_embedding=embedding
        )
        candidates = rerank.select_for_generation(search, result.candidates)
        if request.action == "critique":
            pool = attach_passage_context(conn, result.candidates)
            ranked = attach_passage_context(conn, candidates)
            settings = load_companion_policy()
            kept, syllabus_in_context = critique.reserve_course_evidence(
                ranked,
                pool,
                search,
                source_budget=settings.source_context_chars,
                syllabus_chars=settings.critique.syllabus_chars,
                syllabus_chunks=settings.critique.syllabus_chunks,
            )
            if not syllabus_in_context:
                syllabus_ids = [
                    row["source_id"]
                    for row in conn.execute(
                        get("sources", "syllabus_ids"), {"course_id": course_id}
                    ).fetchall()
                ]
                if syllabus_ids:
                    extra = funnel.retrieve(
                        conn,
                        course_id,
                        work.document.text[:1200],
                        load_retrieval_policy(),
                        query_embedding=embedding,
                        source_ids=syllabus_ids,
                    )
                    extra_ranked = attach_passage_context(
                        conn,
                        rerank.select_for_generation(
                            work.document.text[:1200], extra.candidates
                        ),
                    )
                    kept, syllabus_in_context = critique.reserve_course_evidence(
                        [*ranked, *extra_ranked],
                        [*pool, *extra_ranked],
                        search,
                        source_budget=settings.source_context_chars,
                        syllabus_chars=settings.critique.syllabus_chars,
                        syllabus_chunks=settings.critique.syllabus_chunks,
                    )
        else:
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
    if request.action == "critique":
        score = (
            request.critic_score
            if request.critic_score is not None
            else work.critic_score
        )
        genre = request.essay_genre or work.essay_genre
        syllabus_text = "\n".join(
            candidate.text for candidate in kept if candidate.source_type == "syllabus"
        )
        avoid: set[int] = set()
        if request.focus == "unread":
            included = critique.latest_included(work)
            if included is None:
                raise ValueError(
                    "Critique the draft once before reviewing unread sections."
                )
            avoid = included
        document, coverage = critique.critique_context(
            work.document.text,
            query=query,
            score=score,
            selection=request.selection,
            syllabus_text=syllabus_text,
            avoid=avoid,
        )
        request = request.model_copy(
            update={"critic_score": score, "essay_genre": genre}
        )
    proposed_edit = None
    critique_result: CritiqueResult | None = None
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
        roles = {
            str(candidate.chunk_id): (
                "requirement" if candidate.source_type == "syllabus" else "reading"
            )
            for candidate in kept
        }
        types = {str(candidate.chunk_id): candidate.source_type for candidate in kept}
        evidence = []
        for citation in citations:
            item = {**citation.model_dump(), "citation": f"[{citation.number}]"}
            if request.action == "critique":
                item["role"] = roles.get(citation.chunk_id, "reading")
                item["source_type"] = types.get(citation.chunk_id, "")
            evidence.append(item)
        payload: dict[str, object] = {
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
            "course_evidence": evidence,
        }
        instruction = load_prompt("companion_work") + "\n" + behavior
        response_schema = None
        if request.action == "revise":
            instruction += "\n" + load_prompt("companion_revision")
            response_schema = ProposedEdit.model_json_schema()
        elif request.action == "review":
            instruction += "\n" + load_prompt("companion_review")
            response_schema = DocumentReview.model_json_schema()
        elif request.action == "critique":
            assert request.critic_score is not None
            assert request.essay_genre is not None
            prior = critique.prior_statuses(work, work.document.text)
            payload["critic_score"] = request.critic_score
            payload["essay_genre"] = request.essay_genre
            payload["finding_cap"] = critique.finding_cap(request.critic_score)
            payload["band"] = critique.band_name(request.critic_score)
            payload["syllabus_in_context"] = syllabus_in_context
            payload["prior_findings"] = [item.model_dump() for item in prior]
            instruction = critique.critique_instruction(
                request.critic_score, request.essay_genre, behavior
            )
            response_schema = CritiqueModelOutput.model_json_schema()
        material = json.dumps(payload, ensure_ascii=False)
        generation = provider.generate(
            "tutor_answer",
            grounded_prompt(instruction, material),
            course_id=course_id,
            response_schema=response_schema,
        )
        text, model = strip_fence_echo(generation.text), generation.model
        cited_text = text
        scope = request.selection or document
        if request.action == "critique":
            assert request.critic_score is not None
            assert request.essay_genre is not None
            parsed = parse_json_object(text)
            if parsed is None:
                raise ValueError("The model did not return a critique. Try again.")
            prior = critique.prior_statuses(work, work.document.text)
            findings, citations = critique.validate_findings(
                parsed,
                document_text=work.document.text,
                scope=scope,
                genre=request.essay_genre,
                cap=critique.finding_cap(request.critic_score),
                citations=citations,
                open_quotes={
                    item.original for item in prior if item.status == "still_present"
                },
            )
            critique_result = CritiqueResult(
                genre=request.essay_genre,
                critic_score=request.critic_score,
                syllabus_in_context=syllabus_in_context,
                coverage=coverage,
                findings=findings,
                prior=prior,
                note="" if findings else critique.empty_note(coverage),
            )
            text = critique.render_critique(critique_result)
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
        if request.action != "critique":
            numbers = cited_numbers(cited_text)
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
            citations = [
                citation for citation in citations if citation.number in numbers
            ]
    with connection() as conn:
        cited = tuple(
            (UUID(citation.chunk_id), citation.number) for citation in citations
        )
        stored = trace.record_trace(conn, course_id, search, used, cited=cited)
        reply = WorkReply(
            text=text,
            model=model,
            citations=citations,
            trace_id=str(stored.trace_id),
            coverage=coverage,
            document_revision=work.revision,
            proposed_edit=proposed_edit,
            critique=critique_result,
        )
        saved = work_repo.save_reply(conn, course_id, session_id, request, reply)
        conn.commit()
        return saved
