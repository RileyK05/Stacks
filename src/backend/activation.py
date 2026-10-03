"""Activate a recovered backup into the live library, with rollback (B-14).

Recovery (`backups._restore_into`) validates an archive and writes a new,
separate data folder. This module performs the second step: swap a
recovered database + raw sources into the active data folder *while no
writer is running*, migrating the restored schema and preserving the
previous library so a failure mid-switch can be undone.

It is deliberately a one-shot process, not an API call: the API itself is
a writer (SQLite connections, the ingestion worker, the backup scheduler),
so the swap must happen with the backend stopped. The desktop shell runs
`stacks-backend --activate <id>`, waits for it to exit, then restarts the
normal backend against the now-active data folder.

Only the database and `raw/` are swapped. The data folder's other
contents — downloaded models, the llama.cpp runtime, Office certificate
state — are machine setup, not course data, and are left in place.
"""

from __future__ import annotations

import json
import shutil
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from src.backend.common import backups
from src.backend.common.config import DATABASE_FILENAME, get_settings
from src.backend.common.db import connect
from src.backend.common.migrate import migrate

_ACTIVATION_DIR = ".activation"
_ROLLBACK_PREFIX = "rollback-"


class ActivationRecord(BaseModel):
    """The durable result of the last activation, read by the app."""

    activated: bool
    backup_id: str
    activated_at: str
    rollback_dir: str | None = None
    database_path: str
    error: str | None = None


class ActivationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActivationResult:
    backup_id: str
    data_dir: Path
    rollback_dir: Path | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _activation_dir(data_dir: Path) -> Path:
    return data_dir / _ACTIVATION_DIR


def _record_path(data_dir: Path) -> Path:
    return _activation_dir(data_dir) / "last.json"


def last_activation(data_dir: Path | None = None) -> ActivationRecord | None:
    root = _activation_dir(Path(data_dir or get_settings().data_dir))
    path = root / "last.json"
    if not path.is_file():
        return None
    try:
        return ActivationRecord.model_validate(json.loads(path.read_text("utf-8")))
    except (OSError, ValueError):
        return None


def _write_record(data_dir: Path, record: ActivationRecord) -> None:
    directory = _activation_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / "last.json.tmp"
    temp.write_text(json.dumps(record.model_dump(), indent=2), encoding="utf-8")
    temp.replace(directory / "last.json")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _live_database(data_dir: Path) -> Path:
    """Where the active database file actually lives. Normally
    `course_assistant.db`; tests and the CLI may point DATABASE_PATH at a
    different name, so honor the configured basename."""
    configured = Path(get_settings().database_path)
    if configured.parent == data_dir:
        return configured
    return data_dir / DATABASE_FILENAME


def _database_files(data_dir: Path) -> list[Path]:
    base = _live_database(data_dir)
    return [base, Path(f"{base}-wal"), Path(f"{base}-shm")]


def _checkpoint_and_close(data_dir: Path) -> None:
    """Fold the WAL into the main database so a copy/rename is complete.
    Only valid with no other writer open, which activation guarantees."""
    path = _live_database(data_dir)
    if not path.exists():
        return
    conn = connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _move_database(source: Path, target: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{source}{suffix}")
        if candidate.exists():
            candidate.replace(Path(f"{target}{suffix}"))


def _verify(database: Path) -> None:
    conn = connect(database)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity["integrity_check"] != "ok":
            raise ActivationError("activated database failed integrity_check")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ActivationError("activated database has foreign-key errors")
    finally:
        conn.close()


def _find_archive(backup_id: str) -> Path:
    if not backup_id.isalnum() or len(backup_id) != 32:
        raise ValueError("invalid backup id")
    archives = [
        p
        for p in backups._backup_root().glob("backup-*.zip")
        if p.stem.endswith(backup_id)
    ]
    if len(archives) != 1:
        raise FileNotFoundError("backup not found")
    return archives[0]


def activate_backup(
    backup_id: str, *, data_dir: Path | None = None
) -> ActivationResult:
    """Swap a verified backup into the active data folder.

    Raises `ActivationError`/`ValueError`/`FileNotFoundError` before any
    change, or restores the previous library and raises if the switch
    itself fails. On success the previous library is kept in the rollback
    directory returned in the result.
    """
    root = Path(data_dir or get_settings().data_dir)
    root.mkdir(parents=True, exist_ok=True)
    archive = _find_archive(backup_id)

    staging = root / _ACTIVATION_DIR / f"staging-{_stamp()}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    # Validates every hash/schema/index before touching the live library.
    backups._restore_into(archive, staging)

    rollback = root / _ACTIVATION_DIR / f"{_ROLLBACK_PREFIX}{_stamp()}"
    _activation_dir(root).mkdir(parents=True, exist_ok=True)
    rollback.mkdir(parents=True, exist_ok=False)

    # Quiescent: fold the WAL, then move the current library aside. A
    # rename within one directory is atomic, so if anything below fails,
    # moving it back fully restores the prior state.
    _checkpoint_and_close(root)
    live_db = _live_database(root)
    had_db = live_db.exists()
    if had_db:
        _move_database(live_db, rollback / live_db.name)
    raw_dir = root / "raw"
    if raw_dir.exists():
        raw_dir.replace(rollback / "raw")

    try:
        _move_database(staging / DATABASE_FILENAME, live_db)
        if (staging / "raw").exists():
            (staging / "raw").replace(raw_dir)
        migrate()
        _verify(live_db)
    except BaseException as error:
        _restore_rollback(root, rollback, had_db)
        _write_record(
            root,
            ActivationRecord(
                activated=False,
                backup_id=backup_id,
                activated_at=datetime.now(UTC).isoformat(),
                rollback_dir=str(rollback),
                database_path=str(live_db),
                error=str(error),
            ),
        )
        raise ActivationError(
            f"activation failed and was rolled back: {error}"
        ) from error

    shutil.rmtree(staging, ignore_errors=True)
    _write_record(
        root,
        ActivationRecord(
            activated=True,
            backup_id=backup_id,
            activated_at=datetime.now(UTC).isoformat(),
            rollback_dir=str(rollback),
            database_path=str(live_db),
        ),
    )
    return ActivationResult(backup_id=backup_id, data_dir=root, rollback_dir=rollback)


def _restore_rollback(root: Path, rollback: Path, had_db: bool) -> None:
    """Undo a partial swap: remove whatever was moved in, then move the
    preserved library back. Best-effort but ordered so the database is
    restored before the error propagates."""
    for stray in _database_files(root):
        stray.unlink(missing_ok=True)
    shutil.rmtree(root / "raw", ignore_errors=True)
    live_db = _live_database(root)
    if had_db and (rollback / live_db.name).exists():
        _move_database(rollback / live_db.name, live_db)
    if (rollback / "raw").exists():
        (rollback / "raw").replace(root / "raw")
    # Best effort: the database file is already back in place, so a
    # migration retry failure here must not mask the original error.
    with suppress(Exception):
        migrate()
