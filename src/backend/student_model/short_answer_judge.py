"""Model check for written answers the word matcher could not credit.

`grading.missed_points` is strict by design: it credits a point only when
the answer restates it in nearly the same words, so a student who writes the
right idea in their own words ("enslaving Native people was already illegal,
so no law ever ended it") is marked wrong. Before a run is stored, each point
the matcher missed is shown to the user's interactive model with the
question, the model answer and the student's text; points it judges covered
are saved with the run (`practice_runs.judged_points`) and count as covered.

Nothing here can mark an answer wrong: the matcher's credit always stands,
and a failed or malformed model call leaves its verdict unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from src.backend.common import provider
from src.backend.common.prompt_registry import grounded_prompt, load_prompt_policy
from src.backend.common.schemas.learning import PracticeSuite
from src.backend.student_model.grading import missed_points

logger = logging.getLogger(__name__)

TASK = "answer_grading"


def _schema(count: int) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["points"],
        "properties": {
            "points": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["index", "covered"],
                    "properties": {
                        "index": {"type": "integer", "minimum": 0},
                        "covered": {"type": "boolean"},
                    },
                },
            }
        },
    }


def _parse(text: str, points: list[str]) -> list[str]:
    from src.backend.tutor.compose import parse_json_object

    parsed = parse_json_object(text) or {}
    verdicts = parsed.get("points")
    if not isinstance(verdicts, list):
        return []
    covered: list[str] = []
    for verdict in verdicts:
        if not isinstance(verdict, dict) or verdict.get("covered") is not True:
            continue
        index = verdict.get("index")
        if type(index) is int and 0 <= index < len(points):
            covered.append(points[index])
    return covered


def judge(
    course_id: UUID, test: PracticeSuite, answers: list[int | str]
) -> dict[str, list[str]]:
    """Required points the model credits, by question index, for written
    answers the matcher did not fully credit."""
    instruction = load_prompt_policy().prompts["short_answer_grading"].strip()
    judged: dict[str, list[str]] = {}
    for index, question in enumerate(test.questions):
        if question.format != "short_answer" or index >= len(answers):
            continue
        answer = answers[index]
        if not isinstance(answer, str) or not answer.strip():
            continue
        missing = missed_points(answer, question.points)
        if not missing:
            continue
        material = json.dumps(
            {
                "question": question.prompt,
                "model_answer": question.expected,
                "required_points": [
                    {"index": n, "point": point} for n, point in enumerate(missing)
                ],
                "student_answer": answer,
            },
            ensure_ascii=False,
        )
        try:
            reply = provider.generate(
                TASK,
                grounded_prompt(instruction, material),
                course_id=course_id,
                response_schema=_schema(len(missing)),
            )
        except Exception:
            logger.warning("short-answer check failed; the matcher's grade stands")
            continue
        covered = _parse(reply.text, missing)
        if covered:
            judged[str(index)] = covered
    return judged
