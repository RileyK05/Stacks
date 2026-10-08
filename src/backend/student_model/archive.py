from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from src.backend.common.db import Connection
from src.backend.common.queries import get
from src.backend.common.schemas.learning import (
    Capability,
    ContentFeedback,
    LearningExperiment,
    PracticeHelp,
    PracticeQuestion,
    PracticeRun,
    PracticeSuite,
    TeachingMethod,
)
from src.backend.student_model import inspection, learning


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: UUID
    course_id: UUID
    run_ref: UUID
    suite_ref: UUID
    question_index: int = Field(ge=0)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    topic: str = Field(min_length=1, max_length=5000)
    capability: Capability
    correct: bool | None
    helped: bool
    fresh: bool
    method: TeachingMethod | None
    evidence: dict[str, Any]
    created_at: datetime


class Assessment(BaseModel):
    suite_id: UUID
    question_index: int = Field(ge=0)
    answer: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=500)
    updated_at: datetime


class ArchivedHelp(PracticeHelp):
    suite_id: UUID
    run_ref: UUID
    context_key: str = ""
    updated_at: datetime


class LearningArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suites: list[PracticeSuite] = Field(default_factory=list, max_length=10000)
    runs: list[PracticeRun] = Field(default_factory=list, max_length=10000)
    observations: list[Observation] = Field(default_factory=list, max_length=100000)
    experiments: list[LearningExperiment] = Field(
        default_factory=list, max_length=10000
    )
    assessments: list[Assessment] = Field(default_factory=list, max_length=10000)
    help: list[ArchivedHelp] = Field(default_factory=list, max_length=100000)
    feedback: list[ContentFeedback] = Field(default_factory=list, max_length=100000)


def _response_fits(pick: int | str, question: PracticeQuestion) -> bool:
    if question.format == "short_answer":
        return isinstance(pick, str) and bool(pick.strip()) and len(pick) <= 5000
    return type(pick) is int and 0 <= pick < len(question.options)


def export_learning(conn: Connection, course_id: UUID) -> LearningArchive:
    suites = [
        PracticeSuite.model_validate(r)
        for r in inspection.rows(conn, "suites", course_id=course_id)
    ]
    return LearningArchive(
        suites=suites,
        help=[
            ArchivedHelp.model_validate(r)
            for r in conn.execute(
                get("practice_support", "exported_help"), {"course_id": course_id}
            )
        ],
        feedback=[
            ContentFeedback.model_validate(r)
            for r in conn.execute(
                get("practice_support", "exported_feedback"), {"course_id": course_id}
            )
        ],
        runs=[
            learning.run_view(conn, r)
            for r in inspection.rows(conn, "runs", course_id=course_id)
        ],
        observations=[
            Observation.model_validate(r)
            for r in inspection.rows(conn, "observations", course_id=course_id)
        ],
        experiments=inspection.experiments(conn, course_id),
        assessments=[
            Assessment.model_validate(r)
            for s in suites
            for r in inspection.rows(conn, "assessments", suite_id=s.suite_id)
        ],
    )


def import_learning(
    conn: Connection,
    course_id: UUID,
    archive: LearningArchive,
    source_map: dict[UUID, UUID],
    chunk_map: dict[UUID, UUID],
) -> dict[UUID, UUID]:
    suite_map = {s.suite_id: uuid4() for s in archive.suites}
    run_ids = (
        {r.run_id for r in archive.runs}
        | {o.run_ref for o in archive.observations}
        | {h.run_ref for h in archive.help}
    )
    run_map = {old: uuid4() for old in run_ids}

    def evidence(value: Any) -> Any:
        if isinstance(value, list):
            return [evidence(item) for item in value]
        if isinstance(value, dict):
            mapped = {key: evidence(item) for key, item in value.items()}
            for key, mapping in (
                ("source_id", source_map),
                ("chunk_id", chunk_map),
                ("suite_id", suite_map),
                ("run_id", run_map),
            ):
                raw = mapped.get(key)
                if isinstance(raw, str):
                    try:
                        old = UUID(raw)
                    except ValueError:
                        continue
                    mapped[key] = str(mapping.get(old, old))
            return mapped
        return value

    def insert(name: str, record: BaseModel, **changes: Any) -> None:
        values = record.model_dump() | changes
        for key in (
            "questions",
            "evidence",
            "origin",
            "answers",
            "helped",
            "requested_help",
        ):
            if key in values and isinstance(values[key], (list, dict)):
                values[key] = json.dumps(evidence(values[key]), default=str)
        conn.execute(get("learning", name), values)

    for suite in archive.suites:
        insert(
            "import_suite",
            suite,
            suite_id=suite_map[suite.suite_id],
            course_id=course_id,
            origin={"imported_suite": str(suite.suite_id), **suite.origin},
        )
    for run in archive.runs:
        test = next((s for s in archive.suites if s.suite_id == run.suite_id), None)
        if test is None or run.suite_id not in suite_map:
            raise ValueError("an archived attempt has no test suite")
        if (
            len(run.answers) != len(test.questions)
            or len(run.helped) != len(run.answers)
            or any(
                not _response_fits(pick, question)
                for pick, question in zip(run.answers, test.questions, strict=True)
            )
        ):
            raise ValueError("an archived test has invalid responses")
        insert(
            "import_run",
            run,
            run_id=run_map[run.run_id],
            suite_id=suite_map[run.suite_id],
            course_id=course_id,
            requested_help=run.helped,
        )
    for observation in archive.observations:
        if observation.suite_ref not in suite_map:
            raise ValueError("an archived observation has no test suite")
        test = next(s for s in archive.suites if s.suite_id == observation.suite_ref)
        if observation.question_index >= len(test.questions):
            raise ValueError("an archived observation has no matching question")
        insert(
            "import_observation",
            observation,
            observation_id=uuid4(),
            course_id=course_id,
            suite_ref=suite_map[observation.suite_ref],
            run_ref=run_map[observation.run_ref],
        )
    for experiment in archive.experiments:
        insert(
            "import_experiment", experiment, experiment_id=uuid4(), course_id=course_id
        )
    for assessment in archive.assessments:
        if assessment.suite_id not in suite_map:
            raise ValueError("an archived assessment has no test suite")
        test = next(s for s in archive.suites if s.suite_id == assessment.suite_id)
        if assessment.question_index >= len(test.questions) or (
            assessment.answer is not None
            and assessment.answer
            >= len(test.questions[assessment.question_index].options)
        ):
            raise ValueError("an archived answer key is invalid")
        insert(
            "correct_assessment", assessment, suite_id=suite_map[assessment.suite_id]
        )
    help_map = {h.help_id: uuid4() for h in archive.help}
    for help_record in archive.help:
        if help_record.suite_id not in suite_map:
            raise ValueError("archived help has no test suite")
        test = next(s for s in archive.suites if s.suite_id == help_record.suite_id)
        if not 0 <= help_record.question_index < len(test.questions) or any(
            n not in test.questions[help_record.question_index].sources
            for n in help_record.content.sources
        ):
            raise ValueError("archived help has invalid question or sources")
        values = help_record.model_dump() | {
            "help_id": help_map[help_record.help_id],
            "suite_id": suite_map[help_record.suite_id],
            "run_ref": run_map[help_record.run_ref],
            "claim": uuid4(),
            "content": help_record.content.model_dump_json(),
        }
        conn.execute(get("practice_support", "import_help"), values)
    for rating in archive.feedback:
        if rating.suite_id not in suite_map:
            raise ValueError("archived feedback has no test suite")
        test = next(s for s in archive.suites if s.suite_id == rating.suite_id)
        linked = next((h for h in archive.help if h.help_id == rating.help_id), None)
        if (
            not 0 <= rating.question_index < len(test.questions)
            or (
                rating.target != "question"
                and (
                    linked is None
                    or linked.suite_id != rating.suite_id
                    or linked.question_index != rating.question_index
                    or linked.kind != rating.target
                )
            )
            or (rating.target == "question" and rating.help_id is not None)
            or rating.rating is None
        ):
            raise ValueError("archived feedback has invalid content target")
        conn.execute(
            get("practice_support", "import_feedback"),
            rating.model_dump()
            | {
                "suite_id": suite_map[rating.suite_id],
                "help_id": help_map.get(rating.help_id) if rating.help_id else None,
            },
        )
    return suite_map
