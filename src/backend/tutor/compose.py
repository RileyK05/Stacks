"""Task framing before generation.

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

from src.backend.common import generation as generation_control
from src.backend.common.citations import cited_numbers
from src.backend.common.prompt_registry import (
    grounded_prompt,
    load_prompt,
    load_prompt_policy,
    strip_fence_echo,
)
from src.backend.common.schemas.mind_map import MindMapContent, anchor_map_evidence
from src.backend.retrieval.funnel import Candidate
from src.backend.tutor import quotes as quote_anchors
from src.backend.tutor.materials import DeckDraft, DocumentDraft, has_body
from src.backend.tutor.workspace import extract_workspace_items


class Intent(StrEnum):
    # Small talk ("hi", "thanks", "echo hello", "what can you do?"): answered
    # by the model without course material, never refused as "nothing
    # relevant found".
    CHAT = "chat"
    ANSWER = "answer"
    GRADED = "graded"
    QUIZ = "quiz"
    DOCUMENT = "document"
    SHEET = "sheet"
    SLIDES = "slides"
    CODE = "code"
    MIND_MAP = "mind_map"


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
            r"|\bpractice (?:questions?|problems?|tests?|suites?)\b|\bflash ?cards?\b",
            re.IGNORECASE,
        ),
    ),
    (Intent.MIND_MAP, re.compile(r"\b(?:mind|concept|topic)[ -]?map\b", re.IGNORECASE)),
    (
        Intent.SLIDES,
        re.compile(r"\bslides?\b|\bslide deck\b|\bpresentation\b", re.IGNORECASE),
    ),
    (
        Intent.SHEET,
        re.compile(
            r"\btable\b|\bspreadsheet\b|\bcsv\b|\bcomparison chart\b"
            r"|(?<!answer )(?<!cheat )(?<!review )(?<!study )(?<!work)\bsheet\b",
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
            r"\bstudy guide\b|\bnotes\b|\boutline\b|\b(?:cheat|review|study) ?sheet\b"
            r"|\bsummary (?:i|we) can edit\b|\beditable\b",
            re.IGNORECASE,
        ),
    ),
)


# "and a quiz on that", "now make a table": a request may lead with a filler.
_LEAD = r"^\s*(?:(?:and|also|now|then|ok|okay|so|next)\b[\s,]+)*"
_ARTIFACT_REQUEST = re.compile(
    _LEAD + r"(?:(?:please|could you|can you|would you|will you)\s+)*"
    r"(?:make|create|generate|write|draft|build|prepare|produce|give me|show me|"
    r"turn|convert|format|put|organize|quiz me|test me|"
    r"i (?:want|need|would like))\b"
    r"|" + _LEAD + r"(?:please\s+)?(?:quiz|test) me\b"
    r"|" + _LEAD + r"(?:a |an |some )?(?:quiz|flash ?cards?|slides?|slide deck|"
    r"study guide|notes|outline|table|spreadsheet|cheat sheet|review sheet|"
    r"mind[ -]?map|concept[ -]?map|topic[ -]?map)\b",
    re.IGNORECASE,
)

_DOCUMENT_REQUEST = re.compile(
    _LEAD + r"(?:(?:please|could you|can you|would you|will you)\s+)*"
    r"(?:write|draft|create|make|generate|prepare|produce|give me|"
    r"i (?:want|need|would like))\s+(?:me\s+)?(?:(?:a|an|the|some)\s+)?"
    r"(?:(?:short|brief|sample|editable|full|detailed|one[- ]page|"
    r"\d+[- ](?:word|page))\s+){0,4}"
    r"(?:essay|paper|document|study guide|(?:study|cheat|review) sheet|"
    r"notes|outline)\b",
    re.IGNORECASE,
)


_SMALL_TALK = re.compile(
    r"(?:(?:oh |ok |okay )?(?:hi|hello|hey|hiya|howdy|yo|sup|greetings"
    r"|good (?:morning|afternoon|evening|day))"
    r"(?: (?:there|again|tutor|everyone|all|stacks|friend))*"
    r"|(?:thanks|thank you|thx|ty|cheers)(?: (?:so much|a lot|very much|again|tutor))*"
    r"|ok|okay|k|cool|nice|great|awesome|perfect|got it|sounds good|makes sense"
    r"|i see|understood|bye|goodbye|see you(?: later)?|later|good night"
    r"|(?:echo|say) (?:hello|hi|hey|test|testing|world|hello world)"
    r"|(?:test|testing|ping)(?: (?:test|message|123|1 2 3|please))*"
    r"|how are you(?: doing)?|how is it going|how's it going|what's up|whats up"
    r"|are you (?:there|working|awake)|can you hear me|who are you|what are you"
    r"|what(?:'s| is) your name|what can you do|what do you do|how do you work"
    r"|how can you help(?: me)?|can you help(?: me)?|help(?: me)?"
    r"|what can i ask(?: you)?|what should i ask(?: you)?)",
    re.IGNORECASE,
)
_NOT_WORD = re.compile(r"[^\w\s']+")


def is_small_talk(question: str) -> bool:
    """A greeting, thanks, connection test or "what can you do?": the whole
    message, nothing else. Such a message has no course material to find, so
    it is answered directly instead of being searched for."""
    plain = " ".join(_NOT_WORD.sub(" ", question.replace("’", "'")).split())
    return bool(plain) and _SMALL_TALK.fullmatch(plain) is not None


def classify_intent(question: str) -> Intent:
    if _GRADED_WORK.search(question):
        return Intent.GRADED
    if is_small_talk(question):
        return Intent.CHAT
    if not _ARTIFACT_REQUEST.search(question):
        return Intent.ANSWER
    if _DOCUMENT_REQUEST.search(question):
        return Intent.DOCUMENT
    for intent, pattern in _INTENT_RULES:
        if pattern.search(question):
            return intent
    return Intent.ANSWER


# Words that ask for a kind of output rather than name a subject: "quiz me
# on the CPI" is about the CPI. What is left after removing them is what to
# search the course for; nothing left means "the course in general".
_REQUEST_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "some",
        "my",
        "me",
        "i",
        "you",
        "we",
        "please",
        "can",
        "could",
        "would",
        "will",
        "make",
        "create",
        "generate",
        "write",
        "draft",
        "build",
        "prepare",
        "produce",
        "give",
        "show",
        "turn",
        "convert",
        "format",
        "put",
        "organize",
        "want",
        "need",
        "like",
        "to",
        "quiz",
        "test",
        "tests",
        "suite",
        "suites",
        "flashcard",
        "flashcards",
        "flash",
        "card",
        "cards",
        "question",
        "questions",
        "practice",
        "problems",
        "multiple",
        "choice",
        "slide",
        "slides",
        "deck",
        "presentation",
        "table",
        "spreadsheet",
        "csv",
        "comparison",
        "chart",
        "sheet",
        "cheat",
        "review",
        "study",
        "guide",
        "notes",
        "outline",
        "document",
        "mind",
        "concept",
        "topic",
        "map",
        "mindmap",
        "summary",
        "code",
        "function",
        "program",
        "script",
        "python",
        "on",
        "about",
        "for",
        "of",
        "from",
        "covering",
        "cover",
        "covers",
        "over",
        "regarding",
        "related",
        "with",
        "into",
        "and",
        "or",
        "this",
        "that",
        "it",
        "these",
        "those",
        "all",
        "everything",
        "whole",
        "entire",
        "course",
        "class",
        "material",
        "materials",
        "sources",
        "source",
    }
)
_OVERVIEW_QUESTION = re.compile(
    r"\bwhat(?:'s| is| are)? (?:this|the|my) (?:course|class|material|materials|"
    r"syllabus|unit|sources?)\b(?: (?:is|are))? (?:about|cover|covers|covering)\b"
    r"|\bwhat (?:topics|subjects|things) (?:are|do(?:es)?|does)\b"
    r"|\bwhat (?:does|do) (?:this|the|my) (?:course|class|material|materials|"
    r"syllabus|sources?) (?:cover|include|contain)\b"
    r"|\boverview of (?:this|the|my) (?:course|class|material|materials)\b"
    r"|\bsummar(?:y|ize|ise) (?:of )?(?:this|the|my) (?:whole |entire )?"
    r"(?:course|class|material|materials|sources?)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[\w'-]+")


def retrieval_topic(question: str) -> str:
    """What to search the course for. A plain question is its own topic; a
    request for a quiz, notes, slides... is searched by its subject alone,
    because "make me a study guide" shares no words with the material it is
    about. Empty when the request names no subject."""
    if classify_intent(question) in (Intent.ANSWER, Intent.GRADED, Intent.CHAT):
        return question
    words = [w for w in _WORD.findall(question) if w.casefold() not in _REQUEST_WORDS]
    return " ".join(words)


def asks_for_overview(question: str) -> bool:
    """A question about the course as a whole ("what is this course about?"),
    which no single passage answers: it is answered from a spread of the
    material instead of the passages nearest to its wording."""
    return _OVERVIEW_QUESTION.search(question) is not None


class AnswerMode(StrEnum):
    """How a plain question is answered: `plain` asks for `[n]` markers;
    `quotes` asks for verified literal quotes first (tutor/quotes.py)."""

    PLAIN = "plain"
    QUOTES = "quotes"


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
    # The chunks the model read, in the order they were numbered: [1] is
    # candidates[0]. Citations, the trace and scoring all use this.
    candidates: tuple[Candidate, ...] = ()
    # Quote-anchored mode only: evidence that was / was not found verbatim
    # in the chunk it named. Rejected quotes are never shown.
    quotes: tuple[quote_anchors.Quote, ...] = ()
    rejected_quotes: tuple[quote_anchors.Quote, ...] = ()


def numbered_passages(candidates: tuple[Candidate, ...]) -> str:
    from src.backend.retrieval.labels import candidate_label

    blocks = []
    for index, candidate in enumerate(candidates):
        source_kind = (
            candidate.source_type.replace("_", " ") if candidate.source_type else ""
        )
        where = [
            part
            for part in (
                candidate.source_filename,
                source_kind,
                candidate.container_title,
                candidate_label(candidate),
            )
            if part
        ]
        header = f"[{index + 1}] chunk {candidate.chunk_id}"
        if where:
            header += " · " + " · ".join(where)
        if candidate.partial:
            header += (
                f" (partial passage: characters {candidate.window_start}–"
                f"{candidate.window_end} of {candidate.text_length}; "
                "incomplete logical unit)"
            )
        blocks.append(f"{header}\n{candidate.text}")
    return "\n\n".join(blocks)


def numbered_material(
    question: str, candidates: tuple[Candidate, ...], conversation: str = ""
) -> str:
    """Conversation context and numbered original evidence, inside the fence."""
    evidence = numbered_passages(candidates)
    material = f"Question: {question}\n\nCourse material:\n{evidence}"
    if conversation:
        return f"Conversation so far (context only):\n{conversation}\n\n{material}"
    return material


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


def workspace_schema(
    intent: Intent,
    material_count: int,
    quiz_count: int | None = None,
    *,
    slide_count: int | None = None,
) -> dict[str, Any]:
    sources = _sources_schema(material_count)
    items: dict[Intent, dict[str, Any]] = {
        Intent.MIND_MAP: _object(
            {
                "type": {"const": "mind_map"},
                "title": _string(120),
                "nodes": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 12,
                    "items": _object(
                        {
                            "id": _string(40),
                            "label": _string(100),
                            "summary": _string(300),
                            "sources": sources,
                        }
                    ),
                },
                "edges": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 18,
                    "items": _object(
                        {
                            "source": _string(40),
                            "target": _string(40),
                            "kind": {
                                "type": "string",
                                "enum": ["branch", "similarity"],
                            },
                            "label": _string(100),
                            "explanation": _string(300),
                            "sources": sources,
                        }
                    ),
                },
            }
        ),
        Intent.QUIZ: _object(
            {
                "type": {"const": "quiz"},
                "title": _string(120),
                "questions": {
                    "type": "array",
                    "minItems": quiz_count or 1,
                    "maxItems": quiz_count or 20,
                    "items": _object(
                        {
                            "prompt": _string(400),
                            "topic": _string(160),
                            "capability": {
                                "type": "string",
                                "enum": [
                                    "recognition",
                                    "explanation",
                                    "application",
                                    "counterexample",
                                    "transfer",
                                ],
                            },
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
                "sections": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": _object(
                        {
                            "heading": {"type": "string", "maxLength": 500},
                            "paragraphs": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 64,
                                "items": _string(20_000),
                            },
                        }
                    ),
                },
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
                "slides": {
                    "type": "array",
                    "minItems": slide_count or 1,
                    "maxItems": slide_count or 200,
                    "items": _object(
                        {
                            "title": _string(500),
                            "paragraphs": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 32,
                                "items": _string(20_000),
                            },
                        }
                    ),
                },
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


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in a model reply: the whole reply when the
    endpoint honoured the schema, a ```json fence or the outermost braces
    when it did not."""
    candidates = [text.strip()]
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


_SCHEMA_REMINDER = (
    "\n\nRespond with ONE JSON object only (no prose around it), shaped as: "
    '{"reply": "...", "item": {...}}.'
)

_PLACEHOLDER_OPTION = re.compile(
    r"^(?:option|answer|choice|distractor)\s*\d*\s*[.:)]?$|^(?:a|b|c|d)[.)]?$",
    re.IGNORECASE,
)
_GENERIC_QUIZ_PROMPT = re.compile(
    r"^(?:question about (?:the )?(?:topic|material|subject)|what is the answer)\??$",
    re.IGNORECASE,
)
_DATED_EVENT_VERBS = (
    frozenset({"begin", "began", "begun", "start", "started"}),
    frozenset({"found", "founded", "co-founded", "form", "formed"}),
    frozenset({"join", "joined"}),
    frozenset({"become", "became"}),
    frozenset({"end", "ended"}),
    frozenset({"sign", "signed"}),
    frozenset({"pass", "passed"}),
)
_QUIZ_UNAVAILABLE = (
    "I couldn't create a trustworthy quiz from these course passages. "
    "Try again with a different source or model."
)


def _requested_count(question: str, units: str) -> int | None:
    words = [
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
    ]
    counts = {word: index for index, word in enumerate(words, start=1)}
    match = re.search(
        r"\b(\d+|" + "|".join(words) + r")[ -]+(?:" + units + r")\b",
        question,
        re.IGNORECASE,
    )
    if match is None:
        return None
    count = match.group(1).casefold()
    return int(count) if count.isdigit() else counts[count]


def requested_quiz_count(question: str) -> int | None:
    return _requested_count(question, r"questions?|problems?")


def requested_slide_count(question: str) -> int | None:
    return _requested_count(question, r"slides?")


def _usable_quiz(item: dict[str, Any], candidates: tuple[Candidate, ...]) -> bool:
    """Reject schema-valid but content-free quiz scaffolding from small models."""
    if item.get("type") != "quiz":
        return False
    questions = item.get("questions")
    if not isinstance(questions, list) or not questions:
        return False
    seen_prompts: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            return False
        prompt = question.get("prompt")
        options = question.get("options")
        answer = question.get("answer")
        explanation = question.get("explanation")
        if (
            not isinstance(prompt, str)
            or len(prompt.strip()) < 12
            or _GENERIC_QUIZ_PROMPT.fullmatch(prompt.strip())
        ):
            return False
        prompt_key = " ".join(prompt.casefold().split())
        if prompt_key in seen_prompts:
            return False
        seen_prompts.add(prompt_key)
        if not isinstance(options, list) or len(options) < 2:
            return False
        if type(answer) is not int or not 0 <= answer < len(options):
            return False
        normalized = [
            re.sub(r"\s+", " ", str(option)).strip(" .,:;!?").casefold()
            for option in options
        ]
        if len(set(normalized)) != len(normalized):
            return False
        list_keys = []
        for option in normalized:
            parts = re.split(r"\s*(?:[,;]|\band\b)\s*", option)
            key = tuple(sorted(re.sub(r"^the\s+", "", p.strip()) for p in parts))
            if len(parts) > 1:
                list_keys.append(key)
        if len(set(list_keys)) != len(list_keys):
            return False
        selected_phrase = re.sub(r"^(?:the|a|an)\s+", "", normalized[answer])
        if len(selected_phrase) >= 8 and selected_phrase in prompt.casefold():
            return False
        if any(_PLACEHOLDER_OPTION.fullmatch(option) for option in normalized):
            return False
        topic = question.get("topic", "")
        if topic in (
            "recognition",
            "explanation",
            "application",
            "counterexample",
            "transfer",
        ) and not re.search(
            rf"\b{re.escape(topic)}\b",
            prompt.casefold() + " " + " ".join(c.text.casefold() for c in candidates),
        ):
            return False
        if isinstance(explanation, str):
            explained = explanation.casefold()
            named_options = [
                index
                for index, option in enumerate(normalized)
                if len(option) >= 4
                and re.search(rf"(?<!\w){re.escape(option)}(?!\w)", explained)
            ]
            if len(named_options) == 1 and named_options[0] != answer:
                return False
            shortened = [
                re.sub(r"^(?:the )?(?:function|map|transformation)\s+", "", option)
                for option in normalized
            ]
            named_shortened = [
                index
                for index, option in enumerate(shortened)
                if len(option) >= 12 and option in explained
            ]
            if len(named_shortened) == 1 and named_shortened[0] != answer:
                return False
        cited = question.get("sources")
        if not isinstance(cited, list) or not cited:
            return False
        if any(type(n) is not int or not 1 <= n <= len(candidates) for n in cited):
            return False
        evidence = " ".join(candidates[n - 1].text for n in cited).casefold()
        selected = str(options[answer])
        dates = re.findall(r"\b\d{4}\b", selected)
        if any(date not in evidence for date in dates):
            return False
        if dates and re.search(r"\b(?:when|what year|which year)\b", prompt.casefold()):
            question_words = set(re.findall(r"[\w-]+", prompt.casefold()))
            event_verbs = [
                forms for forms in _DATED_EVENT_VERBS if forms & question_words
            ]
            if event_verbs:
                dated_sentences = [
                    sentence
                    for sentence in re.split(r"(?<=[.!?])\s+", evidence)
                    if any(date in sentence for date in dates)
                ]
                if not any(
                    all(
                        any(
                            re.search(rf"(?<!\w){re.escape(form)}(?!\w)", sentence)
                            for form in forms
                        )
                        for forms in event_verbs
                    )
                    for sentence in dated_sentences
                ):
                    return False
        names = re.findall(r"\b[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ]+)+\b", selected)
        if names and not any(
            re.search(rf"(?<!\w){re.escape(word.casefold())}(?!\w)", evidence)
            for name in names
            for word in name.split()
            if len(word) >= 4
        ):
            return False
    return True


def _usable_quiz_questions(
    item: Any, candidates: tuple[Candidate, ...]
) -> list[dict[str, Any]]:
    if not isinstance(item, dict) or item.get("type") != "quiz":
        return []
    questions = item.get("questions")
    if not isinstance(questions, list):
        return []
    return [
        question
        for question in questions
        if isinstance(question, dict)
        and _usable_quiz({"type": "quiz", "questions": [question]}, candidates)
    ]


def _workspace_response(
    parsed: dict[str, Any] | None,
    intent: Intent,
    material_count: int,
    passages: list[str],
    *,
    slide_count: int | None = None,
) -> str | None:
    item = parsed.get("item") if parsed else None
    if not isinstance(item, dict) or item.get("type") != intent.value:
        return None
    try:
        if intent is Intent.DOCUMENT and "sections" in item:
            item = DocumentDraft.model_validate(item).workspace()
        elif intent is Intent.SLIDES and "slides" in item:
            item = DeckDraft.model_validate(item).workspace()
    except ValueError:
        return None
    if intent is Intent.MIND_MAP:
        try:
            original = extract_workspace_items(
                "```workspace\n" + json.dumps(item) + "\n```", material_count
            )
            if original.withheld:
                return None
            mapped = MindMapContent.model_validate(
                {k: v for k, v in item.items() if k in {"nodes", "edges"}}
            )
            anchored = anchor_map_evidence(mapped, passages)
            item = {**item, **anchored.model_dump()}
        except ValueError:
            return None
    content_key = {
        Intent.DOCUMENT: "content",
        Intent.SLIDES: "deck",
        Intent.CODE: "code",
    }.get(intent)
    if content_key is not None:
        content = item.get(content_key)
        if not isinstance(content, str) or content.strip(" .\t\n`").casefold() in {
            "",
            "content",
            "deck",
            "markdown",
            "code",
        }:
            return None
        if intent in (Intent.DOCUMENT, Intent.SLIDES):
            units = (
                re.split(r"^\s*---\s*$", content, flags=re.MULTILINE)
                if intent is Intent.SLIDES
                else [content]
            )
            if any(not has_body(unit, str(item.get("title", ""))) for unit in units):
                return None
            if intent is Intent.SLIDES and len({unit.strip() for unit in units}) != len(
                units
            ):
                return None
            if (
                intent is Intent.SLIDES
                and slide_count is not None
                and len(units) != slide_count
            ):
                return None
    reply_value = parsed.get("reply") if parsed else None
    reply = reply_value.strip() if isinstance(reply_value, str) else ""
    if any(number < 1 or number > material_count for number in cited_numbers(reply)):
        return None
    block = json.dumps(item, ensure_ascii=False)
    text = f"{reply}\n\n```workspace\n{block}\n```".strip()
    extracted = extract_workspace_items(text, material_count)
    return text if extracted.items and not extracted.withheld else None


@generation_control.operation()
def compose_answer(
    question: str,
    candidates: tuple[Candidate, ...],
    generate: Generate,
    *,
    on_schema_rejected: Callable[[Exception], bool] | None = None,
    select: Callable[[str, tuple[Candidate, ...]], tuple[Candidate, ...]] | None = None,
    answer_mode: AnswerMode = AnswerMode.PLAIN,
    conversation: str = "",
    teaching: str = "",
    scope_note: str = "",
) -> Composed:
    """Frame the task, generate, and return standard answer text.

    `on_schema_rejected(err)` decides whether a failed constrained call
    should be retried without the schema (an endpoint that rejects
    `response_format`); it returns False to re-raise. `scope_note` is
    trusted instruction text (not fenced data) prepended after a
    source-scope change, so an earlier answer from an excluded source is
    not treated as a fact (B-02)."""
    if select is not None:
        candidates = select(question, candidates)
    intent = classify_intent(question)
    quiz_count = requested_quiz_count(question) if intent is Intent.QUIZ else None
    slide_count = requested_slide_count(question) if intent is Intent.SLIDES else None
    if quiz_count is not None and not 1 <= quiz_count <= 20:
        return Composed(
            "A practice test supports 1–20 questions. Choose a count in that range.",
            intent,
            structured=False,
            candidates=candidates,
        )
    if quiz_count is not None:
        teaching += "\n" + load_prompt("workspace_quiz_count").format(count=quiz_count)
    if slide_count is not None and not 1 <= slide_count <= 200:
        return Composed(
            "A slide deck supports 1–200 slides. Choose a count in that range.",
            intent,
            structured=False,
            candidates=candidates,
        )
    material = numbered_material(question, candidates, conversation)
    if intent in (Intent.ANSWER, Intent.GRADED):
        teaching += "\n" + load_prompt("background_review")
    if scope_note:
        teaching = f"{scope_note}\n\n{teaching}" if teaching else scope_note
    if intent is Intent.ANSWER and answer_mode is AnswerMode.QUOTES:
        return _compose_quoted(
            material, candidates, generate, on_schema_rejected, teaching
        )
    if intent in (Intent.ANSWER, Intent.GRADED, Intent.CHAT):
        instruction = "tutor_steer" if intent is Intent.GRADED else "tutor_answer"
        prompt = grounded_prompt(load_prompt(instruction) + teaching, material)
        text = generate("tutor_answer", prompt)
        if any(n < 1 or n > len(candidates) for n in cited_numbers(text)):
            text = (
                "The answer referred to source material it was not given. "
                "Try again; this reply was withheld."
            )
        return Composed(
            strip_fence_echo(text), intent, structured=False, candidates=candidates
        )

    prompt = grounded_prompt(
        load_prompt(f"workspace_{intent.value}") + teaching, material
    )
    schema = workspace_schema(
        intent, len(candidates), quiz_count, slide_count=slide_count
    )
    try:
        raw = generate("artifact_generation", prompt, response_schema=schema)
    except Exception as err:
        if on_schema_rejected is None or not on_schema_rejected(err):
            raise
        raw = generate("artifact_generation", prompt + _SCHEMA_REMINDER)
    parsed = parse_json_object(raw)
    item = parsed.get("item") if parsed else None
    # The small local model can produce schema-valid but misleading quizzes.
    # Keep individually verified questions across attempts, while never
    # putting an untrustworthy answer key in the workspace or chat.
    if intent is Intent.QUIZ and (
        not isinstance(item, dict)
        or not _usable_quiz(item, candidates)
        or (quiz_count is not None and len(item.get("questions", [])) != quiz_count)
    ):
        accepted: list[dict[str, Any]] = []
        seen: set[tuple[tuple[int, ...], str]] = set()
        title = "Practice quiz"
        reply = "Here are the questions I could build from your course material."

        def collect(result: dict[str, Any] | None) -> None:
            nonlocal title
            if not result:
                return
            candidate_item = result.get("item")
            if not isinstance(candidate_item, dict):
                return
            for valid in _usable_quiz_questions(candidate_item, candidates):
                key = (
                    tuple(valid["sources"]),
                    str(valid["options"][valid["answer"]]).strip(" .,:;!?").casefold(),
                )
                if key in seen:
                    continue
                seen.add(key)
                accepted.append(valid)
                title = str(candidate_item.get("title") or title)

        collect(parsed)
        repair_instruction = (
            load_prompt("workspace_quiz")
            + "\n\n"
            + load_prompt("workspace_quiz_repair")
            + teaching
        )
        repair_prompt = grounded_prompt(repair_instruction, material)
        for _ in range(2):
            if len(accepted) >= (quiz_count or 2):
                break
            try:
                repaired = generate(
                    "artifact_generation", repair_prompt, response_schema=schema
                )
            except Exception as err:
                if on_schema_rejected is None or not on_schema_rejected(err):
                    raise
                else:
                    repaired = generate(
                        "artifact_generation", repair_prompt + _SCHEMA_REMINDER
                    )
            parsed = parse_json_object(repaired)
            item = parsed.get("item") if parsed else None
            collect(parsed)
        if not accepted:
            return Composed(
                _QUIZ_UNAVAILABLE,
                intent,
                structured=False,
                candidates=candidates,
            )
        if quiz_count is not None and len(accepted) < quiz_count:
            return Composed(
                f"I could verify only {len(accepted)} of the {quiz_count} "
                "requested questions, so I haven't published an incomplete test. "
                "Try a smaller test or a different source or model.",
                intent,
                structured=False,
                candidates=candidates,
            )
        item = {
            "type": "quiz",
            "title": title,
            "questions": accepted[:quiz_count]
            if quiz_count is not None
            else accepted[:20],
        }
        parsed = {"reply": reply, "item": item}
    passages = [c.text for c in candidates]
    workspace_text = _workspace_response(
        parsed, intent, len(candidates), passages, slide_count=slide_count
    )
    if workspace_text is None and intent is not Intent.QUIZ:
        repair_prompt = grounded_prompt(
            load_prompt(f"workspace_{intent.value}")
            + "\n\n"
            + load_prompt("workspace_repair")
            + teaching,
            material + "\n\nPrevious output to replace:\n" + raw,
        )
        try:
            repaired = generate(
                "artifact_generation", repair_prompt, response_schema=schema
            )
        except Exception as err:
            if on_schema_rejected is None or not on_schema_rejected(err):
                raise
            repaired = generate("artifact_generation", repair_prompt + _SCHEMA_REMINDER)
        workspace_text = _workspace_response(
            parse_json_object(repaired),
            intent,
            len(candidates),
            passages,
            slide_count=slide_count,
        )
    if workspace_text is None:
        return Composed(
            "I couldn't create a usable workspace item from this response. "
            "Try again with a smaller request or a different model.",
            intent,
            structured=False,
            candidates=candidates,
        )
    return Composed(
        strip_fence_echo(workspace_text), intent, structured=True, candidates=candidates
    )


def compose_chat(
    question: str,
    generate: Generate,
    *,
    conversation: str = "",
    course_name: str = "",
    teaching: str = "",
) -> str:
    """Reply to small talk (a greeting, thanks, a connection test, "what can
    you do?") without searching the course: there is nothing to look up, and
    refusing it as "nothing relevant found" made the tutor look broken."""
    parts: list[str] = []
    if course_name:
        parts.append(f"The student is studying: {course_name}")
    if conversation:
        parts.append(f"Conversation so far (context only):\n{conversation}")
    parts.append(f"Student message: {question}")
    instruction = load_prompt_policy().prompts["tutor_chat"].strip() + teaching
    prompt = grounded_prompt(instruction, "\n\n".join(parts))
    return strip_fence_echo(generate("tutor_answer", prompt))


def _compose_quoted(
    material: str,
    candidates: tuple[Candidate, ...],
    generate: Generate,
    on_schema_rejected: Callable[[Exception], bool] | None,
    teaching: str = "",
) -> Composed:
    """Quote-first answer: evidence, then the answer; quotes verified
    against their chunks. An endpoint that rejects the schema, or a reply
    that is not the requested JSON, falls back to the plain answer."""
    prompt = grounded_prompt(load_prompt("tutor_answer_quotes") + teaching, material)
    try:
        raw = generate(
            "tutor_answer",
            prompt,
            response_schema=quote_anchors.answer_schema(len(candidates)),
        )
    except Exception as err:
        if on_schema_rejected is None or not on_schema_rejected(err):
            raise
        raw = None
    parsed = parse_json_object(raw) if raw is not None else None
    answer = parsed.get("answer") if parsed else None
    if not isinstance(answer, str) or not answer.strip():
        text = generate(
            "tutor_answer",
            grounded_prompt(load_prompt("tutor_answer") + teaching, material),
        )
        if any(n < 1 or n > len(candidates) for n in cited_numbers(text)):
            text = (
                "The answer referred to source material it was not given. "
                "Try again; this reply was withheld."
            )
        return Composed(
            strip_fence_echo(text),
            Intent.ANSWER,
            structured=False,
            candidates=candidates,
        )
    verified, rejected = quote_anchors.verify(
        quote_anchors.parse_quotes(parsed.get("quotes") if parsed else None),
        tuple(candidate.text for candidate in candidates),
    )
    text = quote_anchors.anchor_citations(strip_fence_echo(answer.strip()), verified)
    if any(n < 1 or n > len(candidates) for n in cited_numbers(text)):
        text = (
            "The answer referred to source material it was not given. "
            "Try again; this reply was withheld."
        )
    return Composed(
        text,
        Intent.ANSWER,
        structured=True,
        candidates=candidates,
        quotes=tuple(verified),
        rejected_quotes=tuple(rejected),
    )
