"""Task framing before generation (docs/plan-local-first.md §6.1, §6.3).

A small model given the whole task — "answer, and maybe emit one of six
JSON block types if the student seems to want one" — talks ABOUT the
instructions instead of following them (Phase 0 bake-off: MiniCPM5-2B
replied "If you ask for quizzed… I can provide a study guide"). So the
harness decides the shape first and asks for exactly that:

- a plain question gets the lean `tutor_answer` prompt;
- a request for a quiz, notes, a table, slides, or code gets that kind's
  narrow prompt plus a JSON schema. The schema bounds every `sources`
  number to the material actually provided, so an out-of-range citation
  cannot even be generated on a constrained runtime.

Either way the result is the same answer text the rest of the pipeline
already understands (prose plus at most one fenced workspace block), so
the citation gate in `workspace.py` still has the final word. The live
tutor and the answer eval both come through here, so the eval measures
exactly what users get.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from src.backend.common.prompt_registry import (
    grounded_prompt,
    load_prompt,
    strip_fence_echo,
)
from src.backend.retrieval.funnel import Candidate


class Intent(StrEnum):
    ANSWER = "answer"
    GRADED = "graded"
    QUIZ = "quiz"
    DOCUMENT = "document"
    SHEET = "sheet"
    SLIDES = "slides"
    CODE = "code"


# Requests to complete graded work never get a workspace item, whatever
# shape they ask for ("give me the filled-in answer sheet"): they take the
# plain-answer path, whose prompt steers them (decision 009's red/yellow
# zones). Checked before any shape rule.
_GRADED_WORK = re.compile(
    r"\b(?:so (?:i|that i) can|for me to|to)"
    r" (?:submit|hand (?:it )?in|turn (?:it )?in)\b"
    r"|\btake (?:this|my|the) (?:exam|test|quiz) for me\b"
    r"|\bfill in (?:all )?(?:of )?(?:the|my) answers\b"
    r"|\bdo my (?:homework|assignment|problem set|exam)\b"
    r"|\bwrite my (?:essay|paper|assignment|answer)\b",
    re.IGNORECASE,
)

# Ordered: the first matching rule wins ("make slides summarizing X" is
# slides, not notes). Word-boundary anchored so course vocabulary can't
# trigger a shape ("notation" is not "notes", "codomain" is not "code");
# a "sheet" is a spreadsheet only when it isn't an answer/cheat/review
# sheet.
_INTENT_RULES: tuple[tuple[Intent, re.Pattern[str]], ...] = (
    (
        Intent.QUIZ,
        re.compile(
            r"\bquiz(?:zes|zed)?\b|\bmultiple[- ]choice\b|\btest me\b"
            r"|\bpractice (?:questions?|problems?)\b|\bflash ?cards?\b",
            re.IGNORECASE,
        ),
    ),
    (
        Intent.SLIDES,
        re.compile(r"\bslides?\b|\bslide deck\b|\bpresentation\b", re.IGNORECASE),
    ),
    (
        Intent.SHEET,
        re.compile(
            r"\btable\b|\bspreadsheet\b|\bcsv\b|\bcomparison chart\b"
            r"|(?<!answer )(?<!cheat )(?<!review )(?<!work)\bsheet\b",
            re.IGNORECASE,
        ),
    ),
    (
        Intent.CODE,
        re.compile(
            r"\bcode\b|\b(?:python|javascript|java|r) (?:function|script|program)\b"
            r"|\bwrite (?:a|the) (?:function|program|script)\b",
            re.IGNORECASE,
        ),
    ),
    (
        Intent.DOCUMENT,
        re.compile(
            r"\bstudy guide\b|\bnotes\b|\boutline\b|\b(?:cheat|review) ?sheet\b"
            r"|\bsummary (?:i|we) can edit\b|\beditable\b",
            re.IGNORECASE,
        ),
    ),
)


def classify_intent(question: str) -> Intent:
    if _GRADED_WORK.search(question):
        return Intent.GRADED
    for intent, pattern in _INTENT_RULES:
        if pattern.search(question):
            return intent
    return Intent.ANSWER


class Generate(Protocol):
    """The model call: task + prompt in, text out. `response_schema`, when
    given, asks the endpoint to constrain output to that JSON schema."""

    def __call__(
        self, task: str, prompt: str, *, response_schema: dict[str, Any] | None = None
    ) -> str: ...


@dataclass(frozen=True)
class Composed:
    """Answer text in the tutor's standard shape: prose plus at most one
    fenced workspace block (lifted out and gated by workspace.py)."""

    text: str
    intent: Intent
    structured: bool


def numbered_material(question: str, candidates: tuple[Candidate, ...]) -> str:
    blocks = [
        f"[{index + 1}] chunk {candidate.chunk_id}\n{candidate.text}"
        for index, candidate in enumerate(candidates)
    ]
    evidence = "\n\n".join(blocks)
    return f"Question: {question}\n\nCourse material:\n{evidence}"


def build_prompt(question: str, candidates: tuple[Candidate, ...]) -> str:
    """The plain-answer prompt: instruction first, then the question and
    numbered chunks fenced as data (the prompt-injection gate)."""
    return grounded_prompt(
        load_prompt("tutor_answer"), numbered_material(question, candidates)
    )


def _sources_schema(material_count: int) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "integer", "minimum": 1, "maximum": max(material_count, 1)},
        "minItems": 1,
        "maxItems": max(material_count, 1),
    }


def _string(max_length: int | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "minLength": 1}
    if max_length is not None:
        schema["maxLength"] = max_length
    return schema


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    # Every property required + no extras: valid for llama.cpp grammars and
    # for OpenAI's strict structured outputs alike.
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def workspace_schema(intent: Intent, material_count: int) -> dict[str, Any]:
    sources = _sources_schema(material_count)
    items: dict[Intent, dict[str, Any]] = {
        Intent.QUIZ: _object(
            {
                "type": {"const": "quiz"},
                "title": _string(120),
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": _object(
                        {
                            "prompt": _string(400),
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "minLength": 2,
                                    "maxLength": 200,
                                },
                                "minItems": 2,
                                "maxItems": 4,
                            },
                            "answer": {"type": "integer", "minimum": 0, "maximum": 3},
                            "explanation": _string(400),
                            "sources": sources,
                        }
                    ),
                },
            }
        ),
        Intent.DOCUMENT: _object(
            {
                "type": {"const": "document"},
                "title": _string(120),
                "content": _string(6000),
                "sources": sources,
            }
        ),
        Intent.SHEET: _object(
            {
                "type": {"const": "sheet"},
                "title": _string(120),
                "columns": {
                    "type": "array",
                    "items": _string(80),
                    "minItems": 1,
                    "maxItems": 8,
                },
                "rows": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 30,
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
                "sources": sources,
            }
        ),
        Intent.SLIDES: _object(
            {
                "type": {"const": "slides"},
                "title": _string(120),
                "deck": _string(6000),
                "sources": sources,
            }
        ),
        Intent.CODE: _object(
            {
                "type": {"const": "code"},
                "title": _string(120),
                "language": _string(30),
                "code": _string(6000),
                "sources": sources,
            }
        ),
    }
    return _object({"reply": _string(600), "item": items[intent]})


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in a model reply: the whole reply when the
    endpoint honoured the schema, a ```json fence or the outermost braces
    when it did not."""
    candidates = [text.strip()]
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


_SCHEMA_REMINDER = (
    "\n\nRespond with ONE JSON object only (no prose around it), shaped as: "
    '{"reply": "...", "item": {...}}.'
)


def compose_answer(
    question: str,
    candidates: tuple[Candidate, ...],
    generate: Generate,
    *,
    on_schema_rejected: Callable[[Exception], bool] | None = None,
) -> Composed:
    """Frame the task, generate, and return standard answer text.

    `on_schema_rejected(err)` decides whether a failed constrained call
    should be retried without the schema (an endpoint that rejects
    `response_format`); it returns False to re-raise."""
    intent = classify_intent(question)
    if intent in (Intent.ANSWER, Intent.GRADED):
        instruction = "tutor_steer" if intent is Intent.GRADED else "tutor_answer"
        prompt = grounded_prompt(
            load_prompt(instruction), numbered_material(question, candidates)
        )
        text = generate("tutor_answer", prompt)
        return Composed(strip_fence_echo(text), intent, structured=False)

    prompt = grounded_prompt(
        load_prompt(f"workspace_{intent.value}"),
        numbered_material(question, candidates),
    )
    schema = workspace_schema(intent, len(candidates))
    try:
        raw = generate("artifact_generation", prompt, response_schema=schema)
    except Exception as err:
        if on_schema_rejected is None or not on_schema_rejected(err):
            raise
        raw = generate("artifact_generation", prompt + _SCHEMA_REMINDER)
    parsed = parse_json_object(raw)
    item = parsed.get("item") if parsed else None
    if not isinstance(item, dict):
        # Unusable structure: show whatever prose came back; the workspace
        # gate has nothing to lift, so nothing uncited can slip through.
        return Composed(strip_fence_echo(raw), intent, structured=False)
    reply = str(parsed.get("reply") or "").strip() if parsed else ""
    block = json.dumps(item, ensure_ascii=False)
    text = f"{reply}\n\n```workspace\n{block}\n```".strip()
    return Composed(strip_fence_echo(text), intent, structured=True)
