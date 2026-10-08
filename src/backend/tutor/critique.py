"""Essay critique: comments on a draft, scored by harshness, never a rewrite."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import ValidationError
from src.backend.common.citations import cited_numbers
from src.backend.common.companion_config import CritiquePolicy, load_companion_policy
from src.backend.common.prompt_registry import load_prompt
from src.backend.common.schemas.work import (
    ContextCoverage,
    CritiqueFinding,
    CritiqueModelOutput,
    CritiqueResult,
    EssayGenre,
    PriorFindingStatus,
    WorkCitation,
    WorkSession,
)
from src.backend.retrieval.funnel import Candidate

CRAFT_GENRES = frozenset({"creative", "reflective"})
FALLACY_LABELS = {
    "straw_man": "straw man",
    "false_dilemma": "false dilemma",
    "hasty_generalization": "hasty generalization",
    "post_hoc": "post hoc",
    "appeal_to_authority": "appeal to authority",
    "circular": "circular",
    "slippery_slope": "slippery slope",
    "ad_hominem": "ad hominem",
    "equivocation": "equivocation",
    "unsupported_claim": "unsupported claim",
    "missing_counterargument": "missing counterargument",
}
DIMENSION_LABELS = {
    "requirements": "Requirements",
    "reasoning": "Reasoning",
    "evidence": "Evidence",
    "structure": "Structure",
    "craft": "Craft",
    "clarity": "Clarity",
}
_REWRITE = re.compile(
    r"\b(?:re)?write\b.{0,80}\b(?:essay|paper|paragraph|draft|assignment|story|"
    r"section)\b"
    r"|\b(?:rewrite|redraft)\b.{0,40}\b(?:it|this|the draft|my draft)\b"
    r"|\b(?:complete|finish)\b.{0,40}\b(?:essay|paper|assignment|draft)\b"
    r"|\bmake (?:it|this|the essay|the draft) (?:perfect|better|stronger)\b"
    r"|\bdraft (?:the|my|a) (?:essay|paragraph|paper)\b",
    re.IGNORECASE | re.DOTALL,
)
_WORDS = re.compile(r"\w{3,}")


def finding_cap(score: int, policy: CritiquePolicy | None = None) -> int:
    policy = policy or load_companion_policy().critique
    span = score - policy.score_min
    return round(policy.cap_base + span * policy.cap_rise / policy.cap_span)


def band_name(score: int, policy: CritiquePolicy | None = None) -> str:
    policy = policy or load_companion_policy().critique
    if score < policy.strong_from:
        return "rough"
    if score < policy.severe_from:
        return "strong"
    return "severe"


def critique_instruction(score: int, genre: str, behavior: str) -> str:
    return "\n".join(
        (
            load_prompt("companion_work"),
            behavior,
            load_prompt("companion_critique"),
            load_prompt(f"companion_critique_{band_name(score)}"),
            load_prompt(f"companion_critique_{genre}"),
        )
    )


def refuses_rewrite(instruction: str) -> bool:
    return bool(_REWRITE.search(instruction))


def _words(text: str) -> set[str]:
    return set(_WORDS.findall(text.casefold()))


def _overlap(text: str, words: set[str]) -> int:
    return len(words & _words(text))


def reserve_course_evidence(
    ranked: Sequence[Candidate],
    pool: Sequence[Candidate],
    query: str,
    *,
    source_budget: int,
    syllabus_chars: int,
    syllabus_chunks: int,
) -> tuple[list[Candidate], bool]:
    """Keep up to `syllabus_chunks` syllabus passages ahead of other evidence."""
    words = _words(query)
    seen: set[object] = set()
    unique: list[Candidate] = []
    for candidate in pool:
        if candidate.chunk_id in seen:
            continue
        seen.add(candidate.chunk_id)
        unique.append(candidate)
    syllabus = sorted(
        (c for c in unique if c.source_type == "syllabus"),
        key=lambda c: (-_overlap(c.text, words), c.chunk_index),
    )
    chosen: list[Candidate] = []
    used = 0
    for candidate in syllabus:
        if len(chosen) >= syllabus_chunks:
            break
        if used + len(candidate.text) > min(syllabus_chars, source_budget):
            continue
        chosen.append(candidate)
        used += len(candidate.text)
    taken = {c.chunk_id for c in chosen}
    for candidate in ranked:
        if candidate.chunk_id in taken:
            continue
        if used + len(candidate.text) > source_budget:
            continue
        chosen.append(candidate)
        taken.add(candidate.chunk_id)
        used += len(candidate.text)
    return chosen, any(c.source_type == "syllabus" for c in chosen)


def critique_context(
    text: str,
    *,
    query: str,
    score: int,
    selection: str,
    syllabus_text: str,
    avoid: set[int],
) -> tuple[str, ContextCoverage]:
    policy = load_companion_policy()
    critique = policy.critique
    width = policy.section_chars
    sections = [text[i : i + width] for i in range(0, len(text), width)] or [text]
    budget = policy.document_context_chars
    if score < critique.edge_sections_from:
        budget = min(budget, critique.low_context_chars)
    rank_words = _words(syllabus_text) or _words(query)

    def add(chosen: list[int], used: int, index: int) -> tuple[list[int], int, bool]:
        if index in chosen or index < 0 or index >= len(sections):
            return chosen, used, False
        cost = len(sections[index]) + (8 if chosen else 0)
        if chosen and used + cost > budget:
            return chosen, used, False
        return [*chosen, index], used + cost, True

    chosen: list[int] = []
    used = 0
    if selection and selection in text:
        start = text.find(selection)
        end = start + len(selection)
        cursor = 0
        for index, section in enumerate(sections):
            if start < cursor + len(section) and end > cursor:
                chosen, used, _ = add(chosen, used, index)
            cursor += len(section)
    if not avoid and len(text) <= budget:
        chosen = list(range(len(sections)))
    else:
        candidates = list(range(len(sections)))
        if avoid:
            unread = [i for i in candidates if (i + 1) not in avoid]
            if not unread:
                raise ValueError(
                    "The last critique already covered every section of this draft."
                )
            candidates = unread
        elif score >= critique.edge_sections_from:
            chosen, used, _ = add(chosen, used, 0)
            if len(sections) > 1:
                chosen, used, _ = add(chosen, used, len(sections) - 1)
        ranked = sorted(
            candidates, key=lambda i: (-_overlap(sections[i], rank_words), i)
        )
        for index in ranked:
            chosen, used, _ = add(chosen, used, index)
        if not chosen and ranked:
            chosen = [ranked[0]]
    ordered = sorted(set(chosen))
    content = "\n\n".join(f"[D{i + 1}] {sections[i]}" for i in ordered)
    coverage = ContextCoverage(
        total_sections=len(sections),
        included_sections=[i + 1 for i in ordered],
        complete=len(ordered) == len(sections),
    )
    return content, coverage


def prior_statuses(work: WorkSession, document_text: str) -> list[PriorFindingStatus]:
    previous = next(
        (turn.reply.critique for turn in reversed(work.turns) if turn.reply.critique),
        None,
    )
    if previous is None:
        return []
    return [
        PriorFindingStatus(
            original=finding.original,
            feedback=finding.feedback,
            status=(
                "still_present"
                if finding.original in document_text
                else "passage_changed"
            ),
        )
        for finding in previous.findings
    ]


def latest_included(work: WorkSession) -> set[int] | None:
    for turn in reversed(work.turns):
        if turn.reply.critique is not None:
            return set(turn.reply.critique.coverage.included_sections)
    return None


def _names_fallacy(feedback: str, fallacy: str) -> bool:
    label = FALLACY_LABELS[fallacy]
    folded = feedback.casefold()
    return label in folded or label.replace(" ", "") in folded


def validate_findings(
    raw: dict[str, object],
    *,
    document_text: str,
    scope: str,
    genre: EssayGenre,
    cap: int,
    citations: list[WorkCitation],
    open_quotes: set[str],
) -> tuple[list[CritiqueFinding], list[WorkCitation]]:
    try:
        output = CritiqueModelOutput.model_validate(raw)
    except ValidationError as err:
        raise ValueError(
            "The critique did not match the review format. Try again."
        ) from err
    allowed = {citation.number for citation in citations}
    checked: list[CritiqueFinding] = []
    outside = (
        "The critique referred to a passage outside the reviewed draft. "
        "Try again or select a passage."
    )
    for finding in output.findings:
        original = finding.original
        if (
            not original.strip()
            or original not in document_text
            or original not in scope
        ):
            raise ValueError(outside)
        if original in open_quotes:
            raise ValueError(
                "The critique repeated a passage that is still in the draft. Try again."
            )
        if genre in CRAFT_GENRES and finding.fallacy != "none":
            raise ValueError(
                "A creative or reflective critique cannot assign a fallacy."
            )
        if finding.fallacy != "none" and not _names_fallacy(
            finding.feedback, finding.fallacy
        ):
            raise ValueError("The critique named a fallacy it did not explain.")
        numbers = cited_numbers(finding.feedback)
        if not numbers.issubset(allowed):
            raise ValueError("The critique cited a source it was not given.")
        # A craft note that cites a real supplied passage is a course judgment.
        grounding: Literal["course", "craft"] = finding.grounding
        if grounding == "craft" and numbers:
            grounding = "course"
        if grounding == "course" and not numbers:
            raise ValueError(
                "A course-based comment needs a citation from the supplied passages."
            )
        checked.append(finding.model_copy(update={"grounding": grounding}))
    kept = checked[:cap]
    used_numbers: set[int] = set()
    for finding in kept:
        used_numbers.update(cited_numbers(finding.feedback))
    return kept, [citation for citation in citations if citation.number in used_numbers]


def render_critique(result: CritiqueResult) -> str:
    parts: list[str] = []
    if result.note:
        parts.append(result.note)
    for finding in result.findings:
        label = DIMENSION_LABELS[finding.dimension]
        if finding.fallacy != "none":
            label = f"{label} · {FALLACY_LABELS[finding.fallacy]}"
        parts.append(
            f"**{label}**\n\n**Draft passage**\n\n{finding.original}\n\n"
            f"**Feedback**\n\n{finding.feedback}"
        )
    if result.prior:
        lines = []
        for item in result.prior:
            name = "Still open" if item.status == "still_present" else "Passage edited"
            lines.append(f"- {name}: {item.original}")
        parts.append("**Earlier passages**\n\n" + "\n".join(lines))
    sections = ", ".join(str(number) for number in result.coverage.included_sections)
    if result.coverage.complete:
        scope = "All supplied sections were read."
    else:
        scope = (
            f"Sections {sections} of {result.coverage.total_sections} were read. "
            "This is not a review of the rest of the draft."
        )
    if result.syllabus_in_context:
        scope += " Syllabus passages were supplied."
    else:
        scope += " No syllabus passage was supplied, so no assignment rule was assumed."
    parts.append(scope)
    return "\n\n".join(parts)


def empty_note(coverage: ContextCoverage) -> str:
    sections = ", ".join(str(number) for number in coverage.included_sections) or "none"
    return f"No grounded objection in sections {sections}."
