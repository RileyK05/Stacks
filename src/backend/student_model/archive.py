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
    LearningExperiment,
    PracticeRun,
    PracticeSuite,
    TeachingMethod,
)
from src.backend.student_model import learning


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


class LearningArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suites: list[PracticeSuite] = Field(default_factory=list, max_length=10000)
    runs: list[PracticeRun] = Field(default_factory=list, max_length=10000)
    observations: list[Observation] = Field(default_factory=list, max_length=100000)
    experiments: list[LearningExperiment] = Field(
        default_factory=list, max_length=10000
    )
    assessments: list[Assessment] = Field(default_factory=list, max_length=10000)


def export_learning(conn: Connection, course_id: UUID) -> LearningArchive:
    suites = [
        PracticeSuite.model_validate(r)
        for r in learning.rows(conn, "suites", course_id=course_id)
    ]
    return LearningArchive(
        suites=suites,
        runs=[
            learning.run_view(conn, r)
            for r in learning.rows(conn, "runs", course_id=course_id)
        ],
        observations=[
            Observation.model_validate(r)
            for r in learning.rows(conn, "observations", course_id=course_id)
        ],
        experiments=learning.experiments(conn, course_id),
        assessments=[
            Assessment.model_validate(r)
            for s in suites
            for r in learning.rows(conn, "assessments", suite_id=s.suite_id)
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
    run_ids = {r.run_id for r in archive.runs} | {
        o.run_ref for o in archive.observations
    }
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
        if run.suite_id not in suite_map:
            raise ValueError("an archived attempt has no test suite")
        test = next(s for s in archive.suites if s.suite_id == run.suite_id)
        if (
            len(run.answers) != len(test.questions)
            or len(run.helped) != len(run.answers)
            or any(
                not 0 <= pick < len(q.options)
                for pick, q in zip(run.answers, test.questions, strict=True)
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
    return suite_map
