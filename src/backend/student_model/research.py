from __future__ import annotations

import json
import logging
from datetime import timedelta
from uuid import UUID, uuid4

from src.backend.common import courses_repo, provider
from src.backend.common.db import connection, utc_now
from src.backend.common.learning_config import load_learning_policy
from src.backend.common.prompt_registry import grounded_prompt, load_prompt
from src.backend.common.providers import ProviderChoice
from src.backend.common.queries import get
from src.backend.common.schemas.learning import ResearchResult
from src.backend.student_model import inspection, learning
from src.backend.tutor.compose import parse_json_object

logger = logging.getLogger(__name__)


def inspect_exchange(
    course_id: UUID,
    message_id: UUID,
    question: str,
    reply: str,
    chunk_ids: tuple[UUID, ...],
    choice: ProviderChoice | None,
) -> None:
    if not chunk_ids:
        return
    signs = (
        "confus",
        "struggl",
        "don't understand",
        "do not understand",
        "can't",
        "cannot",
        "missed",
        "still don't",
        "not sure",
    )
    if len(question.split()) < 40 and not any(
        sign in question.casefold() for sign in signs
    ):
        return
    try:
        with connection() as conn:
            evidence = learning.evidence_for(conn, chunk_ids)
            existing = inspection.experiments(conn, course_id)
        if len(evidence) != len(chunk_ids):
            return
        policy = load_learning_policy().practice
        if (
            sum(
                e.status in ("proposed", "cooldown") and e.expires_at > utc_now()
                for e in existing
            )
            >= policy.max_open_experiments
        ):
            return
        material = json.dumps(
            {
                "student_message": question,
                "tutor_reply": reply[:3000],
                "numbered_passages": [
                    {"number": i + 1, "text": e["text"]} for i, e in enumerate(evidence)
                ],
            },
            default=str,
        )
        schema = ResearchResult.model_json_schema()
        schema["$defs"]["ResearchHypothesis"]["properties"]["sources"]["items"].update(
            minimum=1, maximum=len(evidence)
        )
        generation = provider.generate(
            "learning_research",
            grounded_prompt(load_prompt("learning_research"), material),
            course_id=course_id,
            choice=choice,
            response_schema=schema,
        )
        result = ResearchResult.model_validate(parse_json_object(generation.text))
        with connection() as conn:
            # The chat or course can be removed while the model is working.
            if courses_repo.get_course(course_id) is None:
                return
            for proposal in result.experiments:
                if proposal.student_quote not in question or any(
                    not 1 <= n <= len(evidence) for n in proposal.sources
                ):
                    continue
                if any(
                    e.topic.casefold() == proposal.topic.casefold()
                    and e.capability == proposal.capability
                    for e in existing
                ):
                    continue
                selected = [evidence[n - 1] for n in proposal.sources]
                conn.execute(
                    get("learning", "create_experiment"),
                    {
                        "experiment_id": uuid4(),
                        "course_id": course_id,
                        "message_ref": message_id,
                        "topic": proposal.topic.strip(),
                        "capability": proposal.capability,
                        "hypothesis": proposal.hypothesis,
                        "proposed_check": proposal.proposed_check,
                        "evidence": json.dumps(
                            {
                                "student_quote": proposal.student_quote,
                                "message_id": str(message_id),
                                "sources": selected,
                            },
                            default=str,
                        ),
                        "expires_at": utc_now()
                        + timedelta(days=policy.experiment_lifetime_days),
                        "max_open": policy.max_open_experiments,
                    },
                )
            learning.refresh_memory(conn, course_id)
            conn.commit()
    except Exception:
        logger.warning("learning research unavailable; practice records are unaffected")
