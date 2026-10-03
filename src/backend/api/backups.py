from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from src.backend.common import backups
from src.backend.common.backups import (
    BackupError,
    BackupInfo,
    BackupPreferences,
    BackupStatus,
)
from src.backend.common.config import get_settings

router = APIRouter(prefix="/settings/backups", tags=["settings"])


class BackupOverview(BaseModel):
    settings: BackupPreferences
    status: BackupStatus
    archive_dir: str


class BackupList(BaseModel):
    backups: list[BackupInfo]


class RecoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class RecoverView(BaseModel):
    data_dir: str
    database_path: str
    restart_required: bool = True
    instructions: str


def _overview() -> BackupOverview:
    return BackupOverview(
        settings=backups.get_preferences(),
        status=backups.get_status(),
        archive_dir=str(Path(get_settings().data_dir) / "backups"),
    )


@router.get("", response_model=BackupOverview)
def get_backups() -> BackupOverview:
    return _overview()


@router.put("", response_model=BackupOverview)
def update_backups(payload: BackupPreferences) -> BackupOverview:
    backups.update_preferences(payload)
    return _overview()


@router.get("/archives", response_model=BackupList)
def list_backups() -> BackupList:
    return BackupList(backups=backups.list_backups())


@router.post("/create", response_model=BackupInfo, status_code=status.HTTP_201_CREATED)
def create_backup() -> BackupInfo:
    try:
        return backups.create_backup()
    except BackupError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, str(error)
        ) from error


@router.post(
    "/recover", response_model=RecoverView, status_code=status.HTTP_201_CREATED
)
def recover_backup(payload: RecoverRequest) -> RecoverView:
    try:
        destination = backups.recover_backup(payload.backup_id)
    except FileNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)
        ) from error
    except BackupError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)
        ) from error
    return RecoverView(
        data_dir=str(destination),
        database_path=str(destination / "course_assistant.db"),
        instructions=(
            "Recovery validated the backup and prepared a separate data "
            "folder; your current library was not changed. In the desktop "
            "app, choose Activate to restart the library against this "
            "backup (the previous library is kept for rollback). Outside "
            "the app, use the recovered folder manually with Stacks fully "
            "closed."
        ),
    )
