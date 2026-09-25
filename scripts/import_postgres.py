"""One-off import from the old hosted-era Postgres database (plan §12,
Phase 2, optional).

Copies each active course owned by a real account (probe/test accounts
on `.invalid` domains are skipped) and its sources into the local SQLite
database, keeping the same ids so the raw files already under the
storage root line up. Derived rows (chunks, embeddings, runs) are NOT
copied: every imported source is queued for ingestion so the local
pipeline rebuilds them. Idempotent — courses already present are skipped.

Needs the Postgres driver, which the app itself no longer depends on:

    .venv/Scripts/python -m pip install "psycopg[binary]"
    .venv/Scripts/python -m scripts.import_postgres \\
        "host=localhost dbname=course_assistant user=postgres password=..."
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        print('psycopg is not installed: pip install "psycopg[binary]"')
        return 2

    from src.backend.common import storage
    from src.backend.common.db import connection
    from src.backend.common.migrate import migrate
    from src.backend.ingest import runs

    migrate()
    with psycopg.connect(argv[0], row_factory=dict_row) as pg:
        courses = pg.execute(
            "SELECT course.course_id, course.name FROM courses AS course"
            " JOIN users AS owner ON owner.user_id = course.owner_user_id"
            " WHERE course.lifecycle_status = 'active'"
            "   AND owner.email NOT LIKE '%%.invalid'"
            " ORDER BY course.name"
        ).fetchall()
        sources = pg.execute(
            "SELECT source_id, course_id, filename, mime_type, source_type,"
            " file_hash, size_bytes, stored_encoding, created_at FROM sources"
            " WHERE course_id = ANY(%s)",
            ([course["course_id"] for course in courses],),
        ).fetchall()

    imported_courses = imported_sources = 0
    with connection() as conn:
        for course in courses:
            exists = conn.execute(
                "SELECT 1 FROM courses WHERE course_id = ?", (course["course_id"],)
            ).fetchone()
            if exists:
                print(f"skip (already imported): {course['name']}")
                continue
            conn.execute(
                "INSERT INTO courses (course_id, name) VALUES (?, ?)",
                (course["course_id"], course["name"]),
            )
            imported_courses += 1
            for source in sources:
                if source["course_id"] != course["course_id"]:
                    continue
                path = storage.source_disk_path(
                    source["course_id"], source["source_id"]
                )
                if not path.exists():
                    print(f"  skip {source['filename']}: stored file missing")
                    continue
                conn.execute(
                    "INSERT INTO sources (source_id, course_id, filename,"
                    " mime_type, source_type, uri, status, file_hash,"
                    " size_bytes, stored_encoding, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, 'uploaded', ?, ?, ?, ?)",
                    (
                        source["source_id"],
                        source["course_id"],
                        source["filename"],
                        source["mime_type"],
                        source["source_type"],
                        str(path),
                        source["file_hash"],
                        source["size_bytes"],
                        source["stored_encoding"],
                        source["created_at"],
                    ),
                )
                runs.enqueue_pending(
                    conn, source["source_id"], source["course_id"], "imported"
                )
                imported_sources += 1
                print(f"  + {source['filename']}")
            print(f"imported: {course['name']}")
        conn.commit()
    print(
        f"{imported_courses} course(s), {imported_sources} source(s) imported;"
        " sources ingest on the app's next worker pass"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
