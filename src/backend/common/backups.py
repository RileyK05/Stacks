"""Local, content-verified backups and safe offline restoration."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import re
import shutil
import sqlite3
import tempfile
import threading
import zipfile
import zlib
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from src.backend.common import settings_repo
from src.backend.common.backups_config import load_backup_policy
from src.backend.common.config import DATABASE_FILENAME, get_settings
from src.backend.common.db import connect, utc_now
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.migrate import MIGRATIONS_DIR
from src.backend.common.queries import get

logger = logging.getLogger(__name__)
_FILE = "backups"
_SETTING = "backups.preferences"
_STATUS_SETTING = "backups.status"
_CREATE_LOCK = threading.Lock()
_COMPRESSION_LEVELS = {"fast": 1, "balanced": 6, "maximum": 9}


class BackupPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    tier: Literal["full", "partial", "heavy"]
    compression: Literal["fast", "balanced", "maximum"]
    interval_hours: int = Field(ge=1, le=720)
    keep_count: int = Field(ge=1, le=100)


class BackupStatus(BaseModel):
    last_success_at: datetime | None = None
    last_error: str | None = None
    next_due_at: datetime | None = None


class BackupInfo(BaseModel):
    id: str
    filename: str
    created_at: datetime
    size_bytes: int
    tier: Literal["full", "partial", "heavy"]
    compression: Literal["fast", "balanced", "maximum"]
    sha256: str


class BackupError(RuntimeError):
    pass


class InvalidBackupError(BackupError):
    pass


def _backup_root() -> Path:
    return Path(get_settings().data_dir) / "backups"


def get_preferences() -> BackupPreferences:
    raw = settings_repo.get_setting(_SETTING)
    if raw is not None:
        return BackupPreferences.model_validate(raw)
    policy = load_backup_policy()
    return BackupPreferences(
        enabled=policy.default_enabled,
        tier=policy.default_tier,
        compression=policy.default_compression,
        interval_hours=policy.default_interval_hours,
        keep_count=policy.default_keep_count,
    )


def update_preferences(preferences: BackupPreferences) -> BackupPreferences:
    settings_repo.put_setting(_SETTING, preferences.model_dump())
    return preferences


def _status() -> BackupStatus:
    raw = settings_repo.get_setting(_STATUS_SETTING, {}) or {}
    return BackupStatus.model_validate(raw)


def get_status() -> BackupStatus:
    status = _status()
    prefs = get_preferences()
    if prefs.enabled and status.last_success_at is not None:
        status.next_due_at = status.last_success_at + timedelta(
            hours=prefs.interval_hours
        )
    return status


def _save_status(
    *, success_at: datetime | None = None, error: str | None = None
) -> None:
    current = _status()
    last_success = success_at if success_at is not None else current.last_success_at
    settings_repo.put_setting(
        _STATUS_SETTING,
        {
            "last_success_at": last_success.isoformat() if last_success else None,
            "last_error": error,
        },
    )


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _tier_snapshot(snapshot: Path, tier: str) -> None:
    if tier == "full":
        return
    conn = connect(snapshot)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        # These deletions are intentionally explicit. The live database is
        # never modified, and FK checks catch omissions before publication.
        for operation in (
            "messages",
            "conversations",
            "answer_cache",
            "work_turns",
            "usage_ledger",
            "retrieval_traces",
            "chunk_embeddings",
            "passage_windows",
            "graph_edges",
        ):
            conn.execute(get(_FILE, f"delete_{operation}"))
        conn.execute(get(_FILE, "sanitize_artifact_origins"))
        conn.execute(get(_FILE, "sanitize_practice_origins"))
        conn.execute(
            get(_FILE, "sanitize_source_uris"),
            {"uri_prefix": "raw/"},
        )
        # Keep only learning presentation preference and backup configuration;
        # provider endpoints, runtime paths, and hidden text settings do not
        # travel in reduced tiers.
        conn.execute(
            get(_FILE, "delete_nonacademic_settings"),
            {
                "learning_preference": "learning.preferred_method",
                "backup_preferences": _SETTING,
            },
        )
        if tier == "heavy":
            for operation in (
                "practice_feedback",
                "practice_help",
                "practice_assessments",
                "practice_runs",
                "learning_teaching_events",
                "learning_observations",
                "learning_experiments",
                "core_method_observations",
                "course_memories",
            ):
                conn.execute(get(_FILE, f"delete_{operation}"))
            conn.execute(get(_FILE, "delete_learning_preference"))
        conn.commit()
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise BackupError(f"snapshot has {len(fk_errors)} foreign-key errors")
        # VACUUM compacts the offline copy so omitted text is not left behind
        # in free pages that SQLite would otherwise reuse later.
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _source_members(snapshot: Path) -> list[dict[str, Any]]:
    conn = connect(snapshot)
    try:
        return [dict(row) for row in conn.execute(get(_FILE, "backup_source_rows"))]
    finally:
        conn.close()


def _verified_stored_source(
    row: dict[str, Any],
) -> tuple[Path, int, str, str, int, tuple[int, int, int]]:
    course_id = UUID(str(row["course_id"]))
    source_id = UUID(str(row["source_id"]))
    root = Path(get_settings().storage_root).resolve()
    path = (root / str(course_id) / f"{source_id}.bin").resolve()
    if path.parent != (root / str(course_id)).resolve() or not path.is_file():
        raise BackupError(f"source file is missing: {source_id}")
    before = path.stat()
    stored_hash, stored_size = _digest(path)
    expected_stored = row["size_bytes"]
    if expected_stored is not None and stored_size != int(expected_stored):
        raise BackupError(f"stored source size changed: {source_id}")
    raw_hash = hashlib.sha256()
    raw_size = 0
    max_original = load_lifecycle_policy().max_raw_upload_bytes
    opener = gzip.open if row["stored_encoding"] == "gzip" else open
    try:
        with opener(path, "rb") as source:
            while chunk := source.read(1024 * 1024):
                raw_hash.update(chunk)
                raw_size += len(chunk)
                if raw_size > max_original:
                    raise BackupError(
                        f"source expands beyond upload limit: {source_id}"
                    )
    except (OSError, EOFError, zlib.error) as error:
        raise BackupError(f"stored source cannot be decoded: {source_id}") from error
    content_hash = raw_hash.hexdigest()
    if row["file_hash"] and content_hash != row["file_hash"]:
        raise BackupError(f"source content hash differs from database: {source_id}")
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise BackupError(f"source changed while backing up: {source_id}")
    return (
        path,
        raw_size,
        content_hash,
        stored_hash,
        stored_size,
        (before.st_size, before.st_mtime_ns, before.st_ino),
    )


def _archive_file(archive: zipfile.ZipFile, name: str, path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source, archive.open(name, "w") as target:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            target.write(chunk)
    return {"path": name, "size_bytes": size, "sha256": digest.hexdigest()}


def _prune(keep_count: int) -> None:
    archives = sorted(
        _backup_root().glob("backup-*.zip"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )
    for old in archives[keep_count:]:
        old.unlink(missing_ok=True)


def create_backup(*, tier: str | None = None) -> BackupInfo:
    if not _CREATE_LOCK.acquire(blocking=False):
        raise BackupError("a backup is already running")
    root = _backup_root()
    temp_db: Path | None = None
    staging: Path | None = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        prefs = get_preferences()
        selected_tier = cast(Literal["full", "partial", "heavy"], tier or prefs.tier)
        if selected_tier not in ("full", "partial", "heavy"):
            raise ValueError("unknown backup tier")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_id = uuid4().hex
        final_path = root / f"backup-{stamp}-{backup_id}.zip"
        with tempfile.NamedTemporaryFile(
            prefix="snapshot-", suffix=".sqlite", dir=root, delete=False
        ) as handle:
            temp_db = Path(handle.name)
        source = connect()
        destination = connect(temp_db)
        try:
            source.backup(destination)
            destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            destination.execute("PRAGMA journal_mode=DELETE")
        finally:
            destination.close()
            source.close()
        _tier_snapshot(temp_db, selected_tier)
        integrity = connect(temp_db)
        try:
            result = integrity.execute("PRAGMA integrity_check").fetchone()
            if result is None or result["integrity_check"] != "ok":
                raise BackupError("snapshot database failed integrity_check")
        finally:
            integrity.close()
        source_rows = _source_members(temp_db)
        sources: list[
            tuple[dict[str, Any], Path, int, str, str, int, tuple[int, int, int]]
        ] = []
        for row in source_rows:
            (
                source_path,
                original_size,
                content_hash,
                stored_hash,
                stored_size,
                file_stamp,
            ) = _verified_stored_source(row)
            sources.append(
                (
                    row,
                    source_path,
                    original_size,
                    content_hash,
                    stored_hash,
                    stored_size,
                    file_stamp,
                )
            )
        policy = load_backup_policy()
        if len(sources) + 2 > policy.max_members:
            raise BackupError("backup exceeds configured member-count limit")
        if (
            temp_db.stat().st_size + sum(source[5] for source in sources)
            > policy.max_archive_bytes
        ):
            raise BackupError("backup content exceeds configured expanded-size limit")
        with tempfile.NamedTemporaryFile(
            prefix=".backup-", suffix=".tmp", dir=root, delete=False
        ) as handle:
            staging = Path(handle.name)
        manifest: dict[str, Any] = {
            "format": "stacks-backup",
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "tier": selected_tier,
            "compression": prefs.compression,
            "members": [],
            "sources": [],
        }
        with zipfile.ZipFile(
            staging,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=_COMPRESSION_LEVELS[prefs.compression],
            allowZip64=True,
        ) as archive:
            manifest["members"].append(
                _archive_file(archive, "database.sqlite", temp_db)
            )
            for (
                row,
                path,
                original_size,
                content_hash,
                stored_hash,
                stored_size,
                file_stamp,
            ) in sources:
                member = (
                    f"raw/{UUID(str(row['course_id']))}/"
                    f"{UUID(str(row['source_id']))}.bin"
                )
                info = _archive_file(archive, member, path)
                after = path.stat()
                if (
                    info["sha256"] != stored_hash
                    or info["size_bytes"] != stored_size
                    or (after.st_size, after.st_mtime_ns, after.st_ino) != file_stamp
                ):
                    raise BackupError(
                        f"source changed while backing up: {row['source_id']}"
                    )
                manifest["members"].append(info)
                manifest["sources"].append(
                    {
                        "course_id": str(row["course_id"]),
                        "source_id": str(row["source_id"]),
                        "path": member,
                        "stored_encoding": row["stored_encoding"],
                        "file_hash": row["file_hash"],
                        "content_sha256": content_hash,
                        "original_size_bytes": original_size,
                        "stored_size_bytes": info["size_bytes"],
                    }
                )
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            )
        if staging.stat().st_size > policy.max_archive_bytes:
            raise BackupError("backup exceeds configured archive-size limit")
        staging.replace(final_path)
        _prune(prefs.keep_count)
        archive_hash, archive_size = _digest(final_path)
        _save_status(success_at=utc_now())
        return BackupInfo(
            id=backup_id,
            filename=final_path.name,
            created_at=datetime.now(UTC),
            size_bytes=archive_size,
            tier=selected_tier,
            compression=prefs.compression,
            sha256=archive_hash,
        )
    except BaseException as error:
        _save_status(error=str(error)[:1000])
        raise
    finally:
        if temp_db is not None:
            temp_db.unlink(missing_ok=True)
            Path(f"{temp_db}-wal").unlink(missing_ok=True)
            Path(f"{temp_db}-shm").unlink(missing_ok=True)
        if staging is not None:
            staging.unlink(missing_ok=True)
        _CREATE_LOCK.release()


def list_backups() -> list[BackupInfo]:
    result: list[BackupInfo] = []
    for path in sorted(
        _backup_root().glob("backup-*.zip"), key=lambda p: p.name, reverse=True
    ):
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = _read_manifest(archive, verify_content=False)
            created = datetime.fromisoformat(manifest["created_at"])
            digest, size = _digest(path)
            backup_id = path.stem.rsplit("-", 1)[-1]
            result.append(
                BackupInfo(
                    id=backup_id,
                    filename=path.name,
                    created_at=created,
                    size_bytes=size,
                    tier=manifest["tier"],
                    compression=manifest["compression"],
                    sha256=digest,
                )
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            zipfile.BadZipFile,
            InvalidBackupError,
        ):
            logger.warning("skipping invalid backup %s", path.name)
    return result


def _safe_member(name: str) -> bool:
    if ":" in name or "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name:
        return False
    if name in ("manifest.json", "database.sqlite"):
        return True
    parts = path.parts
    if len(parts) != 3 or parts[0] != "raw" or not parts[2].endswith(".bin"):
        return False
    try:
        course_id = str(UUID(parts[1]))
        source_id = str(UUID(parts[2][:-4]))
    except ValueError:
        return False
    return course_id == parts[1] and f"{source_id}.bin" == parts[2]


def _read_manifest(
    archive: zipfile.ZipFile, *, verify_content: bool = True
) -> dict[str, Any]:
    infos = archive.infolist()
    policy = load_backup_policy()
    names = [info.filename for info in infos]
    if len(names) > policy.max_members or len(names) != len(set(names)):
        raise InvalidBackupError("archive has duplicate or excessive members")
    if any(not _safe_member(name) for name in names):
        raise InvalidBackupError("archive contains an unsafe path")
    if "manifest.json" not in names or names.count("database.sqlite") != 1:
        raise InvalidBackupError("archive is missing required members")
    if sum(info.file_size for info in infos) > policy.max_archive_bytes:
        raise InvalidBackupError("archive expands beyond the safety limit")
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
        raise InvalidBackupError("archive manifest is invalid") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "stacks-backup"
        or manifest.get("version") != 1
        or manifest.get("tier") not in ("full", "partial", "heavy")
        or not isinstance(manifest.get("members"), list)
        or not isinstance(manifest.get("sources"), list)
    ):
        raise InvalidBackupError("archive manifest has an unsupported format")
    if manifest.get("compression") not in ("fast", "balanced", "maximum"):
        raise InvalidBackupError("archive compression value is invalid")
    if any(not isinstance(item, dict) for item in manifest["members"]):
        raise InvalidBackupError("manifest contains an invalid member entry")
    if any(not isinstance(item, dict) for item in manifest["sources"]):
        raise InvalidBackupError("manifest contains an invalid source entry")
    listed = {item.get("path"): item for item in manifest["members"]}
    expected = set(names) - {"manifest.json"}
    if set(listed) != expected:
        raise InvalidBackupError("manifest member list does not match the archive")
    for name, metadata in listed.items():
        if (
            not isinstance(name, str)
            or not _safe_member(name)
            or type(metadata.get("size_bytes")) is not int
            or metadata["size_bytes"] < 0
            or not isinstance(metadata.get("sha256"), str)
            or len(metadata["sha256"]) != 64
        ):
            raise InvalidBackupError("manifest contains invalid member metadata")
        if metadata["size_bytes"] != archive.getinfo(name).file_size:
            raise InvalidBackupError("member size does not match manifest")
        if verify_content:
            digest = hashlib.sha256()
            with archive.open(name) as member:
                while chunk := member.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != metadata.get("sha256"):
                raise InvalidBackupError(f"checksum mismatch for {name}")
    return manifest


def _validate_schema(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"] for row in conn.execute(get(_FILE, "schema_table_names")).fetchall()
    }
    required = {
        "schema_migrations",
        "courses",
        "sources",
        "locators",
        "chunks",
        "chunk_embeddings",
        "citation_snapshots",
        "pending_ingestion",
        "ingestion_runs",
        "ingestion_stage_runs",
        "ingestion_history",
        "retrieval_traces",
        "app_settings",
        "course_memories",
        "conversations",
        "messages",
        "artifacts",
        "artifact_versions",
        "practice_suites",
        "practice_runs",
        "practice_assessments",
        "learning_observations",
        "learning_experiments",
        "core_method_observations",
        "work_sessions",
        "work_documents",
        "work_turns",
    }
    versions_present = {
        row["version"] for row in conn.execute(get(_FILE, "schema_versions"))
    }
    if "014" in versions_present:
        required.update({"source_indexes", "passage_containers", "passage_windows"})
    missing = required - existing
    if missing:
        raise InvalidBackupError(
            "backup database is missing required tables: " + ", ".join(sorted(missing))
        )
    rows = conn.execute(get(_FILE, "schema_versions")).fetchall()
    versions: list[int] = []
    for row in rows:
        version = row["version"]
        if not isinstance(version, str) or re.fullmatch(r"\d{3}", version) is None:
            raise InvalidBackupError("backup database has an invalid schema version")
        versions.append(int(version))
    known = [
        int(path.name[:3]) for path in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")
    ]
    if not versions or not known or max(versions) > max(known):
        raise InvalidBackupError("backup database was created by a newer schema")


def _validate_snapshot(path: Path, manifest: dict[str, Any]) -> None:
    conn = connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        _validate_schema(conn)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity["integrity_check"] != "ok":
            raise InvalidBackupError("backup database failed integrity_check")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise InvalidBackupError("backup database has foreign-key errors")
        rows = [dict(row) for row in conn.execute(get(_FILE, "backup_source_rows"))]
    except sqlite3.Error as error:
        raise InvalidBackupError("backup does not contain a Stacks database") from error
    finally:
        conn.close()
    for item in manifest["sources"]:
        try:
            if not isinstance(item.get("course_id"), str) or not isinstance(
                item.get("source_id"), str
            ):
                raise ValueError("missing source ids")
            course_id = str(UUID(item["course_id"]))
            source_id = str(UUID(item["source_id"]))
        except (ValueError, KeyError, TypeError) as error:
            raise InvalidBackupError("manifest source identity is invalid") from error
        if (
            course_id != item["course_id"]
            or source_id != item["source_id"]
            or item.get("path") != f"raw/{course_id}/{source_id}.bin"
            or item.get("stored_encoding") not in ("identity", "gzip")
            or type(item.get("stored_size_bytes")) is not int
            or item["stored_size_bytes"] < 0
            or type(item.get("original_size_bytes")) is not int
            or item["original_size_bytes"] < 0
            or (
                item.get("file_hash") is not None
                and (
                    not isinstance(item.get("file_hash"), str)
                    or re.fullmatch(r"[a-f0-9]{64}", item["file_hash"]) is None
                )
            )
            or re.fullmatch(r"[a-f0-9]{64}", str(item.get("content_sha256"))) is None
        ):
            raise InvalidBackupError("manifest source metadata is invalid")
    by_source = {item["source_id"]: item for item in manifest["sources"]}
    if len(by_source) != len(manifest["sources"]) or len(rows) != len(by_source):
        raise InvalidBackupError("source list does not match snapshot database")
    for row in rows:
        source_id = str(row["source_id"])
        item = by_source.get(source_id)
        if item is None or item.get("course_id") != str(row["course_id"]):
            raise InvalidBackupError("source metadata does not match snapshot")
        if (
            item.get("file_hash") != row["file_hash"]
            or item.get("stored_encoding") != row["stored_encoding"]
            or item.get("stored_size_bytes") != row["size_bytes"]
            or not isinstance(item.get("content_sha256"), str)
            or (row["file_hash"] and item.get("content_sha256") != row["file_hash"])
        ):
            raise InvalidBackupError(f"source metadata mismatch: {source_id}")


def _restore_into(archive_path: Path, destination: Path) -> None:
    policy = load_backup_policy()
    if archive_path.stat().st_size > policy.max_archive_bytes:
        raise InvalidBackupError("archive exceeds configured size limit")
    if destination.exists() and (
        not destination.is_dir() or any(destination.iterdir())
    ):
        raise BackupError("restore destination must be a new empty data folder")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stacks-restore-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            manifest = _read_manifest(archive)
            db_path = staging / DATABASE_FILENAME
            with (
                archive.open("database.sqlite") as source,
                db_path.open("wb") as target,
            ):
                shutil.copyfileobj(source, target, 1024 * 1024)
            _validate_snapshot(db_path, manifest)
            conn = connect(db_path)
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(get(_FILE, "sanitize_source_uris"), {"uri_prefix": "raw/"})
                # Restored preferences must not reactivate an old endpoint,
                # certificate identity, export path, or machine-specific path.
                conn.execute(get(_FILE, "reset_settings"))
                conn.execute(get("ingestion", "fail_interrupted_stage_runs"))
                conn.execute(get("ingestion", "fail_interrupted_runs"))
                conn.execute(get(_FILE, "reset_restored_claims"))
                if manifest["tier"] in ("partial", "heavy"):
                    for row in conn.execute(
                        get(_FILE, "restore_indexed_sources")
                    ).fetchall():
                        params = {
                            "source_id": row["source_id"],
                            "course_id": row["course_id"],
                        }
                        conn.execute(
                            get("sources", "snapshot_citations_before_reindex"),
                            params,
                        )
                        conn.execute(
                            get(_FILE, "mark_restored_source_for_reindex"), params
                        )
                        conn.execute(get(_FILE, "queue_restored_source"), params)
                conn.commit()
                if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise InvalidBackupError("restored database has foreign-key errors")
                integrity = conn.execute("PRAGMA integrity_check").fetchone()
                if integrity is None or integrity["integrity_check"] != "ok":
                    raise InvalidBackupError("restored database failed integrity_check")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("PRAGMA journal_mode=DELETE")
            finally:
                conn.close()
            Path(f"{db_path}-wal").unlink(missing_ok=True)
            Path(f"{db_path}-shm").unlink(missing_ok=True)
            raw_root = staging / "raw"
            for item in manifest["sources"]:
                course_id = str(UUID(item["course_id"]))
                source_id = str(UUID(item["source_id"]))
                expected_name = f"raw/{course_id}/{source_id}.bin"
                if item.get("path") != expected_name:
                    raise InvalidBackupError("source has a noncanonical archive path")
                source_output = raw_root / course_id / f"{source_id}.bin"
                source_output.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open(expected_name) as source,
                    source_output.open("wb") as output,
                ):
                    shutil.copyfileobj(source, output, 1024 * 1024)
                if source_output.stat().st_size != item.get("stored_size_bytes"):
                    raise InvalidBackupError(
                        f"stored source size mismatch: {source_id}"
                    )
                digest = hashlib.sha256()
                raw_size = 0
                opener = gzip.open if item.get("stored_encoding") == "gzip" else open
                max_original = load_lifecycle_policy().max_raw_upload_bytes
                with opener(source_output, "rb") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        raw_size += len(chunk)
                        if raw_size > max_original:
                            raise InvalidBackupError(
                                f"source expands beyond upload limit: {source_id}"
                            )
                actual_content_hash = digest.hexdigest()
                if (
                    actual_content_hash != item.get("content_sha256")
                    or (
                        item.get("file_hash")
                        and actual_content_hash != item.get("file_hash")
                    )
                    or raw_size != item.get("original_size_bytes")
                ):
                    raise InvalidBackupError(
                        f"source content verification failed: {source_id}"
                    )
        if destination.exists():
            destination.rmdir()
        staging.replace(destination)
    except (
        zipfile.BadZipFile,
        sqlite3.Error,
        KeyError,
        TypeError,
        ValueError,
        EOFError,
        zlib.error,
        gzip.BadGzipFile,
    ) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise InvalidBackupError("backup archive is malformed or corrupt") from error
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def recover_backup(backup_id: str) -> Path:
    if not backup_id.isalnum() or len(backup_id) != 32:
        raise ValueError("invalid backup id")
    archives = [
        p for p in _backup_root().glob("backup-*.zip") if p.stem.endswith(backup_id)
    ]
    if len(archives) != 1:
        raise FileNotFoundError("backup not found")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = (
        Path(get_settings().data_dir) / "recovered" / f"restore-{stamp}-{backup_id[:8]}"
    )
    _restore_into(archives[0], destination)
    return destination


async def run_forever(stop: asyncio.Event) -> None:
    """Check the configured due time; archive creation/compression runs off-loop."""
    while not stop.is_set():
        try:
            prefs = get_preferences()
            status = get_status()
            if prefs.enabled and (
                status.last_success_at is None
                or status.last_success_at
                <= utc_now() - timedelta(hours=prefs.interval_hours)
            ):
                await asyncio.to_thread(create_backup)
        except Exception:
            logger.exception("automatic backup failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=60)
