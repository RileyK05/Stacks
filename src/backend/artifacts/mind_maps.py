from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from src.backend.artifacts import content
from src.backend.common import artifacts_repo, provider
from src.backend.common.db import Connection, connection
from src.backend.common.prompt_registry import (
    grounded_prompt,
    load_prompt,
    load_prompt_policy,
)
from src.backend.common.providers import ProviderChoice
from src.backend.common.queries import get
from src.backend.common.schemas.learning import HelpContent, PracticeQuestion
from src.backend.common.schemas.map_study import MapStudyRequest
from src.backend.common.schemas.mind_map import MindMapContent
from src.backend.retrieval.funnel import Candidate
from src.backend.student_model import learning
from src.backend.tutor.compose import compose_answer, parse_json_object
from src.backend.tutor.workspace import WorkspaceQuiz, extract_workspace_items


class MapStudyResult(BaseModel):
    text: str
    citations: list[dict[str, Any]]
    sources: list[int] = Field(default_factory=list)
    model: str
    fell_back_to_local: bool = False
    quiz_id: UUID | None = None
    quiz_version: int | None = None
    quiz: WorkspaceQuiz | None = None


@dataclass
class _Context:
    map: MindMapContent
    label: str
    ids: tuple[UUID, ...]
    evidence: list[dict[str, Any]]
    choice: ProviderChoice | None
    topics: tuple[str, ...]
    message_id: UUID | None


def _context(conn: Connection, course_id: UUID, request: MapStudyRequest) -> _Context:
    origin = request.origin
    selection = None
    if origin.message_id:
        message = conn.execute(
            get("mind_maps", "message"),
            {
                "course_id": course_id,
                "message_id": origin.message_id,
            },
        ).fetchone()
        items = message["payload"].get("workspace", []) if message else []
        if (
            origin.item_index >= len(items)
            or items[origin.item_index].get("type") != "mind_map"
        ):
            raise LookupError("saved mind map not found")
        raw = {
            k: v for k, v in items[origin.item_index].items() if k in {"nodes", "edges"}
        }
        payload = message["payload"]
        # Workspace [n] markers refer to the complete candidate array. Older
        # messages stored only chunk_ids, so retain that field as a fallback.
        raw_ids = payload.get("material_chunk_ids", payload.get("chunk_ids", []))
        ids = tuple(UUID(cid) for cid in raw_ids)
        selection = message
    else:
        assert origin.artifact_id is not None
        artifact = artifacts_repo.load(conn, course_id, origin.artifact_id)
        if artifact is None or artifact.kind != "mind_map":
            raise LookupError("saved mind map not found")
        if artifact.version != origin.artifact_version:
            raise artifacts_repo.StaleVersionError(
                "save or reload the map before studying it"
            )
        raw, ids = artifact.content, artifact.sources
        if artifact.origin.get("message_id"):
            selection = conn.execute(
                get("mind_maps", "message"),
                {
                    "course_id": course_id,
                    "message_id": artifact.origin["message_id"],
                },
            ).fetchone()
    mapped = MindMapContent.model_validate(raw)
    node = next((n for n in mapped.nodes if n.id == request.node_id), None)
    if node is None:
        raise LookupError("map topic not found")
    wanted = set(node.sources)
    children = {node.id}
    if request.action == "quiz":
        for _ in mapped.nodes:
            children.update(
                e.target
                for e in mapped.edges
                if e.kind == "branch" and e.source in children
            )
        wanted.update(
            n for child in mapped.nodes if child.id in children for n in child.sources
        )
    if any(not 1 <= n <= len(ids) for n in wanted):
        raise ValueError("the map cites unavailable evidence")
    selected = tuple(ids[n - 1] for n in sorted(wanted))
    rows = learning.evidence_for(conn, selected)
    by_id = {str(row["chunk_id"]): row for row in rows}
    allowed = selection["source_ids"] if selection else None
    evidence = [by_id[str(cid)] for cid in selected if str(cid) in by_id]
    if len(evidence) != len(selected) or (
        allowed is not None
        and any(str(r["source_id"]) not in {str(s) for s in allowed} for r in evidence)
    ):
        raise ValueError(
            "this topic needs sources that are removed or excluded from its chat"
        )
    choice = (
        ProviderChoice.model_validate(selection["model_choice"])
        if selection and selection["model_choice"]
        else None
    )
    topics = tuple(n.label for n in mapped.nodes if n.id in children)
    return _Context(
        mapped,
        node.label,
        selected,
        evidence,
        choice,
        topics,
        selection["message_id"] if selection else None,
    )


def _quiz_result(
    conn: Connection, course_id: UUID, artifact_id: UUID, request: MapStudyRequest
) -> MapStudyResult:
    artifact = artifacts_repo.load(conn, course_id, artifact_id)
    assert artifact is not None
    if (
        artifact.origin.get("map_origin") != request.origin.model_dump(mode="json")
        or artifact.origin.get("map_node") != request.node_id
    ):
        raise ValueError("this request ID was already used for another topic")
    evidence = learning.evidence_for(conn, artifact.sources)
    return MapStudyResult(
        text="This practice quiz is saved in your course materials.",
        citations=evidence,
        model=artifact.origin.get("model", ""),
        fell_back_to_local=artifact.origin.get("fell_back_to_local", False),
        quiz_id=artifact.artifact_id,
        quiz_version=artifact.version,
        quiz=WorkspaceQuiz(type="quiz", title=artifact.title, **artifact.content),
    )


def study(course_id: UUID, request: MapStudyRequest) -> MapStudyResult:
    with connection() as conn:
        context = _context(conn, course_id, request)
        existing = (
            conn.execute(
                get("mind_maps", "quiz_request"),
                {
                    "course_id": course_id,
                    "request_id": request.request_id,
                },
            ).fetchone()
            if request.action == "quiz"
            else None
        )
        if existing:
            saved = artifacts_repo.load(conn, course_id, existing["artifact_id"])
            assert saved is not None
            if (
                saved.origin.get("map_origin") != request.origin.model_dump(mode="json")
                or saved.origin.get("map_node") != request.node_id
            ):
                raise ValueError("this request ID was already used for another topic")
            return _quiz_result(conn, course_id, existing["artifact_id"], request)
    generations: list[provider.GenerationResult] = []

    def generate(
        task: str, prompt: str, *, response_schema: dict[str, Any] | None = None
    ) -> str:
        result = provider.generate(
            task,
            prompt,
            course_id=course_id,
            choice=context.choice,
            response_schema=response_schema,
        )
        generations.append(result)
        return result.text

    if request.action == "explain":
        material = json.dumps(
            {
                "topic": context.label,
                "passages": [
                    {"number": i, "text": r["text"]}
                    for i, r in enumerate(context.evidence, 1)
                ],
            },
            default=str,
        )
        prompt = grounded_prompt(load_prompt("map_explain"), material)
        schema = HelpContent.model_json_schema()
        schema["properties"]["sources"]["items"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": len(context.ids),
        }
        try:
            raw = generate("tutor_answer", prompt, response_schema=schema)
        except provider.ProviderRequestRejectedError:
            raw = generate("tutor_answer", prompt)
        help = HelpContent.model_validate(parse_json_object(raw))
        numbers = content.cited_numbers(help.model_dump())
        if not help.sources or any(not 1 <= n <= len(context.ids) for n in numbers):
            raise ValueError("the explanation cited unavailable evidence")
        if content.cited_numbers({"text": help.text}) - set(help.sources):
            raise ValueError("the explanation's citations do not match its sources")
        missing = set(help.sources) - content.cited_numbers({"text": help.text})
        text = help.text + (
            "\n\nSources: " + " ".join(f"[{n}]" for n in sorted(missing))
            if missing
            else ""
        )
        with connection() as conn:
            if _context(conn, course_id, request) != context:
                raise artifacts_repo.StaleVersionError(
                    "the map or source selection changed; try again"
                )
        return MapStudyResult(
            text=text,
            sources=help.sources,
            citations=context.evidence,
            model=generations[-1].model,
            fell_back_to_local=any(r.fell_back_to_local for r in generations),
        )
    candidates = tuple(
        Candidate(
            chunk_id=cid,
            source_id=UUID(str(row["source_id"])),
            locator_id=uuid4(),
            chunk_index=row["chunk_index"],
            text=row["text"],
            layers=frozenset({"map"}),
            rank=1,
        )
        for cid, row in zip(context.ids, context.evidence, strict=True)
    )
    question = f"Quiz me on {context.label}"
    composed = compose_answer(
        question,
        candidates,
        generate,
        on_schema_rejected=lambda err: isinstance(
            err, provider.ProviderRequestRejectedError
        ),
        teaching="\n\n" + load_prompt("map_quiz"),
        conversation=json.dumps({"allowed_topic_labels": context.topics}),
    )
    extracted = extract_workspace_items(composed.text, len(context.ids))
    quiz = next(
        (item for item in extracted.items if isinstance(item, WorkspaceQuiz)), None
    )
    if quiz is None:
        raise ValueError(
            "the model could not create a supported quiz; try another model"
        )
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if _context(conn, course_id, request) != context:
            raise artifacts_repo.StaleVersionError(
                "the map or source selection changed; try again"
            )
        prior = conn.execute(
            get("mind_maps", "quiz_request"),
            {
                "course_id": course_id,
                "request_id": request.request_id,
            },
        ).fetchone()
        if prior:
            return _quiz_result(conn, course_id, prior["artifact_id"], request)
        topics = {" ".join(t.casefold().split()) for t in context.topics}
        questions = learning.allocate_questions(
            conn,
            course_id,
            question,
            [
                PracticeQuestion.model_validate(q.model_dump(exclude_none=True))
                for q in quiz.questions
                if " ".join(q.topic.casefold().split()) in topics
            ],
            source_ids=[UUID(str(r["source_id"])) for r in context.evidence],
        )
        if not questions:
            raise ValueError("no fresh supported questions remain for this topic")
        raw_content, sources = content.compact(
            {"questions": [q.model_dump() for q in questions]}, context.ids
        )
        saved = artifacts_repo._create(
            conn,
            course_id,
            kind="quiz",
            title=f"Practice: {context.label}",
            content=content.validate_content("quiz", raw_content),
            sources=sources,
            origin={
                "map_origin": request.origin.model_dump(mode="json"),
                "map_node": request.node_id,
                "message_id": str(context.message_id) if context.message_id else None,
                "map_request_id": str(request.request_id),
                "model": generations[-1].model,
                "prompt_version": load_prompt_policy().prompts_config_version,
                "fell_back_to_local": any(r.fell_back_to_local for r in generations),
            },
            author="model",
            note="Generated from a mind-map topic",
        )
        conn.commit()
        return _quiz_result(conn, course_id, saved.artifact_id, request)
