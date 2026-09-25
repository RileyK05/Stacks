"""Model edits to an artifact (docs/plan-notebook.md §4.3, decision 013).

The student asks for a change ("make slide 3 shorter", "add a due-date
column"); the model returns the changed content as a *proposal* the
student accepts or undoes — nothing is saved here.

Small models do targeted edits well and whole rewrites badly, so an edit
can be scoped to one doc section or one slide. The model reads the part
being edited, the request, and numbered course material: first the
chunks the part already cites (so existing citations stay meaningful),
then chunks retrieved for the request. Its citations are mapped back onto
the artifact's own sources; a citation to material it was not given is
refused, so an edit can never smuggle in an uncited "source".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from src.backend.artifacts import attribution
from src.backend.artifacts import content as artifact_content
from src.backend.artifacts.content import UnknownCitationError
from src.backend.common import provider
from src.backend.common.artifacts_repo import Artifact
from src.backend.common.db import Connection, json_ids
from src.backend.common.prompt_registry import (
    grounded_prompt,
    load_prompt,
    strip_fence_echo,
)
from src.backend.common.providers import ProviderChoice
from src.backend.common.queries import get
from src.backend.retrieval import funnel, rerank, trace
from src.backend.retrieval.config import RetrievalPolicy
from src.backend.tutor.compose import parse_json_object

MAX_MATERIAL = 8
REMOVED_SOURCE = "(this source was removed from the course)"
# How much of the current content an addition shows the model for context.
ADDITION_CONTEXT_CHARS = 4000
_ADDITION = re.compile(
    r"^\s*(?:please\s+)?(?:add|include|insert|append|write|draft|create|make|"
    r"give\s+me|list|put)\b",
    re.IGNORECASE,
)
_REWRITE = re.compile(
    r"\b(?:rewrite|re-write|shorten|shorter|concise|simplify|fix|correct|reword|"
    r"rephrase|replace|remove|delete|reorgani[sz]e|restructure|translate|edit|change|"
    r"improve|expand this|turn (?:this|it) into)\b",
    re.IGNORECASE,
)
_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)
_PREAMBLE = re.compile(
    r"^(?:sure|certainly|okay|ok|of course|here(?:'s| is| are)|below is)\b.*:$",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*)\n```\s*$", re.DOTALL)


class EditScope(BaseModel):
    """Which part to edit: a doc section (split at headings) or a slide.
    None edits the whole artifact."""

    part: Literal["section", "slide"]
    index: int = Field(ge=0)


class EditFailedError(RuntimeError):
    """The model's reply could not be used; the message says why."""


@dataclass(frozen=True)
class Proposal:
    title: str
    content: dict[str, Any]
    sources: list[UUID]
    model: str
    trace_id: UUID
    # New lines the model wrote that match no passage clearly enough to
    # cite: the student is told before accepting.
    uncited_lines: int = 0


@dataclass(frozen=True)
class _Material:
    chunk_ids: list[UUID]
    texts: list[str]


# --- the part being edited ----------------------------------------------


def _fenced_spans(markdown: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    opened: int | None = None
    offset = 0
    for line in markdown.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            if opened is None:
                opened = offset
            else:
                spans.append((opened, offset + len(line)))
                opened = None
        offset += len(line)
    if opened is not None:
        spans.append((opened, len(markdown)))
    return spans


def doc_sections(markdown: str) -> list[str]:
    """A doc split at its headings; text before the first heading is a
    section of its own. Joining the sections gives the doc back. A "#"
    line inside a fenced code block (a Python comment) is not a heading."""
    fenced = _fenced_spans(markdown)
    starts = [
        m.start()
        for m in _HEADING.finditer(markdown)
        if not any(a <= m.start() < b for a, b in fenced)
    ]
    if not starts or starts[0] != 0:
        starts = [0, *starts]
    bounds = [*starts, len(markdown)]
    return [markdown[a:b] for a, b in zip(bounds, bounds[1:], strict=False) if a < b]


def _target(artifact: Artifact, scope: EditScope | None) -> Any:
    content = artifact.content
    if scope is None:
        return content
    if artifact.kind == "doc" and scope.part == "section":
        sections = doc_sections(content.get("markdown", ""))
        if scope.index >= len(sections):
            raise EditFailedError("that section no longer exists")
        return {"markdown": sections[scope.index]}
    if artifact.kind == "slides" and scope.part == "slide":
        slides = content.get("slides", [])
        if scope.index >= len(slides):
            raise EditFailedError("that slide no longer exists")
        return {"slides": [slides[scope.index]]}
    raise EditFailedError(f"a {artifact.kind} can't be edited by {scope.part}")


def _splice(
    artifact: Artifact, scope: EditScope | None, edited: dict[str, Any]
) -> dict[str, Any]:
    if scope is None:
        return edited
    if artifact.kind == "doc":
        sections = doc_sections(artifact.content.get("markdown", ""))
        replacement = edited["markdown"]
        if sections[scope.index].endswith("\n") and not replacement.endswith("\n"):
            replacement += "\n\n"
        sections[scope.index] = replacement
        return {"markdown": "".join(sections)}
    slides = list(artifact.content.get("slides", []))
    new = edited.get("slides", [])
    slides[scope.index : scope.index + 1] = new or [slides[scope.index]]
    return {"slides": slides}


# --- how the model sees it and answers --------------------------------------


def _render(kind: str, target: Any) -> str:
    if kind == "doc":
        return str(target.get("markdown", ""))
    return json.dumps(target, ensure_ascii=False, indent=1)


_FORMAT_HINTS: dict[str, str] = {
    "doc": "Return the whole edited text as Markdown, nothing else.",
    "sheet": (
        'Return JSON: {"columns": [...], "rows": [[...], ...]}; '
        "every row has one cell per column."
    ),
    "slides": (
        'Return JSON: {"slides": [{"title": "...", "body": "Markdown", '
        '"notes": "..."}]}.'
    ),
    "quiz": (
        'Return JSON: {"questions": [{"prompt": "...", "options": ["..."], '
        '"answer": 0, "explanation": "...", "sources": [1]}]}; '
        '"answer" is the index of the correct option.'
    ),
    "flashcards": (
        'Return JSON: {"cards": [{"front": "...", "back": "...", "sources": [1]}]}.'
    ),
    "code": 'Return JSON: {"language": "...", "code": "..."}.',
    "chart": 'Return JSON: {"html": "..."} (HTML/SVG only, no scripts).',
}


def _string_array(item: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "array", "items": item or {"type": "string"}}


def _schema(kind: str, material_count: int) -> dict[str, Any] | None:
    number = {"type": "integer", "minimum": 1, "maximum": max(material_count, 1)}

    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    string = {"type": "string"}
    if kind == "sheet":
        return obj({"columns": _string_array(), "rows": _string_array(_string_array())})
    if kind == "slides":
        return obj(
            {
                "slides": _string_array(
                    obj({"title": string, "body": string, "notes": string})
                )
            }
        )
    if kind == "quiz":
        return obj(
            {
                "questions": _string_array(
                    obj(
                        {
                            "prompt": string,
                            "options": _string_array(),
                            "answer": {"type": "integer", "minimum": 0},
                            "explanation": string,
                            "sources": _string_array(number),
                        }
                    )
                )
            }
        )
    if kind == "flashcards":
        return obj(
            {
                "cards": _string_array(
                    obj(
                        {
                            "front": string,
                            "back": string,
                            "sources": _string_array(number),
                        }
                    )
                )
            }
        )
    if kind == "code":
        return obj({"language": string, "code": string})
    if kind == "chart":
        return obj({"html": string})
    return None


def _parse(kind: str, raw: str) -> dict[str, Any]:
    if kind == "doc":
        text = strip_fence_echo(raw).strip()
        fenced = _FENCE.match(text)
        body = (fenced.group(1) if fenced else text).strip()
        # "Here is a short study guide…:" is the model talking, not content.
        first, _, rest = body.partition("\n")
        if rest.strip() and _PREAMBLE.match(first.strip()):
            body = rest.strip()
        return {"markdown": body + "\n"}
    parsed = parse_json_object(raw)
    if parsed is None:
        raise EditFailedError(
            "the model's reply wasn't in the expected format; try again"
        )
    return parsed


def _attribute(
    kind: str, edited: dict[str, Any], shown: Any, texts: list[str]
) -> tuple[dict[str, Any], int]:
    """Cite the new prose lines of a doc or slide edit that clearly come
    from one passage (attribution.py). Numbers refer to the material list,
    like the model's own citations."""
    if kind == "doc":
        result = attribution.attach(
            str(edited.get("markdown", "")), texts, before=_render(kind, shown)
        )
        return {**edited, "markdown": result.text}, result.uncited
    if kind == "slides" and isinstance(edited.get("slides"), list):
        before = json.dumps(shown, ensure_ascii=False)
        uncited = 0
        slides = []
        for slide in edited["slides"]:
            if not isinstance(slide, dict):
                slides.append(slide)
                continue
            result = attribution.attach(
                str(slide.get("body", "")), texts, before=before
            )
            uncited += result.uncited
            slides.append({**slide, "body": result.text})
        return {**edited, "slides": slides}, uncited
    return edited, 0


def _strip_echo(
    kind: str, edited: dict[str, Any], shown: Any, texts: list[str]
) -> dict[str, Any]:
    """Drop course material the model pasted back instead of writing
    (attribution.strip_echo)."""
    before = _render(kind, shown)
    if kind == "doc":
        return {
            **edited,
            "markdown": attribution.strip_echo(
                str(edited.get("markdown", "")), texts, before
            ),
        }
    if kind == "slides" and isinstance(edited.get("slides"), list):
        return {
            **edited,
            "slides": [
                {
                    **s,
                    "body": attribution.strip_echo(
                        str(s.get("body", "")), texts, before
                    ),
                }
                if isinstance(s, dict)
                else s
                for s in edited["slides"]
            ],
        }
    return edited


# --- material ------------------------------------------------------------------


def _material(
    conn: Connection,
    course_id: UUID,
    artifact: Artifact,
    target: Any,
    request: str,
    policy: RetrievalPolicy,
    *,
    query_embedding: list[float] | None,
    embedding_model: str | None,
) -> tuple[_Material, funnel.RetrievalResult]:
    cited = [
        artifact.sources[n - 1]
        for n in sorted(artifact_content.cited_numbers(target))
        if 1 <= n <= len(artifact.sources)
    ]
    query = f"{request}\n{_render(artifact.kind, target)[:600]}"
    result = funnel.retrieve(
        conn,
        course_id,
        query,
        policy,
        query_embedding=query_embedding,
        embedding_model=embedding_model,
    )
    chosen = (
        rerank.select_for_generation(query, result.candidates)
        if result.candidates
        else ()
    )
    chunk_ids = list(dict.fromkeys([*cited, *(c.chunk_id for c in chosen)]))[
        :MAX_MATERIAL
    ]
    rows = conn.execute(
        get("retrieval_traces", "chunks_with_locators_by_ids"),
        {"chunk_ids": json_ids(chunk_ids)},
    ).fetchall()
    text_by_id = {row["chunk_id"]: row["text"] for row in rows}
    # A cited chunk whose source was removed keeps its place (so the
    # numbering the model sees still lines up with the artifact's).
    kept = [cid for cid in chunk_ids if cid in text_by_id or cid in cited]
    return (
        _Material(kept, [text_by_id.get(cid, REMOVED_SOURCE) for cid in kept]),
        result,
    )


def is_addition(kind: str, request: str, target: Any) -> bool:
    """Whether the request adds something new (answered with only the new
    part, inserted by code) rather than changing what is there. An empty
    doc or deck is always an addition."""
    if kind == "doc":
        if not str(target.get("markdown", "")).strip():
            return True
    elif kind == "slides":
        slides = target.get("slides", [])
        if all(not (s.get("title") or s.get("body")) for s in slides):
            return True
    else:
        return False
    return bool(_ADDITION.match(request)) and not _REWRITE.search(request)


_ADD_HINTS: dict[str, str] = {
    "doc": "Return only the new Markdown to add, nothing else.",
    "slides": (
        'Return JSON: {"slides": [{"title": "...", "body": "Markdown", '
        '"notes": "..."}]} with only the new slides.'
    ),
}


def _combine(kind: str, shown: Any, added: dict[str, Any]) -> dict[str, Any]:
    if kind == "doc":
        current = str(shown.get("markdown", "")).rstrip()
        new = str(added.get("markdown", "")).strip()
        joined = f"{current}\n\n{new}" if current else new
        return {"markdown": joined + "\n"}
    existing = [s for s in shown.get("slides", []) if s.get("title") or s.get("body")]
    return {"slides": [*existing, *added.get("slides", [])]}


def propose_edit(
    conn: Connection,
    course_id: UUID,
    artifact: Artifact,
    request: str,
    policy: RetrievalPolicy,
    *,
    scope: EditScope | None = None,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
    choice: ProviderChoice | None = None,
) -> Proposal:
    """The artifact with the requested change applied, not saved. Writes
    the retrieval trace (the caller commits) so the edit is auditable."""
    target = _target(artifact, scope)
    material, result = _material(
        conn,
        course_id,
        artifact,
        target,
        request,
        policy,
        query_embedding=query_embedding,
        embedding_model=embedding_model,
    )
    # The part being edited, renumbered to the material list the model
    # reads: its existing citations come first in that list.
    to_material = {
        n: material.chunk_ids.index(artifact.sources[n - 1]) + 1
        for n in artifact_content.cited_numbers(target)
        if 1 <= n <= len(artifact.sources)
        and artifact.sources[n - 1] in material.chunk_ids
    }
    shown = artifact_content.renumber(target, to_material)
    numbered = "\n\n".join(
        f"[{index + 1}] {text}" for index, text in enumerate(material.texts)
    )
    adding = is_addition(artifact.kind, request, target)
    if adding:
        context = _render(artifact.kind, shown)
        if len(context) > ADDITION_CONTEXT_CHARS:
            context = "…" + context[-ADDITION_CONTEXT_CHARS:]
        block = (
            f"Artifact type: {artifact.kind}\n"
            f"Current content (for context only; do not repeat it):\n"
            f"{context.strip() or '(empty)'}\n\n"
            f"Write only the new part to add: {request}\n\n"
            f"{_ADD_HINTS[artifact.kind]}\n\n"
            f"Course material:\n{numbered or '(none found for this request)'}"
        )
    else:
        block = (
            f"Artifact type: {artifact.kind}\n"
            f"Current content:\n{_render(artifact.kind, shown)}\n\n"
            f"Requested change: {request}\n\n"
            f"{_FORMAT_HINTS[artifact.kind]}\n\n"
            f"Course material:\n{numbered or '(none found for this request)'}"
        )
    schema = _schema(artifact.kind, len(material.chunk_ids))
    prompt = grounded_prompt(load_prompt("artifact_edit"), block)
    try:
        generation = provider.generate(
            "artifact_generation",
            prompt,
            course_id=course_id,
            response_schema=schema,
            choice=choice,
        )
    except provider.ProviderRequestRejectedError:
        if schema is None:
            raise
        generation = provider.generate(
            "artifact_generation", prompt, course_id=course_id, choice=choice
        )
    edited = _strip_echo(
        artifact.kind, _parse(artifact.kind, generation.text), shown, material.texts
    )
    if adding:
        edited = _combine(artifact.kind, shown, edited)
    edited, uncited = _attribute(artifact.kind, edited, shown, material.texts)
    try:
        edited = artifact_content.validate_content(artifact.kind, edited)
        merged, sources = artifact_content.merge(
            edited, material.chunk_ids, artifact.sources
        )
    except UnknownCitationError as err:
        raise EditFailedError(
            f"the edit cited material it wasn't given ({err}); nothing was changed"
        ) from err
    except (ValidationError, ValueError) as err:
        raise EditFailedError(
            "the model's reply didn't fit this artifact; try again or rephrase"
        ) from err
    full = artifact_content.validate_content(
        artifact.kind, _splice(artifact, scope, merged)
    )
    used = result.__class__(
        candidates=tuple(
            c for c in result.candidates if c.chunk_id in material.chunk_ids
        ),
        layer_contribution=result.layer_contribution,
        matched_concept_ids=result.matched_concept_ids,
        matched_toc_entry_ids=result.matched_toc_entry_ids,
    )
    stored = trace.record_trace(
        conn,
        course_id,
        request,
        used,
        embedding_model=embedding_model,
        toc_entry_ids=result.matched_toc_entry_ids,
    )
    return Proposal(
        uncited_lines=uncited,
        title=artifact.title,
        content=full,
        sources=sources,
        model=generation.model,
        trace_id=stored.trace_id,
    )
