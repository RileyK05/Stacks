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
_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)
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


@dataclass(frozen=True)
class _Material:
    chunk_ids: list[UUID]
    texts: list[str]


# --- the part being edited ----------------------------------------------


def doc_sections(markdown: str) -> list[str]:
    """A doc split at its headings; text before the first heading is a
    section of its own. Joining the sections gives the doc back."""
    starts = [m.start() for m in _HEADING.finditer(markdown)]
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
        return {"markdown": (fenced.group(1) if fenced else text) + "\n"}
    parsed = parse_json_object(raw)
    if parsed is None:
        raise EditFailedError(
            "the model's reply wasn't in the expected format; try again"
        )
    return parsed


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
    present = [cid for cid in chunk_ids if cid in text_by_id]
    return _Material(present, [text_by_id[cid] for cid in present]), result


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
    try:
        shown = artifact_content.renumber(target, to_material)
    except UnknownCitationError:
        shown = target
    numbered = "\n\n".join(
        f"[{index + 1}] {text}" for index, text in enumerate(material.texts)
    )
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
    edited = _parse(artifact.kind, generation.text)
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
        title=artifact.title,
        content=full,
        sources=sources,
        model=generation.model,
        trace_id=stored.trace_id,
    )
