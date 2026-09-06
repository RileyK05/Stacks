from uuid import uuid4

import pytest
from psycopg import sql
from src.backend.common.db import connection
from src.backend.common.migrate import MIGRATIONS_DIR
from src.backend.common.schemas import UserTier


def test_all_migrations_apply_to_empty_schema() -> None:
    schema_name = f"migration_test_{uuid4().hex}"
    with connection() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        conn.execute(
            sql.SQL("SET LOCAL search_path TO {}, public").format(
                sql.Identifier(schema_name)
            )
        )
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s",
                (schema_name,),
            ).fetchall()
        }
        assert "course_enrollments" in tables
        assert "ingestion_runs" in tables
        assert "ingestion_stage_runs" in tables
        assert "user_artifacts" in tables
        assert "tutor_profiles" in tables
        assert "user_subscriptions" in tables
        assert "generation_ledger" in tables
        assert "course_archive_access" in tables
        assert "storage_cleanup_jobs" in tables
        conn.rollback()


def test_new_user_defaults_to_free_tier() -> None:
    with connection() as conn:
        tier = conn.execute(
            "INSERT INTO users (name) VALUES ('Tierless') RETURNING tier"
        ).fetchone()[0]
        conn.rollback()
    assert tier == UserTier.FREE


def test_subscription_syncs_user_tier() -> None:
    with connection() as conn:
        user_id = conn.execute(
            "INSERT INTO users (name) VALUES ('Subbed') RETURNING user_id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO user_subscriptions (user_id, tier) VALUES (%s, 'paid')",
            (user_id,),
        )
        tier = conn.execute(
            "SELECT tier FROM users WHERE user_id = %s", (user_id,)
        ).fetchone()[0]
        assert tier == UserTier.PAID
        conn.execute(
            "UPDATE user_subscriptions SET ended_at = now() "
            "WHERE user_id = %s AND ended_at IS NULL",
            (user_id,),
        )
        tier = conn.execute(
            "SELECT tier FROM users WHERE user_id = %s", (user_id,)
        ).fetchone()[0]
        assert tier == UserTier.FREE
        conn.rollback()


def test_only_one_active_subscription_per_user() -> None:
    with connection() as conn:
        user_id = conn.execute(
            "INSERT INTO users (name) VALUES ('Double') RETURNING user_id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO user_subscriptions (user_id, tier) VALUES (%s, 'paid')",
            (user_id,),
        )
        with pytest.raises(Exception, match="user_subscription_one_active"):
            conn.execute(
                "INSERT INTO user_subscriptions (user_id, tier) "
                "VALUES (%s, 'paid')",
                (user_id,),
            )
        conn.rollback()


def test_user_delete_cascades_distilled_records() -> None:
    """Account hard-delete must not landmine on the distilled records the
    user owns; the deletion ceremony (7-day grace, archive summary) is
    owned by the account-deletion service, not by FK NO ACTION."""
    with connection() as conn:
        user_id = conn.execute(
            "INSERT INTO users (name) VALUES ('Deletable') RETURNING user_id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO course_memories "
            "(user_id, course_id, course_ref, name, summary) "
            "VALUES (%s, %s, 'ref', 'Memory Course', 'summary')",
            (user_id, uuid4()),
        )
        conn.execute(
            "INSERT INTO citation_snapshots "
            "(user_id, course_id, source_id, source_name) "
            "VALUES (%s, %s, %s, 'source.txt')",
            (user_id, uuid4(), uuid4()),
        )
        conn.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        remaining = conn.execute(
            "SELECT COUNT(*) FROM course_memories WHERE user_id = %s",
            (user_id,),
        ).fetchone()[0]
        snapshots = conn.execute(
            "SELECT COUNT(*) FROM citation_snapshots WHERE user_id = %s",
            (user_id,),
        ).fetchone()[0]
        conn.rollback()
    assert remaining == 0
    assert snapshots == 0


def test_017_rewrites_legacy_codes_and_check_rejects_old_format() -> None:
    """015-era codes (24 hex chars, look-alikes included) violate the 017
    CHECK — the migration's DO block must rewrite them first. This pins the
    two migrations' load-bearing order: a schema that ran 017 without 015's
    data, or applied 017's CHECK with legacy rows present, fails loudly."""
    import re

    schema_name = f"migration_order_{uuid4().hex}"
    with connection() as conn:
        conn.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
        conn.execute(
            sql.SQL("SET LOCAL search_path TO {}, public").format(
                sql.Identifier(schema_name)
            )
        )
        legacy_code = "0123456789abcdef01234567"
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            text = path.read_text(encoding="utf-8")
            if path.name == "015_course_archives_and_memory_banks.sql":
                text += (
                    f"\nUPDATE courses SET code = '{legacy_code}' "
                    "WHERE code IS NOT NULL;\n"
                )
            conn.execute(text)
        user_id = conn.execute(
            "INSERT INTO users (name) VALUES ('Owner') RETURNING user_id"
        ).fetchone()[0]
        rows = conn.execute("SELECT code FROM courses").fetchall()
        for (code,) in rows:
            assert re.fullmatch(r"[A-HJKMNPQRSTUVWXYZ2-9]{16}", code), code
        assert not any(code == legacy_code for (code,) in rows)
        with pytest.raises(Exception, match="courses_join_code_known"):
            conn.execute(
                "INSERT INTO courses (owner_user_id, code, name, visibility) "
                "VALUES (%s, %s, 'bad', 'private')",
                (user_id, legacy_code),
            )
        conn.rollback()
