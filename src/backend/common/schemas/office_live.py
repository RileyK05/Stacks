from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from src.backend.common.schemas.work import DocumentInput, WorkModel

OfficeHost = Literal["word", "excel", "powerpoint"]


class LiveRegistration(WorkModel):
    course_id: UUID
    session_id: UUID
    host: OfficeHost
    external_id: str = Field(min_length=1, max_length=2000)


class LiveConnection(WorkModel):
    connection_id: UUID | None = None
    connected: bool = False
    host: OfficeHost | None = None


class LivePoll(WorkModel):
    external_id: str = Field(min_length=1, max_length=2000)


class RefreshStatus(WorkModel):
    request_id: UUID
    status: Literal["pending", "complete", "failed"] = "pending"
    revision: int | None = None
    error: str = ""


class RefreshCompletion(WorkModel):
    request_id: UUID
    external_id: str = Field(min_length=1, max_length=2000)
    document: DocumentInput | None = None
    error: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def one_result(self) -> "RefreshCompletion":
        if (self.document is None) == (not self.error.strip()):
            raise ValueError("Supply either a document or a reading error.")
        return self


class ReaderOptions(WorkModel):
    max_chars: int = Field(alias="maxChars", gt=0)
    max_cells: int = Field(alias="maxCells", gt=0)
    max_sheets: int = Field(alias="maxSheets", gt=0)
    max_slides: int = Field(alias="maxSlides", gt=0)
    max_shapes: int = Field(alias="maxShapes", gt=0)
    chunk_rows: int = Field(alias="chunkRows", gt=0)
    chunk_columns: int = Field(alias="chunkColumns", gt=0)


class LivePolicyView(WorkModel):
    poll_interval_ms: int
    refresh_timeout_seconds: int
    reader: ReaderOptions


class LiveCommand(WorkModel):
    request_id: UUID
    expected_revision: int


class LivePollResult(WorkModel):
    command: LiveCommand | None = None
    policy: LivePolicyView
