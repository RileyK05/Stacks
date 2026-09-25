"""Artifacts API (docs/plan-notebook.md §4.3, decision 013).

Typed, editable study material in a course: create, save from a chat,
edit (every save a version; a save based on an outdated copy is refused
with 409), ask the model for an edit (a proposal the student accepts or
undoes — accepting is an ordinary save authored by "model"), restore a
version, list what it cites, export to a file.

Citations are checked on every save: each cited number must name one of
the artifact's sources, and every source must be a chunk of this course.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from src.backend.api.tutor import CitationView
from src.backend.artifacts import content as artifact_content
from src.backend.artifacts import edit as artifact_edit
from src.backend.artifacts import export as artifact_export
from src.backend.artifacts.content import ArtifactKind, UnknownCitationError
from src.backend.common import (
    artifacts_repo,
    conversations_repo,
    courses_repo,
    provider,
    providers,
    usage_repo,
)
from src.backend.common.artifacts_repo import (
    Artifact,
    ArtifactSummary,
    StaleVersionError,
)
from src.backend.common.config import get_settings
from src.backend.common.db import connection, json_ids
from src.backend.common.embeddings_config import load_embedding_policy
from src.backend.common.queries import get
from src.backend.retrieval.config import load_retrieval_policy
from src.backend.tutor.workspace import WorkspaceItem

router = APIRouter(prefix="/courses/{course_id}/artifacts", tags=["artifacts"])
_WORKSPACE_ITEM: TypeAdapter[WorkspaceItem] = TypeAdapter(WorkspaceItem)


class ArtifactSummaryView(BaseModel):
    artifact_id: str
    kind: ArtifactKind
    title: str
    version: int
    created_at: datetime
    updated_at: datetime
    origin: dict[str, Any]


class ArtifactView(ArtifactSummaryView):
    content: dict[str, Any]
    # Chunk ids; "[n]" in the content means sources[n-1].
    sources: list[str]


class ArtifactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ArtifactKind
    title: str = Field(default="", max_length=artifacts_repo.TITLE_MAX_LENGTH)
    content: dict[str, Any] | None = None


class FromMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    item_index: int = Field(default=0, ge=0)


class ArtifactSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=artifacts_repo.TITLE_MAX_LENGTH)
    content: dict[str, Any]
    # None keeps the artifact's sources (an ordinary edit); a list replaces
    # them (accepting a model edit that cited new material).
    sources: list[UUID] | None = Field(default=None, max_length=500)
    author: Literal["you", "model"] = "you"
    note: str = Field(default="", max_length=300)


class VersionView(BaseModel):
    version: int
    title: str
    author: str
    note: str
    created_at: datetime


class VersionDetailView(VersionView):
    content: dict[str, Any]
    sources: list[str]


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=1)


class ArtifactCitationView(BaseModel):
    number: int
    chunk_id: str
    # None when the chunk was removed along with its source.
    citation: CitationView | None


class ModelChoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection: str = Field(min_length=1, max_length=providers.CONNECTION_ID_MAX)
    model: str | None = Field(default=None, max_length=200)


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=2000)
    scope: artifact_edit.EditScope | None = None
    model_choice: ModelChoiceBody | None = None


class ProposalView(BaseModel):
    title: str
    content: dict[str, Any]
    sources: list[str]
    model: str
    trace_id: str
    # New lines not tied to any source: shown as a warning before accepting.
    uncited_lines: int = 0


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = Field(min_length=1, max_length=8)
    # A path chosen in the app's save dialog; otherwise the export folder.
    path: str | None = Field(default=None, max_length=2000)


class ExportView(BaseModel):
    path: str
    filename: str


def _summary_view(artifact: ArtifactSummary) -> ArtifactSummaryView:
    return ArtifactSummaryView(
        artifact_id=str(artifact.artifact_id),
        kind=artifact.kind,  # type: ignore[arg-type]
        title=artifact.title,
        version=artifact.version,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
        origin=artifact.origin,
    )


def _view(artifact: Artifact) -> ArtifactView:
    return ArtifactView(
        **_summary_view(artifact).model_dump(),
        content=artifact.content,
        sources=[str(s) for s in artifact.sources],
    )


def _require_course(course_id: UUID) -> None:
    if courses_repo.get_course(course_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")


def _require_artifact(course_id: UUID, artifact_id: UUID) -> Artifact:
    _require_course(course_id)
    artifact = artifacts_repo.get_artifact(course_id, artifact_id)
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact not found")
    return artifact


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _checked(
    course_id: UUID,
    kind: str,
    raw: dict[str, Any],
    sources: list[UUID] | tuple[UUID, ...],
    kept: tuple[UUID, ...] = (),
) -> dict[str, Any]:
    """Valid content whose every citation names one of `sources`, all of
    them chunks of this course. Sources the artifact already had (`kept`)
    are not re-checked: once their file is deleted they are a visible
    missing slot, and the artifact must stay editable."""
    try:
        content = artifact_content.validate_content(kind, raw)
    except (ValidationError, ValueError) as err:
        raise _unprocessable(f"that {kind} isn't valid: {err}") from err
    outside = [
        n for n in artifact_content.cited_numbers(content) if not 1 <= n <= len(sources)
    ]
    if outside:
        raise _unprocessable(
            f"citation [{min(outside)}] doesn't match any of this {kind}'s sources"
        )
    new = tuple(dict.fromkeys(s for s in sources if s not in kept))
    foreign = set(new) - artifacts_repo.chunks_in_course(course_id, new)
    if foreign:
        raise _unprocessable("a cited source isn't part of this course")
    return content


@router.get("", response_model=list[ArtifactSummaryView])
def list_artifacts(course_id: UUID) -> list[ArtifactSummaryView]:
    _require_course(course_id)
    return [_summary_view(a) for a in artifacts_repo.list_artifacts(course_id)]


@router.post("", response_model=ArtifactView, status_code=status.HTTP_201_CREATED)
def create_artifact(course_id: UUID, payload: ArtifactCreate) -> ArtifactView:
    _require_course(course_id)
    raw = payload.content if payload.content is not None else {}
    content = _checked(course_id, payload.kind, raw, ())
    created = artifacts_repo.create(
        course_id,
        kind=payload.kind,
        title=payload.title.strip() or artifact_content.DEFAULT_TITLES[payload.kind],
        content=content,
        origin={"by": "you"},
    )
    return _view(created)


@router.post(
    "/from-message", response_model=ArtifactView, status_code=status.HTTP_201_CREATED
)
def save_from_message(course_id: UUID, payload: FromMessage) -> ArtifactView:
    """Save a workspace item from a chat answer as an artifact. The item is
    read from the stored message, not from the client, and its citations
    are pinned to the chunks that answer read."""
    _require_course(course_id)
    message = conversations_repo.message_in_course(course_id, payload.message_id)
    if message is None or message.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found")
    items = message.payload.get("workspace") or []
    if payload.item_index >= len(items):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "that answer has no such item")
    try:
        item = _WORKSPACE_ITEM.validate_python(items[payload.item_index])
        kind, title, raw, item_sources = artifact_content.from_workspace_item(item)
        numbered = [UUID(str(value)) for value in message.payload.get("chunk_ids", [])]
        compacted, sources = artifact_content.compact(raw, numbered, also=item_sources)
    except (ValidationError, UnknownCitationError, ValueError) as err:
        raise _unprocessable(f"that item can't be saved: {err}") from err
    content = _checked(course_id, kind, compacted, sources)
    created = artifacts_repo.create(
        course_id,
        kind=kind,
        title=title,
        content=content,
        sources=sources,
        origin={
            "by": "chat",
            "conversation_id": str(message.conversation_id),
            "message_id": str(message.message_id),
            "model": str(message.payload.get("model", "")),
        },
        author="model",
        note="Saved from a chat",
    )
    return _view(created)


@router.get("/{artifact_id}", response_model=ArtifactView)
def get_artifact(course_id: UUID, artifact_id: UUID) -> ArtifactView:
    return _view(_require_artifact(course_id, artifact_id))


@router.put("/{artifact_id}", response_model=ArtifactView)
def save_artifact(
    course_id: UUID, artifact_id: UUID, payload: ArtifactSave
) -> ArtifactView:
    current = _require_artifact(course_id, artifact_id)
    sources = tuple(payload.sources) if payload.sources is not None else current.sources
    content = _checked(
        course_id, current.kind, payload.content, sources, kept=current.sources
    )
    try:
        saved = artifacts_repo.save(
            course_id,
            artifact_id,
            expected_version=payload.base_version,
            title=payload.title,
            content=content,
            sources=sources,
            author=payload.author,
            note=payload.note,
        )
    except StaleVersionError as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    return _view(saved)


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artifact(course_id: UUID, artifact_id: UUID) -> None:
    _require_course(course_id)
    if not artifacts_repo.delete(course_id, artifact_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact not found")


@router.get("/{artifact_id}/versions", response_model=list[VersionView])
def list_versions(course_id: UUID, artifact_id: UUID) -> list[VersionView]:
    _require_artifact(course_id, artifact_id)
    return [
        VersionView(
            version=v.version,
            title=v.title,
            author=v.author,
            note=v.note,
            created_at=v.created_at,
        )
        for v in artifacts_repo.versions(artifact_id)
    ]


@router.get("/{artifact_id}/versions/{number}", response_model=VersionDetailView)
def get_version(course_id: UUID, artifact_id: UUID, number: int) -> VersionDetailView:
    _require_artifact(course_id, artifact_id)
    found = artifacts_repo.version(artifact_id, number)
    if found is None or found.content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    return VersionDetailView(
        version=found.version,
        title=found.title,
        author=found.author,
        note=found.note,
        created_at=found.created_at,
        content=found.content,
        sources=[str(s) for s in found.sources],
    )


@router.post("/{artifact_id}/versions/{number}/restore", response_model=ArtifactView)
def restore_version(
    course_id: UUID, artifact_id: UUID, number: int, payload: RestoreRequest
) -> ArtifactView:
    """Restoring saves the old content as the newest version, so the
    restore itself can be undone the same way."""
    current = _require_artifact(course_id, artifact_id)
    found = artifacts_repo.version(artifact_id, number)
    if found is None or found.content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    try:
        saved = artifacts_repo.save(
            course_id,
            artifact_id,
            expected_version=payload.base_version,
            title=found.title,
            content=artifact_content.validate_content(current.kind, found.content),
            sources=found.sources,
            author="you",
            note=f"Restored version {number}",
        )
    except StaleVersionError as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    return _view(saved)


def _citations(
    course_id: UUID, sources: tuple[UUID, ...]
) -> list[ArtifactCitationView]:
    with connection() as conn:
        rows = conn.execute(
            get("retrieval_traces", "chunks_with_locators_by_ids"),
            {"chunk_ids": json_ids(sources)},
        ).fetchall()
    by_id = {row["chunk_id"]: row for row in rows}
    views: list[ArtifactCitationView] = []
    for number, chunk_id in enumerate(sources, start=1):
        row = by_id.get(chunk_id)
        views.append(
            ArtifactCitationView(
                number=number,
                chunk_id=str(chunk_id),
                citation=CitationView(
                    chunk_id=str(row["chunk_id"]),
                    source_id=str(row["source_id"]),
                    chunk_index=row["chunk_index"],
                    text=row["text"],
                    locator_type=row["locator_type"],
                    label=row["label"],
                    description=row["description"],
                    filename=row["filename"],
                )
                if row
                else None,
            )
        )
    return views


@router.get("/{artifact_id}/citations", response_model=list[ArtifactCitationView])
def artifact_citations(
    course_id: UUID, artifact_id: UUID
) -> list[ArtifactCitationView]:
    """The artifact's sources in citation order: [n] is the n-th entry."""
    artifact = _require_artifact(course_id, artifact_id)
    return _citations(course_id, artifact.sources)


@router.post("/{artifact_id}/propose-edit", response_model=ProposalView)
def propose_edit(
    course_id: UUID, artifact_id: UUID, payload: EditRequest
) -> ProposalView:
    """The artifact with a requested change applied by the model — shown to
    the student to accept (save with author "model") or throw away."""
    artifact = _require_artifact(course_id, artifact_id)
    choice = (
        providers.ProviderChoice(**payload.model_choice.model_dump(exclude_none=True))
        if payload.model_choice
        else None
    )
    try:
        query_embedding = provider.embed_query(payload.request)
        with connection() as conn:
            proposal = artifact_edit.propose_edit(
                conn,
                course_id,
                artifact,
                payload.request,
                load_retrieval_policy(),
                scope=payload.scope,
                query_embedding=query_embedding,
                embedding_model=load_embedding_policy().model,
                choice=choice,
            )
            conn.commit()
    except artifact_edit.EditFailedError as err:
        raise _unprocessable(str(err)) from err
    except provider.EmptyModelError as err:
        raise _unprocessable("the model returned nothing; try again") from err
    except provider.ProviderUnavailableError as err:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(err)) from err
    except usage_repo.BudgetExceededError as err:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(err)) from err
    return ProposalView(
        title=proposal.title,
        content=proposal.content,
        sources=[str(s) for s in proposal.sources],
        model=proposal.model,
        trace_id=str(proposal.trace_id),
        uncited_lines=proposal.uncited_lines,
    )


@router.post("/{artifact_id}/export", response_model=ExportView)
def export_artifact(
    course_id: UUID, artifact_id: UUID, payload: ExportRequest
) -> ExportView:
    artifact = _require_artifact(course_id, artifact_id)
    fmt = payload.format.lower().lstrip(".")
    if fmt not in artifact_export.FORMATS.get(artifact.kind, ()):
        raise _unprocessable(f"a {artifact.kind} can't be exported as .{fmt}")
    extension = artifact_export.extension_for(artifact.kind, fmt, artifact.content)
    if payload.path:
        target = Path(payload.path)
        if target.suffix.lower() != f".{extension}":
            target = target.with_name(f"{target.name}.{extension}")
        if not target.parent.is_dir():
            raise _unprocessable("that folder doesn't exist")
    else:
        directory = Path(get_settings().export_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = artifact_export.unique_path(
            directory, artifact_export.safe_stem(artifact.title), extension
        )
    labels = [
        artifact_export.SourceLabel(
            number=view.number,
            filename=view.citation.filename if view.citation else "(removed source)",
            label=view.citation.label if view.citation else "",
        )
        for view in _citations(course_id, artifact.sources)
    ]
    data = artifact_export.render(
        artifact.kind, fmt, artifact.title, artifact.content, labels
    )
    target.write_bytes(data)
    return ExportView(path=str(target), filename=target.name)
