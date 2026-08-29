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