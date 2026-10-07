"""Practice questions in the style of an uploaded quiz or exam.

The upload is read for topics, difficulty, and question formats. It is not
stored as a course source and its questions are not answered. New questions
are written from the course's own passages, then dropped when they reuse a
run of the upload's wording. A copied explanation is cleared. A copied
required point is removed.
"""

from __future__ import annotations

import io
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from src.backend.artifacts import content as artifact_content
from src.backend.common import artifacts_repo, provider
from src.backend.common.companion_config import load_companion_policy
from src.backend.common.db import connection
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.prompt_registry import grounded_prompt, load_prompt
from src.backend.ingest import extract
from src.backend.ingest.ocr_pages import split_ocr_pages
from src.backend.retrieval import funnel
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.retrieval.funnel import Candidate
from src.backend.student_model.grading import content_words, point_covered
from src.backend.tutor.answer import embed_search
from src.backend.tutor.compose import (
    _shuffle_quiz_options,
    _usable_quiz,
    parse_json_object,
)

MAX_PAGES = 8
MAX_QUESTIONS = 12
MAX_EXEMPLAR_CHARS = 16_000
OCR_SCALE = 1.5
OCR_MAX_PIXELS = 8_000_000
_WORD = re.compile(r"[a-z0-9]+")
_CAPABILITIES = (
    "recognition",
    "explanation",
    "application",
    "counterexample",
    "transfer",
)
_FORMATS = ("multiple_choice", "short_answer", "multi_part")


class ExamStyleError(ValueError):
    """The upload cannot become practice questions."""


class StyleItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    format: Literal["multiple_choice", "short_answer", "multi_part"]
    parts: list[Literal["multiple_choice", "short_answer"]] = Field(
        default_factory=list, max_length=4
    )


class StyleProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topics: list[str] = Field(min_length=1, max_length=8)
    difficulty: Literal["recognition", "explanation", "application", "mixed"] = "mixed"
    style: str = Field(default="", max_length=400)
    items: list[StyleItem] = Field(min_length=1, max_length=8)


def upload_limit() -> int:
    return load_companion_policy().max_upload_bytes


def sniff_upload(raw: bytes) -> Literal["pdf", "image"]:
    if raw.startswith(b"%PDF"):
        return "pdf"
    if (
        raw.startswith(b"\x89PNG\r\n\x1a\n")
        or raw.startswith(b"\xff\xd8\xff")
        or (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
    ):
        return "image"
    raise ExamStyleError("Upload a PDF, PNG, JPEG, or WebP of the quiz or exam.")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _shingles(words: list[str], size: int = 6) -> set[str]:
    if len(words) < size:
        return set()
    return {
        " ".join(words[index : index + size]) for index in range(len(words) - size + 1)
    }


def copies_exemplar(text: str, exemplar: str) -> bool:
    """True when `text` repeats a six-word run from the upload, or is a long
    stretch that appears inside it. Short topic names are not copies."""
    words = _words(text)
    source = _words(exemplar)
    if len(words) >= 6 and _shingles(words) & _shingles(source):
        return True
    return len(words) >= 8 and " ".join(words) in " ".join(source)


def _png_from_photo(raw: bytes) -> bytes:
    from PIL import Image

    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 20_000_000
    try:
        with Image.open(io.BytesIO(raw)) as image:
            converted = image.convert("RGB")
            if converted.width * converted.height > OCR_MAX_PIXELS:
                raise ExamStyleError(
                    "This photo is too large to read. Use a smaller image."
                )
            buffer = io.BytesIO()
            converted.save(buffer, format="PNG")
            return buffer.getvalue()
    except ExamStyleError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as err:
        raise ExamStyleError("This image could not be read.") from err
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def _transcribe(
    course_id: UUID, images: list[bytes], *, skip_unreadable: bool = False
) -> list[str]:
    if not images:
        return []
    try:
        result = provider.generate(
            "ocr",
            load_prompt("ocr"),
            course_id=course_id,
            images=images,
        )
        return split_ocr_pages(result.text, len(images))
    except provider.ProviderUnavailableError:
        raise
    except ValueError:
        if len(images) == 1:
            if skip_unreadable:
                return [""]
            raise ExamStyleError(
                "The scan could not be read. Try a clearer photo "
                "or a PDF with selectable text."
            ) from None
        return [
            text
            for image in images
            for text in _transcribe(course_id, [image], skip_unreadable=skip_unreadable)
        ]


def read_upload(course_id: UUID, kind: Literal["pdf", "image"], raw: bytes) -> str:
    if kind == "image":
        pages = _transcribe(course_id, [_png_from_photo(raw)])
        text = "\n\n".join(page.strip() for page in pages if page.strip())
    else:
        text = _read_pdf(course_id, raw)
    text = text.strip()
    if len(_words(text)) < 12:
        raise ExamStyleError(
            "Not enough text could be read from that file to describe its questions."
        )
    if len(text) > MAX_EXEMPLAR_CHARS:
        text = text[:MAX_EXEMPLAR_CHARS]
    return text


def _read_pdf(course_id: UUID, raw: bytes) -> str:
    try:
        pages = extract.pdf_page_plain_text(raw)
    except Exception as err:
        raise ExamStyleError("This PDF could not be read.") from err
    if not pages:
        raise ExamStyleError("This PDF has no pages.")
    pages = pages[:MAX_PAGES]
    empty = [index for index, text in enumerate(pages) if not text.strip()]
    recognized: dict[int, str] = {}
    if empty:
        try:
            rendered = extract.rasterize_pdf_bytes(
                raw,
                max_pages=len(empty),
                scale=OCR_SCALE,
                pages=empty,
                max_pixels=OCR_MAX_PIXELS,
            )
        except (OSError, RuntimeError, ValueError) as err:
            if any(text.strip() for text in pages):
                rendered = []
            else:
                raise ExamStyleError("This scanned PDF could not be read.") from err
        if rendered:
            for index, text in zip(
                [page.page_index for page in rendered],
                _transcribe(
                    course_id,
                    [page.image for page in rendered],
                    skip_unreadable=True,
                ),
                strict=True,
            ):
                recognized[index] = text
    parts = [
        (recognized.get(index) or text).strip() for index, text in enumerate(pages)
    ]
    return "\n\n".join(part for part in parts if part)


def _clean_topic(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:80]


def profile_from_model(raw: object) -> StyleProfile:
    if not isinstance(raw, dict):
        raise ExamStyleError("The quiz's style could not be read. Try again.")
    topics = [
        topic
        for topic in (_clean_topic(item) for item in raw.get("topics") or [])
        if topic
    ][:8]
    difficulty = raw.get("difficulty")
    if difficulty not in {"recognition", "explanation", "application", "mixed"}:
        difficulty = "mixed"
    style_raw = raw.get("style")
    style = style_raw if isinstance(style_raw, str) else ""
    items: list[dict[str, Any]] = []
    for item in (raw.get("items") or [])[:8]:
        fmt: str
        parts: list[Any]
        if isinstance(item, str):
            fmt, parts = item, []
        elif isinstance(item, dict):
            raw_fmt = item.get("format")
            fmt = raw_fmt if isinstance(raw_fmt, str) else ""
            raw_parts = item.get("parts")
            parts = raw_parts if isinstance(raw_parts, list) else []
        else:
            continue
        if fmt not in _FORMATS:
            continue
        kept = [part for part in parts if part in {"multiple_choice", "short_answer"}][
            :4
        ]
        if fmt == "multi_part" and not kept:
            continue
        items.append({"format": fmt, "parts": kept})
    try:
        return StyleProfile.model_validate(
            {
                "topics": topics,
                "difficulty": difficulty,
                "style": " ".join(style.split())[:400],
                "items": items,
            }
        )
    except ValidationError as err:
        raise ExamStyleError("That file does not look like a quiz or exam.") from err


_FALLBACK_STYLE = (
    "Match the listed formats and difficulty. Ask about the listed topics in a new way."
)
_FALLBACK_TOPIC = "Course material"


def _safe_profile(profile: StyleProfile, exemplar: str) -> StyleProfile:
    """Keep the upload's wording out of the saved profile (origin, title,
    and each question's topic)."""
    update: dict[str, Any] = {}
    if copies_exemplar(profile.style, exemplar):
        update["style"] = _FALLBACK_STYLE
    topics = [topic for topic in profile.topics if not copies_exemplar(topic, exemplar)]
    if not topics:
        update["topics"] = [_FALLBACK_TOPIC]
    elif len(topics) != len(profile.topics):
        update["topics"] = topics
    return profile.model_copy(update=update) if update else profile


def describe_style(course_id: UUID, exemplar: str) -> StyleProfile:
    try:
        result = provider.generate(
            "artifact_generation",
            grounded_prompt(load_prompt("exam_style_profile"), exemplar),
            course_id=course_id,
            response_schema=StyleProfile.model_json_schema(),
        )
    except provider.ProviderRequestRejectedError:
        result = provider.generate(
            "artifact_generation",
            grounded_prompt(load_prompt("exam_style_profile"), exemplar),
            course_id=course_id,
        )
    parsed = parse_json_object(result.text)
    return _safe_profile(profile_from_model(parsed), exemplar)


def _passages(course_id: UUID, topics: list[str]) -> tuple[Candidate, ...]:
    query = " ".join(topics)[:500]
    policy = load_retrieval_policy()
    with connection() as conn:
        found = funnel.retrieve(
            conn,
            course_id,
            query,
            policy,
            query_embedding=embed_search(query),
            embedding_model=load_embedding_policy().model,
        )
    return found.candidates


def _numbered(candidates: tuple[Candidate, ...]) -> str:
    blocks = []
    for number, candidate in enumerate(candidates, start=1):
        label = candidate.source_filename or "source"
        blocks.append(f"[{number}] {label}\n{candidate.text[:1500]}")
    return "\n\n".join(blocks)


def _grounded(text: str, evidence: str) -> bool:
    """The same mechanical check as short-answer grading, so a point that
    says the opposite of the passage, or a different short number, is dropped."""
    return point_covered(evidence, text)


def _topic_for(raw: str, topics: list[str]) -> str:
    folded = {topic.casefold(): topic for topic in topics}
    if raw.casefold() in folded:
        return folded[raw.casefold()]
    wanted = set(content_words(raw))
    best = max(
        topics,
        key=lambda topic: len(wanted & set(content_words(topic))),
        default=topics[0],
    )
    if wanted and wanted & set(content_words(best)):
        return best
    return topics[0]


def _capability(raw: object, difficulty: str) -> str:
    if isinstance(raw, str) and raw in _CAPABILITIES:
        return raw
    if difficulty in _CAPABILITIES:
        return difficulty
    return "recognition"


def _inherited(part: dict[str, Any], parent: dict[str, Any], key: str) -> object:
    """A nested part keeps its own value, and otherwise the shared item's."""
    value = part.get(key)
    if value is None or value == "" or value == []:
        return parent.get(key)
    return value


def _flatten(raw_questions: object) -> list[dict[str, Any]]:
    if not isinstance(raw_questions, list):
        return []
    flat: list[dict[str, Any]] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        parts = item.get("parts")
        if item.get("format") == "multi_part" and isinstance(parts, list):
            stem = item.get("stem") if isinstance(item.get("stem"), str) else ""
            for offset, part in enumerate(parts[:4]):
                if not isinstance(part, dict):
                    continue
                flat.append(
                    {
                        **part,
                        "stem": part.get("stem") or stem,
                        "part": part.get("part") or chr(ord("a") + offset),
                        "sources": _inherited(part, item, "sources"),
                        "topic": _inherited(part, item, "topic"),
                        "explanation": _inherited(part, item, "explanation"),
                        "capability": _inherited(part, item, "capability"),
                    }
                )
            continue
        flat.append(item)
        if len(flat) >= MAX_QUESTIONS:
            break
    return flat[:MAX_QUESTIONS]


def _usable_short(question: dict[str, Any], candidates: tuple[Candidate, ...]) -> bool:
    prompt = question.get("prompt")
    expected = question.get("expected")
    points = question.get("points")
    cited = question.get("sources")
    if (
        not isinstance(prompt, str)
        or len(prompt.strip()) < 12
        or not isinstance(expected, str)
        or len(expected.strip()) < 2
        or not isinstance(points, list)
        or not 1 <= len(points) <= 6
        or not isinstance(cited, list)
        or not cited
    ):
        return False
    if any(
        type(number) is not int or not 1 <= number <= len(candidates)
        for number in cited
    ):
        return False
    evidence = " ".join(candidates[number - 1].text for number in cited)
    if not all(
        isinstance(point, str) and _grounded(point, evidence) for point in points
    ):
        return False
    return point_covered(evidence, expected)


def _fit_question(question: dict[str, Any]) -> dict[str, Any] | None:
    """Drop a question when one field cannot be stored. Labels can be shortened."""
    prompt = question.get("prompt")
    stem = question.get("stem") or ""
    expected = question.get("expected") or ""
    if (
        not isinstance(prompt, str)
        or len(prompt) > 5000
        or not isinstance(stem, str)
        or len(stem) > 2000
        or not isinstance(expected, str)
        or len(expected) > 5000
    ):
        return None
    raw_points = question.get("points") or []
    if not isinstance(raw_points, list) or any(
        not isinstance(point, str) or len(point) > 300 for point in raw_points
    ):
        return None
    raw_part = question.get("part")
    raw_explanation = question.get("explanation")
    raw_topic = question.get("topic")
    part = raw_part.strip()[:8] if isinstance(raw_part, str) else ""
    explanation = raw_explanation[:5000] if isinstance(raw_explanation, str) else ""
    topic = raw_topic[:160] if isinstance(raw_topic, str) else ""
    return {**question, "part": part, "explanation": explanation, "topic": topic}


def accept_questions(
    raw_questions: object,
    profile: StyleProfile,
    candidates: tuple[Candidate, ...],
    exemplar: str,
) -> list[dict[str, Any]]:
    if not isinstance(raw_questions, list):
        raise ExamStyleError("The model's new questions could not be read. Try again.")
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    repeated = False
    for item in _flatten(raw_questions):
        fmt = item.get("format")
        if fmt not in {"multiple_choice", "short_answer"}:
            fmt = "short_answer" if item.get("points") else "multiple_choice"
        raw_prompt = item.get("prompt")
        prompt = raw_prompt if isinstance(raw_prompt, str) else ""
        raw_stem = item.get("stem")
        stem = raw_stem if isinstance(raw_stem, str) else ""
        if copies_exemplar(prompt, exemplar) or copies_exemplar(stem, exemplar):
            repeated = True
            continue
        if fmt == "multiple_choice" and any(
            isinstance(option, str) and copies_exemplar(option, exemplar)
            for option in item.get("options") or []
        ):
            repeated = True
            continue
        if (
            fmt == "short_answer"
            and isinstance(item.get("expected"), str)
            and copies_exemplar(item["expected"], exemplar)
        ):
            repeated = True
            continue
        raw_explanation = item.get("explanation")
        explanation = (
            ""
            if not isinstance(raw_explanation, str)
            or copies_exemplar(raw_explanation, exemplar)
            else raw_explanation.strip()
        )
        raw_points = item.get("points")
        points: list[object] = []
        for point in raw_points if isinstance(raw_points, list) else []:
            if isinstance(point, str) and copies_exemplar(point, exemplar):
                repeated = True
                continue
            points.append(point)
        key = " ".join(_words(prompt))
        if not key or key in seen:
            continue
        raw_topic = item.get("topic")
        topic = _topic_for(
            raw_topic if isinstance(raw_topic, str) else "",
            profile.topics,
        )
        capability = _capability(item.get("capability"), profile.difficulty)
        if fmt == "multiple_choice":
            candidate = {
                "type": "quiz",
                "questions": [
                    {
                        "prompt": prompt,
                        "options": item.get("options"),
                        "answer": item.get("answer"),
                        "explanation": explanation,
                        "sources": item.get("sources"),
                        "topic": topic,
                        "capability": capability,
                    }
                ],
            }
            if not _usable_quiz(candidate, candidates):
                continue
            question = _shuffle_quiz_options(candidate)["questions"][0]
            question = {
                "format": "multiple_choice",
                "stem": stem.strip(),
                "part": item.get("part") if isinstance(item.get("part"), str) else "",
                "expected": "",
                "points": [],
                **question,
            }
        else:
            question = {
                "format": "short_answer",
                "prompt": prompt.strip(),
                "stem": stem.strip(),
                "part": item.get("part") if isinstance(item.get("part"), str) else "",
                "options": [],
                "answer": 0,
                "expected": str(item.get("expected") or "").strip(),
                "points": [
                    " ".join(str(point).split())
                    for point in points
                    if str(point).strip()
                ],
                "explanation": explanation,
                "sources": item.get("sources"),
                "topic": topic,
                "capability": capability,
            }
            if not _usable_short(question, candidates):
                continue
        fitted = _fit_question(question)
        if fitted is None:
            continue
        seen.add(key)
        accepted.append(fitted)
    if not accepted:
        if repeated:
            raise ExamStyleError(
                "No new questions could be written without repeating the uploaded exam."
            )
        raise ExamStyleError(
            "No usable new questions could be written from the course material "
            "for that quiz's topics."
        )
    return accepted


def _material(profile: StyleProfile, candidates: tuple[Candidate, ...]) -> str:
    profile_text = profile.model_dump_json()
    return (
        f"STYLE PROFILE\n{profile_text}\n\n"
        f"NUMBERED COURSE MATERIAL\n{_numbered(candidates)}"
    )


def write_questions(
    course_id: UUID,
    profile: StyleProfile,
    candidates: tuple[Candidate, ...],
    exemplar: str,
) -> list[dict[str, Any]]:
    instruction = load_prompt("exam_style_quiz")
    result = provider.generate(
        "artifact_generation",
        grounded_prompt(instruction, _material(profile, candidates)),
        course_id=course_id,
    )
    parsed = parse_json_object(result.text)
    if parsed is None:
        raise ExamStyleError("The model's new questions could not be read. Try again.")
    return accept_questions(parsed.get("questions"), profile, candidates, exemplar)


def _title(profile: StyleProfile) -> str:
    topic = profile.topics[0]
    title = f"Exam-style practice: {topic}"
    return title[: artifacts_repo.TITLE_MAX_LENGTH]


def create_practice(
    course_id: UUID,
    *,
    filename: str,
    raw: bytes,
) -> artifacts_repo.Artifact:
    if not raw:
        raise ExamStyleError("The file is empty.")
    if len(raw) > upload_limit():
        raise ExamStyleError("This file is too large to read as a quiz.")
    kind = sniff_upload(raw)
    exemplar = read_upload(course_id, kind, raw)
    profile = describe_style(course_id, exemplar)
    candidates = _passages(course_id, profile.topics)
    if not candidates:
        raise ExamStyleError(
            "Nothing in this course matches the topics on that quiz. "
            "Index the materials those questions are about, then try again."
        )
    questions = write_questions(course_id, profile, candidates, exemplar)
    try:
        body = artifact_content.validate_content("quiz", {"questions": questions})
        body, sources = artifact_content.compact(
            body, [candidate.chunk_id for candidate in candidates]
        )
    except (ValidationError, ValueError) as err:
        raise ExamStyleError(
            "The new questions were not valid practice items, so nothing was saved."
        ) from err
    safe_name = filename.rsplit("\\", 1)[-1].rsplit("/", 1)[-1][:200]
    return artifacts_repo.create(
        course_id,
        kind="quiz",
        title=_title(profile),
        content=body,
        sources=sources,
        origin={
            "exam_style": {
                "filename": safe_name,
                "topics": profile.topics,
                "difficulty": profile.difficulty,
                "style": profile.style,
                "formats": [item.format for item in profile.items],
            }
        },
        author="model",
        note=(
            "New questions in the style of an uploaded quiz. "
            "The upload was not added to course sources."
        ),
    )
