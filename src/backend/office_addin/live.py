"""Ephemeral Office panes, not archived or inferred from foreground windows."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from uuid import UUID, uuid4

from src.backend.common import work_repo
from src.backend.common.companion_config import load_companion_policy
from src.backend.common.db import connection
from src.backend.common.queries import get
from src.backend.common.schemas.office_live import (
    LiveCommand,
    LiveConnection,
    LivePolicyView,
    LivePollResult,
    LiveRegistration,
    ReaderOptions,
    RefreshCompletion,
    RefreshStatus,
)
from src.backend.common.schemas.work import DocumentUpdate


class LiveUnavailableError(ValueError):
    pass


def policy_view() -> LivePolicyView:
    policy = load_companion_policy()
    live = policy.office_live
    return LivePolicyView(
        poll_interval_ms=live.poll_interval_ms,
        refresh_timeout_seconds=live.refresh_timeout_seconds,
        reader=ReaderOptions(
            maxChars=policy.max_document_chars,
            maxCells=live.max_cells,
            maxSheets=live.max_sheets,
            maxSlides=live.max_slides,
            maxShapes=live.max_shapes,
            chunkRows=live.chunk_rows,
            chunkColumns=live.chunk_columns,
        ),
    )


@dataclass
class Pane:
    binding: LiveRegistration
    heartbeat: float
    pending: UUID | None = None


@dataclass
class Refresh:
    connection_id: UUID
    course_id: UUID
    session_id: UUID
    expected_revision: int
    started: float
    result: RefreshStatus


class LiveBroker:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = RLock()
        self._panes: dict[UUID, Pane] = {}
        self._requests: dict[UUID, Refresh] = {}

    def clear(self) -> None:
        with self._lock:
            self._panes.clear()
            self._requests.clear()

    def disconnect(self, key: UUID) -> None:
        with self._lock:
            self._remove(key, "The Office pane disconnected. Reconnect it to refresh.")

    def _sweep(self) -> None:
        now = self._clock()
        policy = load_companion_policy().office_live
        for key, pane in list(self._panes.items()):
            active = self._requests.get(pane.pending) if pane.pending else None
            reading = (
                active is not None
                and active.result.status == "pending"
                and now - active.started < policy.refresh_timeout_seconds
            )
            if not reading and now - pane.heartbeat >= policy.lease_seconds:
                self._remove(key, "The Office pane disconnected. Reopen it to refresh.")
        for key, request in list(self._requests.items()):
            if request.result.status == "pending":
                if now - request.started >= policy.refresh_timeout_seconds:
                    request.result.status = "failed"
                    request.result.error = (
                        "Office did not finish reading in time. Retry the refresh."
                    )
                    pending_pane = self._panes.get(request.connection_id)
                    if pending_pane and pending_pane.pending == key:
                        pending_pane.pending = None
            elif now - request.started > policy.result_retention_seconds:
                del self._requests[key]

    def _remove(self, key: UUID, message: str) -> None:
        pane = self._panes.pop(key, None)
        if pane and pane.pending in self._requests:
            request = self._requests[pane.pending]
            request.result.status = "failed"
            request.result.error = message

    def register(self, binding: LiveRegistration) -> LiveConnection:
        with self._lock:
            self._sweep()
            with connection() as conn:
                work = work_repo.session(conn, binding.course_id, binding.session_id)
            if (
                not work.document
                or work.document.origin != "office"
                or work.document.external_id != binding.external_id
            ):
                raise LiveUnavailableError(
                    "Publish this Office document before connecting live reads."
                )
            for key, pane in list(self._panes.items()):
                if pane.binding.session_id == binding.session_id:
                    self._remove(
                        key, "The document connected through a different Office pane."
                    )
            if len(self._panes) >= load_companion_policy().office_live.max_connections:
                raise LiveUnavailableError(
                    "Too many Office documents are connected. Close an unused pane."
                )
            key = uuid4()
            self._panes[key] = Pane(binding, self._clock())
            return LiveConnection(connection_id=key, connected=True, host=binding.host)

    def _matching(self, course_id: UUID, session_id: UUID) -> tuple[UUID, Pane] | None:
        with connection() as conn:
            work = work_repo.session(conn, course_id, session_id)
        for key, pane in list(self._panes.items()):
            binding = pane.binding
            if binding.course_id == course_id and binding.session_id == session_id:
                if (
                    not work.document
                    or work.document.origin != "office"
                    or work.document.external_id != binding.external_id
                ):
                    self._remove(
                        key, "This session is now connected to a different document."
                    )
                    return None
                return key, pane
        return None

    def status(self, course_id: UUID, session_id: UUID) -> LiveConnection:
        with self._lock:
            self._sweep()
            match = self._matching(course_id, session_id)
            return (
                LiveConnection(
                    connection_id=match[0], connected=True, host=match[1].binding.host
                )
                if match
                else LiveConnection()
            )

    def request(self, course_id: UUID, session_id: UUID) -> RefreshStatus:
        with self._lock:
            self._sweep()
            match = self._matching(course_id, session_id)
            if not match:
                raise LiveUnavailableError(
                    "The Office pane is offline. Reopen it, "
                    "or explicitly use the saved snapshot."
                )
            key, pane = match
            if pane.pending:
                return self._requests[pane.pending].result.model_copy()
            with connection() as conn:
                work = work_repo.session(conn, course_id, session_id)
            request_id = uuid4()
            result = RefreshStatus(request_id=request_id)
            self._requests[request_id] = Refresh(
                key, course_id, session_id, work.revision, self._clock(), result
            )
            pane.pending = request_id
            return result.model_copy()

    def result(
        self, course_id: UUID, session_id: UUID, request_id: UUID
    ) -> RefreshStatus:
        with self._lock:
            self._sweep()
            request = self._requests.get(request_id)
            if (
                not request
                or request.course_id != course_id
                or request.session_id != session_id
            ):
                raise work_repo.WorkNotFoundError(
                    "Refresh request not found in this work session."
                )
            return request.result.model_copy()

    def poll(self, key: UUID, external_id: str) -> LivePollResult:
        with self._lock:
            self._sweep()
            pane = self._panes.get(key)
            if not pane:
                raise LiveUnavailableError(
                    "This Office connection expired. Connect the document again."
                )
            if pane.binding.external_id != external_id:
                self._remove(key, "The Office document changed. Connect it again.")
                raise LiveUnavailableError(
                    "The Office document changed. Connect it again."
                )
            pane.heartbeat = self._clock()
            request = self._requests.get(pane.pending) if pane.pending else None
            return LivePollResult(
                command=LiveCommand(
                    request_id=request.result.request_id,
                    expected_revision=request.expected_revision,
                )
                if request
                else None,
                policy=policy_view(),
            )

    def complete(self, key: UUID, completion: RefreshCompletion) -> RefreshStatus:
        with self._lock:
            self._sweep()
            request = self._requests.get(completion.request_id)
            if not request or request.connection_id != key:
                raise LiveUnavailableError(
                    "This read no longer belongs to the connected Office pane."
                )
            pane = self._panes.get(key)
            if not pane or completion.external_id != pane.binding.external_id:
                raise LiveUnavailableError(
                    "The Office document changed while it was being read."
                )
            if request.result.status != "pending":
                return request.result.model_copy()
            try:
                if completion.error:
                    raise LiveUnavailableError(completion.error)
                document = completion.document
                if (
                    not document
                    or document.origin != "office"
                    or document.external_id != pane.binding.external_id
                ):
                    raise LiveUnavailableError(
                        "The read returned a different document identity."
                    )
                with connection() as conn:
                    conn.execute(
                        get("work", "lock_document"),
                        {
                            "session_id": request.session_id,
                            "course_id": request.course_id,
                        },
                    )
                    work = work_repo.session(
                        conn, request.course_id, request.session_id
                    )
                    if work.revision != request.expected_revision:
                        raise work_repo.WorkConflictError(
                            "The saved document changed during refresh. Refresh again."
                        )
                    if (
                        not work.document
                        or work.document.external_id != pane.binding.external_id
                        or work.document.origin != "office"
                    ):
                        raise LiveUnavailableError(
                            "The session connected to a different document "
                            "during refresh."
                        )
                    if (
                        work.document.model_dump(exclude={"revision", "captured_at"})
                        != document.model_dump()
                    ):
                        work = work_repo.update_document(
                            conn,
                            request.course_id,
                            request.session_id,
                            DocumentUpdate(
                                **document.model_dump(), expected_revision=work.revision
                            ),
                        )
                    conn.commit()
                request.result.status = "complete"
                request.result.revision = work.revision
            except (ValueError, work_repo.WorkNotFoundError) as err:
                request.result.status = "failed"
                request.result.error = str(err)
            pane.pending = None
            pane.heartbeat = self._clock()
            return request.result.model_copy()


BROKER = LiveBroker()
