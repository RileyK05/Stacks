"""Desktop recovery activation and rollback (B-14).

A backup is created from a known library, the live library is changed,
then activation swaps the backup in and preserving the changed library for
rollback. A failed activation restores the previous library.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.backend import activation
from src.backend.common import backups, courses_repo
from src.backend.common.config import get_settings
from src.backend.common.db import connection


def _make_backup_with_course(name: str) -> str:
    courses_repo.create_course(name)
    info = backups.create_backup(tier="full")
    return info.id


def _course_names() -> set[str]:
    with connection() as conn:
        rows = conn.execute("SELECT name FROM courses").fetchall()
    return {row["name"] for row in rows}


def test_activation_swaps_in_the_backup_and_keeps_rollback() -> None:
    backup_id = _make_backup_with_course("Original")
    # Change the live library after the backup: this change must disappear.
    courses_repo.create_course("Changed later")
    assert _course_names() == {"Original", "Changed later"}

    result = activation.activate_backup(backup_id)
    assert result.ok
    assert _course_names() == {"Original"}, "the backup library is now active"
    assert result.rollback_dir is not None
    live_name = Path(get_settings().database_path).name
    assert (result.rollback_dir / live_name).is_file(), (
        "the previous library is preserved for rollback"
    )

    record = activation.last_activation()
    assert record is not None and record.activated and record.backup_id == backup_id


def test_activation_records_a_failure_and_restores_the_previous_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_id = _make_backup_with_course("Original")
    courses_repo.create_course("Changed later")

    def boom() -> None:
        raise RuntimeError("injected failure after the swap")

    # Fail after the new library is moved in but before verification, so
    # the rollback path runs.
    monkeypatch.setattr(activation, "migrate", boom)
    with pytest.raises(activation.ActivationError):
        activation.activate_backup(backup_id)

    assert _course_names() == {"Original", "Changed later"}, (
        "a failed activation restores the previous library"
    )
    record = activation.last_activation()
    assert record is not None and not record.activated and record.error


def test_activation_rejects_an_unknown_backup() -> None:
    with pytest.raises(FileNotFoundError):
        activation.activate_backup("0" * 32)
    with pytest.raises(ValueError):
        activation.activate_backup("not-an-id")


def test_restore_backup_cli_prepares_a_folder() -> None:
    """The offline script still prepares a separate, verified folder."""
    from src.backend.common.backups import _restore_into

    backup_id = _make_backup_with_course("Original")
    archives = list(
        (Path(get_settings().data_dir) / "backups").glob(f"backup-*-{backup_id}.zip")
    )
    assert len(archives) == 1
    destination = Path(get_settings().data_dir) / "manual-restore"
    _restore_into(archives[0], destination)
    assert (destination / "course_assistant.db").is_file()
