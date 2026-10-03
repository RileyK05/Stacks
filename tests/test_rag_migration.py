from pathlib import Path
from uuid import uuid4

from src.backend.common import migrate as migrations
from src.backend.common.db import connect
from src.backend.ingest import runs


def test_retired_office_version_fields_survive_upgrade(tmp_path, monkeypatch):
    path = tmp_path / "office-history.db"
    pending = migrations._pending_migrations
    with monkeypatch.context() as scope:
        scope.setattr(
            migrations,
            "_pending_migrations",
            lambda: [(v, p) for v, p in pending() if int(v) <= 11],
        )
        migrations.migrate(path)
    conn = connect(path)
    course, artifact = uuid4(), uuid4()
    try:
        for table in ("artifacts", "artifact_versions"):
            for column, kind in (
                ("filename", "TEXT"),
                ("file_sha256", "TEXT"),
                ("file_size", "INTEGER"),
                ("mime_type", "TEXT"),
            ):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        conn.execute("ALTER TABLE artifact_versions ADD COLUMN ops JSON")
        conn.execute(
            "INSERT INTO courses(course_id,name) VALUES (?, 'History')", (course,)
        )
        conn.execute(
            "INSERT INTO artifacts(artifact_id,course_id,kind,title,content,filename)"
            " VALUES (?, ?, 'doc', 'Draft', '{\"markdown\":\"Original\"}',"
            " 'paper.docx')",
            (artifact, course),
        )
        conn.execute(
            "INSERT INTO artifact_versions"
            "(artifact_id,version,title,content,sources,author,note,filename,ops)"
            " VALUES (?, 1, 'Draft', '{\"markdown\":\"Original\"}', '[]', 'you',"
            " 'Existing note', 'draft.docx', '[{\"insert\":\"Original\"}]')",
            (artifact,),
        )
        conn.commit()
    finally:
        conn.close()
    migrations.migrate(path)
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT origin FROM artifacts WHERE artifact_id = ?", (artifact,)
        ).fetchone()
        assert row["origin"]["legacy_office_file"]["filename"] == "paper.docx"
        history = row["origin"]["legacy_office_versions"][0]
        assert history["filename"] == "draft.docx"
        assert history["ops"] == [{"insert": "Original"}]
        version = conn.execute("SELECT content, note FROM artifact_versions").fetchone()
        assert version["content"] == {"markdown": "Original"}
        assert version["note"] == "Existing note"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()


def test_old_annotations_and_history_survive_retiring_the_old_stores(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "legacy.db"
    pending = migrations._pending_migrations
    with monkeypatch.context() as scope:
        scope.setattr(
            migrations,
            "_pending_migrations",
            lambda: [(v, p) for v, p in pending() if int(v) <= 13],
        )
        migrations.migrate(path)
    course, source, locator, passage = [uuid4() for _ in range(4)]
    concept, note, run = [uuid4() for _ in range(3)]
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO courses(course_id,name) VALUES (?, 'Calculus')", (course,)
        )
        conn.execute(
            "INSERT INTO sources"
            "(source_id,course_id,filename,mime_type,source_type,status)"
            " VALUES (?, ?, 'notes.txt', 'text/plain', 'notes', 'indexed')",
            (source, course),
        )
        conn.execute(
            "INSERT INTO locators(locator_id,source_id,locator_type,start,label)"
            " VALUES (?, ?, 'section', '0', 'Limits')",
            (locator, source),
        )
        conn.execute(
            "INSERT INTO chunks(chunk_id,source_id,locator_id,chunk_index,text)"
            " VALUES (?, ?, ?, 0, 'A limit describes nearby behavior.')",
            (passage, source, locator),
        )
        conn.execute(
            "INSERT INTO concepts(concept_id,course_id,name,definition,synonyms)"
            " VALUES (?, ?, 'limit', 'Nearby behavior.', '[" + '"boundary"' + "]')",
            (concept, course),
        )
        conn.execute(
            "INSERT INTO concept_chunks(concept_id,chunk_id) VALUES (?, ?)",
            (concept, passage),
        )
        conn.execute(
            "INSERT INTO memory_objects(memory_id,concept_id,source_id,kind,content)"
            " VALUES (?, ?, ?, 'concept', 'Preserve this course note exactly.')",
            (note, concept, source),
        )
        conn.execute(
            "INSERT INTO memory_object_evidence(evidence_id,memory_id,chunk_id)"
            " VALUES (?, ?, ?)",
            (uuid4(), note, passage),
        )
        conn.execute(
            "INSERT INTO course_memories"
            "(memory_id,course_id,course_ref,name,summary,summary_version)"
            " VALUES (?, ?, ?, 'Calculus', 'Existing student focus.', 'v1')",
            (uuid4(), course, course),
        )
        conn.execute(
            "INSERT INTO ingestion_runs(run_id,source_id,pipeline_version)"
            " VALUES (?, ?, '4')",
            (run, source),
        )
        conn.execute(
            "INSERT INTO ingestion_stage_runs"
            "(stage_run_id,run_id,stage,position,handler_version)"
            " VALUES (?, ?, 'update_toc', 0, '1')",
            (uuid4(), run),
        )
        conn.commit()
    finally:
        conn.close()
    assert migrations.migrate(path) == ["014", "015", "016", "017"]
    conn = connect(path)
    try:
        annotations = conn.execute(
            "SELECT artifact_id,content,sources,origin FROM artifacts ORDER BY title"
        ).fetchall()
        assert {a["artifact_id"] for a in annotations} == {concept, note}
        retained_note = next(a for a in annotations if a["artifact_id"] == note)
        assert retained_note["content"]["markdown"].endswith(
            "Preserve this course note exactly."
        )
        assert retained_note["sources"] == [str(passage)]
        assert (
            conn.execute(
                "SELECT text FROM chunks WHERE chunk_id = ?", (passage,)
            ).fetchone()["text"]
            == "A limit describes nearby behavior."
        )
        assert (
            conn.execute(
                "SELECT summary FROM course_memories WHERE course_id = ?", (course,)
            ).fetchone()["summary"]
            == "Existing student focus."
        )
        history = runs.stage_run(conn, run, "update_toc")
        assert history is not None and history.stage == "update_toc"
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert not tables & {
            "concepts",
            "dependencies",
            "memory_objects",
            "tables_of_contents",
            "toc_entries",
            "graph_clusters",
        }
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
