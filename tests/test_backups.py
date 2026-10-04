from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from src.backend.common import backups, course_memory
from src.backend.common.config import get_settings
from src.backend.common.db import connect, connection


def _seed_data() -> tuple[str, str, bytes]:
    course_id, source_id = str(uuid4()), str(uuid4())
    original = (b"source material with exact bytes\n" * 5000) + b"end"
    raw_path = Path(get_settings().storage_root) / course_id / f"{source_id}.bin"
    raw_path.parent.mkdir(parents=True)
    with (
        raw_path.open("wb") as target,
        gzip.GzipFile(fileobj=target, mode="wb", compresslevel=6, mtime=0) as zipped,
    ):
        zipped.write(original)
    stored_size = raw_path.stat().st_size
    ids = {
        name: str(uuid4())
        for name in (
            "chat",
            "message",
            "artifact",
            "suite",
            "run",
            "session",
            "locator",
            "chunk",
            "ingestion_run",
            "stage_run",
        )
    }
    with connection() as conn:
        conn.execute(
            "INSERT INTO courses(course_id,name) VALUES (?,?)", (course_id, "Calculus")
        )
        conn.execute(
            """INSERT INTO sources(source_id,course_id,filename,mime_type,source_type,
               uri,status,file_hash,size_bytes,stored_encoding)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                source_id,
                course_id,
                "notes.txt",
                "text/plain",
                "notes",
                str(raw_path),
                "indexed",
                hashlib.sha256(original).hexdigest(),
                stored_size,
                "gzip",
            ),
        )
        conn.execute(
            """INSERT INTO locators(locator_id,source_id,locator_type,start,label)
               VALUES(?,?,?,?,?)""",
            (ids["locator"], source_id, "page", "1", "Page 1"),
        )
        conn.execute(
            """INSERT INTO chunks(chunk_id,source_id,locator_id,chunk_index,text)
               VALUES(?,?,?,?,?)""",
            (
                ids["chunk"],
                source_id,
                ids["locator"],
                0,
                "cited original passage exact",
            ),
        )
        conn.execute(
            """INSERT INTO course_memories(memory_id,course_id,course_ref,name,
               summary,summary_version) VALUES(?,?,?,?,?,?)""",
            (str(uuid4()), course_id, course_id, "Calculus", "Course focus", "v1"),
        )
        conn.execute(
            """INSERT INTO conversations(conversation_id,course_id,title,summary)
               VALUES(?,?,?,?)""",
            (ids["chat"], course_id, "Chat", "private rolling summary"),
        )
        conn.execute(
            """INSERT INTO messages(message_id,conversation_id,seq,role,text,payload)
               VALUES(?,?,?,?,?,?)""",
            (ids["message"], ids["chat"], 1, "user", "hidden chat text", "{}"),
        )
        conn.execute(
            """INSERT INTO artifacts(artifact_id,course_id,kind,title,content,
               sources,origin) VALUES(?,?,?,?,?,?,?)""",
            (
                ids["artifact"],
                course_id,
                "doc",
                "Study notes",
                json.dumps({"text": "kept text"}),
                json.dumps([ids["chunk"]]),
                json.dumps(
                    {
                        "by": "chat",
                        "conversation_id": ids["chat"],
                        "message_id": ids["message"],
                        "item_index": 0,
                        "adopted": True,
                        "model": "local-model",
                    }
                ),
            ),
        )
        conn.execute(
            """INSERT INTO artifact_versions(artifact_id,version,title,content,
               sources,author,note) VALUES(?,?,?,?,?,?,?)""",
            (
                ids["artifact"],
                1,
                "Study notes",
                json.dumps({"text": "kept text"}),
                json.dumps([ids["chunk"]]),
                "you",
                "saved",
            ),
        )
        conn.execute(
            """INSERT INTO work_sessions(session_id,course_id,title,purpose)
               VALUES(?,?,?,?)""",
            (ids["session"], course_id, "Draft", "Saved work"),
        )
        conn.execute(
            """INSERT INTO pending_ingestion
               (source_id,course_id,reason,claimed_at,claimed_runs,claimed_runs_max,heartbeat_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                source_id,
                course_id,
                "interrupted before backup",
                "2026-09-30T10:00:00.000000Z",
                4,
                5,
                "2026-09-30T10:01:00.000000Z",
            ),
        )
        conn.execute(
            """INSERT INTO ingestion_runs
               (run_id,source_id,pipeline_version,status,configuration)
               VALUES(?,?,?,'running','{}')""",
            (ids["ingestion_run"], source_id, "test-pipeline"),
        )
        conn.execute(
            """INSERT INTO ingestion_stage_runs
               (stage_run_id,run_id,stage,position,max_attempts,handler_version,status)
               VALUES(?,?,?,0,2,'test','running')""",
            (ids["stage_run"], ids["ingestion_run"], "extract"),
        )
        conn.execute(
            "INSERT INTO work_documents(session_id,revision,payload) VALUES(?,?,?)",
            (ids["session"], 1, json.dumps({"text": "saved work document"})),
        )
        conn.execute(
            """INSERT INTO work_turns(request_id,session_id,action,instruction,
               selection,document_revision,reply) VALUES(?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                ids["session"],
                "review",
                "hidden instruction",
                "hidden selection",
                1,
                "{}",
            ),
        )
        conn.execute(
            """INSERT INTO practice_suites(suite_id,course_id,title,questions,
               evidence,origin) VALUES(?,?,?,?,?,?)""",
            (
                ids["suite"],
                course_id,
                "Quiz",
                '[{"prompt":"retained practice question"}]',
                "[]",
                json.dumps({"message_id": ids["message"], "item_index": 0}),
            ),
        )
        conn.execute(
            """INSERT INTO practice_runs(run_id,suite_id,course_id,answers,helped,
               requested_help,policy_version) VALUES(?,?,?,?,?,?,?)""",
            (ids["run"], ids["suite"], course_id, "[]", "[]", "[]", "v1"),
        )
        help_id = str(uuid4())
        conn.execute(
            """INSERT INTO practice_help(help_id,suite_id,run_ref,question_index,
               kind,status,claim,content) VALUES(?,?,?,?,?,?,?,?)""",
            (
                help_id,
                ids["suite"],
                ids["run"],
                0,
                "hint",
                "ready",
                str(uuid4()),
                '{"text":"private quiz assistance","sources":[1]}',
            ),
        )
        conn.execute(
            """INSERT INTO practice_feedback(suite_id,question_index,target,help_id,
               rating,reason) VALUES(?,?,?,?,?,?)""",
            (ids["suite"], 0, "hint", help_id, "bad", "private content opinion"),
        )
        conn.execute(
            """INSERT INTO learning_observations(observation_id,course_id,run_ref,
               suite_ref,question_index,fingerprint,topic,capability,correct,
               helped,fresh,evidence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                course_id,
                ids["run"],
                ids["suite"],
                0,
                "f",
                "limits",
                "application",
                1,
                0,
                1,
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO usage_ledger(ledger_id,task,provider,model,usage_reported) "
            "VALUES(?,?,?,?,0)",
            (str(uuid4()), "answer", "local", "local-model"),
        )
        conn.execute(
            "INSERT INTO app_settings(key,value) VALUES(?,?)",
            ("learning.preferred_method", '"visual"'),
        )
        conn.execute(
            "INSERT INTO app_settings(key,value) VALUES(?,?)",
            ("provider.interactive", '{"base_url":"http://private"}'),
        )
        conn.commit()
    return course_id, source_id, original


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])


def _archive_with_database_mutation(
    source_archive: Path, target_archive: Path, temp_db: Path, mutation: str
) -> None:
    with zipfile.ZipFile(source_archive) as source:
        database = source.read("database.sqlite")
        manifest = json.loads(source.read("manifest.json"))
        temp_db.write_bytes(database)
        edited = sqlite3.connect(temp_db)
        if mutation == "newer_schema":
            edited.execute("INSERT INTO schema_migrations(version) VALUES('999')")
        else:
            edited.execute("DROP TABLE ingestion_history")
        edited.commit()
        edited.close()
        database = temp_db.read_bytes()
        for member in manifest["members"]:
            if member["path"] == "database.sqlite":
                member["size_bytes"] = len(database)
                member["sha256"] = hashlib.sha256(database).hexdigest()
        with zipfile.ZipFile(target_archive, "w") as target:
            for item in source.infolist():
                if item.filename == "database.sqlite":
                    data = database
                elif item.filename == "manifest.json":
                    data = json.dumps(manifest).encode()
                else:
                    data = source.read(item.filename)
                target.writestr(item, data)


@pytest.mark.parametrize("tier", ["full", "partial", "heavy"])
def test_tiers_preserve_actual_data_and_restore_exact_sources(
    tier: str, tmp_path: Path
) -> None:
    course_id, source_id, original = _seed_data()
    with connection() as live:
        hidden_message_id = live.execute("SELECT message_id FROM messages").fetchone()[
            "message_id"
        ]
    prefs = backups.get_preferences().model_copy(update={"tier": tier})
    backups.update_preferences(prefs)
    info = backups.create_backup()
    assert info.tier == tier
    assert info.compression == "balanced"
    archive_path = Path(get_settings().data_dir) / "backups" / info.filename
    with zipfile.ZipFile(archive_path) as archive:
        snapshot_bytes = archive.read("database.sqlite")
    if tier == "full":
        assert b"hidden chat text" in snapshot_bytes
        assert b"private rolling summary" in snapshot_bytes
        assert str(hidden_message_id).encode() in snapshot_bytes
    else:
        assert b"hidden chat text" not in snapshot_bytes
        assert b"private rolling summary" not in snapshot_bytes
        assert b"http://private" not in snapshot_bytes
        assert str(hidden_message_id).encode() not in snapshot_bytes
        if tier == "heavy":
            assert b"Course focus" not in snapshot_bytes
            assert b"visual" not in snapshot_bytes
            assert b"private quiz assistance" not in snapshot_bytes
            assert b"private content opinion" not in snapshot_bytes
        assert b"retained practice question" in snapshot_bytes
    restored = tmp_path / f"restored-{tier}"
    backups._restore_into(archive_path, restored)

    db = sqlite3.connect(restored / "course_assistant.db")
    db.row_factory = sqlite3.Row
    try:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        assert db.execute("SELECT title FROM artifacts").fetchone()[0] == "Study notes"
        assert (
            db.execute("SELECT content FROM artifact_versions").fetchone()[0]
            == '{"text": "kept text"}'
        )
        assert (
            db.execute("SELECT payload FROM work_documents").fetchone()[0]
            == '{"text": "saved work document"}'
        )
        assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM practice_suites").fetchone()[0] == 1
        assert _count(db, "practice_help") == (0 if tier == "heavy" else 1)
        assert _count(db, "practice_feedback") == (0 if tier == "heavy" else 1)
        expected_source_status = "indexed" if tier == "full" else "uploaded"
        assert (
            db.execute("SELECT status FROM sources").fetchone()[0]
            == expected_source_status
        )
        pending = db.execute(
            "SELECT reason,claimed_at,claimed_runs,heartbeat_at "
            "FROM pending_ingestion WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        assert pending["claimed_at"] is None
        assert pending["claimed_runs"] == 0
        assert pending["heartbeat_at"] is None
        if tier == "full":
            assert pending["reason"] == "interrupted before backup"
            assert _count(db, "citation_snapshots") == 0
        else:
            assert pending["reason"] == "backup_restore_rebuild_vectors"
            citation = db.execute(
                "SELECT text FROM citation_snapshots WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            assert citation["text"] == "cited original passage exact"
        assert db.execute("SELECT status FROM ingestion_runs").fetchone()[0] == "failed"
        assert (
            db.execute("SELECT status FROM ingestion_stage_runs").fetchone()[0]
            == "failed"
        )
        saved_settings = dict(
            db.execute("SELECT key,value FROM app_settings").fetchall()
        )
        assert "provider.interactive" not in saved_settings
        assert "backups.preferences" in saved_settings
        origin = json.loads(db.execute("SELECT origin FROM artifacts").fetchone()[0])
        assert origin["model"] == "local-model"
        if tier == "full":
            assert json.loads(saved_settings["learning.preferred_method"]) == "visual"
            assert (
                db.execute("SELECT usage_reported FROM usage_ledger").fetchone()[0] == 0
            )
            assert (
                db.execute("SELECT text FROM messages").fetchone()[0]
                == "hidden chat text"
            )
            assert (
                db.execute("SELECT instruction FROM work_turns").fetchone()[0]
                == "hidden instruction"
            )
            assert "message_id" in origin and origin["adopted"] is True
            assert _count(db, "learning_observations") == 1
            assert _count(db, "practice_runs") == 1
        else:
            assert _count(db, "conversations") == 0
            assert _count(db, "messages") == 0
            assert _count(db, "work_turns") == 0
            assert _count(db, "usage_ledger") == 0
            assert "message_id" not in origin and "conversation_id" not in origin
            suite_origin = json.loads(
                db.execute("SELECT origin FROM practice_suites").fetchone()[0]
            )
            assert "message_id" not in suite_origin
            assert (
                "retained practice question"
                in db.execute("SELECT questions FROM practice_suites").fetchone()[0]
            )
            if tier == "partial":
                assert (
                    json.loads(saved_settings["learning.preferred_method"]) == "visual"
                )
                assert _count(db, "learning_observations") == 1
                assert _count(db, "practice_runs") == 1
                assert (
                    db.execute("SELECT summary FROM course_memories").fetchone()[0]
                    == "Course focus"
                )
            else:
                assert "learning.preferred_method" not in saved_settings
                assert _count(db, "learning_observations") == 0
                assert _count(db, "practice_runs") == 0
                assert _count(db, "course_memories") == 0
    finally:
        db.close()
    restored_source = restored / "raw" / course_id / f"{source_id}.bin"
    with gzip.open(restored_source, "rb") as source:
        assert source.read() == original
    if tier == "heavy":
        restored_db = connect(restored / "course_assistant.db")
        try:
            course_memory.refresh(restored_db, UUID(course_id))
            restored_db.commit()
            summary = restored_db.execute(
                "SELECT summary FROM course_memories WHERE course_id = ?",
                (course_id,),
            ).fetchone()["summary"]
            assert "Course: Calculus" in summary
            assert "Evidence snapshot:" not in summary
            assert restored_db.execute(
                "SELECT content FROM artifacts WHERE course_id = ?", (course_id,)
            ).fetchone()["content"] == {"text": "kept text"}
        finally:
            restored_db.close()


def test_bad_source_fails_without_removing_prior_backup(tmp_path: Path) -> None:
    _course, source_id, _original = _seed_data()
    first = backups.create_backup()
    source_path = Path(get_settings().storage_root) / _course / f"{source_id}.bin"
    source_path.write_bytes(b"changed stored bytes")
    with pytest.raises(backups.BackupError, match="source"):
        backups.create_backup()
    assert (Path(get_settings().data_dir) / "backups" / first.filename).is_file()
    assert backups.get_status().last_error


def test_retention_applies_after_successful_publish(tmp_path: Path) -> None:
    _seed_data()
    backups.update_preferences(
        backups.get_preferences().model_copy(update={"keep_count": 1})
    )
    first = backups.create_backup()
    second = backups.create_backup()
    files = list((Path(get_settings().data_dir) / "backups").glob("backup-*.zip"))
    assert len(files) == 1
    assert files[0].name == second.filename
    assert files[0].name != first.filename


def test_corrupt_archive_is_rejected_before_restore(tmp_path: Path) -> None:
    _seed_data()
    info = backups.create_backup()
    archive_path = Path(get_settings().data_dir) / "backups" / info.filename
    corrupt = tmp_path / "corrupt.zip"
    with (
        zipfile.ZipFile(archive_path) as source,
        zipfile.ZipFile(corrupt, "w") as target,
    ):
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "database.sqlite":
                data = data[:-1] + bytes([data[-1] ^ 0x01])
            target.writestr(item, data)
    with pytest.raises(backups.InvalidBackupError, match="checksum"):
        backups._restore_into(corrupt, tmp_path / "must-not-exist")


def test_non_object_manifest_is_rejected(tmp_path: Path) -> None:
    _seed_data()
    info = backups.create_backup()
    archive_path = Path(get_settings().data_dir) / "backups" / info.filename
    malformed = tmp_path / "malformed.zip"
    with (
        zipfile.ZipFile(archive_path) as source,
        zipfile.ZipFile(malformed, "w") as target,
    ):
        for item in source.infolist():
            target.writestr(
                item,
                "[]"
                if item.filename == "manifest.json"
                else source.read(item.filename),
            )
    with pytest.raises(backups.InvalidBackupError, match="unsupported format"):
        backups._restore_into(malformed, tmp_path / "bad-manifest")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("newer_schema", "newer schema"),
        ("missing_table", "missing required tables"),
    ],
)
def test_restore_rejects_unsupported_database_schema_before_publish(
    tmp_path: Path, mutation: str, message: str
) -> None:
    _seed_data()
    info = backups.create_backup()
    source_archive = Path(get_settings().data_dir) / "backups" / info.filename
    malformed = tmp_path / f"{mutation}.zip"
    _archive_with_database_mutation(
        source_archive, malformed, tmp_path / "edited.sqlite", mutation
    )
    destination = tmp_path / "rejected-restore"
    with pytest.raises(backups.InvalidBackupError, match=message):
        backups._restore_into(malformed, destination)
    assert not destination.exists()


def test_existing_nonempty_restore_destination_is_rejected(tmp_path: Path) -> None:
    _seed_data()
    info = backups.create_backup()
    archive_path = Path(get_settings().data_dir) / "backups" / info.filename
    destination = tmp_path / "occupied"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(backups.BackupError, match="new empty"):
        backups._restore_into(archive_path, destination)
    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_disabled_schedule_keeps_archives_and_does_not_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_data()
    created = backups.create_backup()
    backups.update_preferences(
        backups.get_preferences().model_copy(update={"enabled": False})
    )
    attempts: list[bool] = []
    stop = asyncio.Event()

    def forbidden_create() -> None:
        attempts.append(True)
        stop.set()

    async def end_wait(awaitable, timeout: float):
        del timeout
        awaitable.close()
        stop.set()
        raise TimeoutError

    monkeypatch.setattr(backups, "create_backup", forbidden_create)
    monkeypatch.setattr(backups.asyncio, "wait_for", end_wait)
    asyncio.run(backups.run_forever(stop))
    assert attempts == []
    assert [info.id for info in backups.list_backups()] == [created.id]


def test_create_lock_rejects_overlapping_backup(tmp_path: Path) -> None:
    _seed_data()
    assert backups._CREATE_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(backups.BackupError, match="already running"):
            backups.create_backup()
    finally:
        backups._CREATE_LOCK.release()


def test_source_changed_after_validation_prevents_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id, source_id, _original = _seed_data()
    existing = backups.create_backup()
    raw_path = Path(get_settings().storage_root) / course_id / f"{source_id}.bin"
    write_member = backups._archive_file

    def mutate_then_write(archive, name: str, path: Path):
        if name.startswith("raw/"):
            raw_path.write_bytes(raw_path.read_bytes() + b"changed")
        return write_member(archive, name, path)

    monkeypatch.setattr(backups, "_archive_file", mutate_then_write)
    with pytest.raises(backups.BackupError, match="changed while backing up"):
        backups.create_backup()
    assert (Path(get_settings().data_dir) / "backups" / existing.filename).is_file()


def test_backup_api_uses_generated_recovery_folder(client) -> None:
    overview = client.get("/settings/backups")
    assert overview.status_code == 200
    assert overview.json()["settings"]["enabled"] is False
    assert overview.json()["archive_dir"].endswith("backups")

    updated = client.put(
        "/settings/backups",
        json={
            "enabled": False,
            "tier": "partial",
            "compression": "fast",
            "interval_hours": 24,
            "keep_count": 5,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["settings"]["tier"] == "partial"
    created = client.post("/settings/backups/create")
    assert created.status_code == 201
    listed = client.get("/settings/backups/archives")
    assert listed.status_code == 200
    assert listed.json()["backups"][0]["id"] == created.json()["id"]

    recovered = client.post(
        "/settings/backups/recover", json={"backup_id": created.json()["id"]}
    )
    assert recovered.status_code == 201
    result = recovered.json()
    assert Path(result["database_path"]).is_file()
    assert Path(result["data_dir"]).parent.name == "recovered"
    assert result["restart_required"] is True
    assert "your current library was not changed" in result["instructions"]
    assert "Activate" in result["instructions"]
