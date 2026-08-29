from datetime import UTC, datetime
from uuid import uuid4

import pytest
from src.backend.common import auth, courses_repo, spend_repo, users_repo
from src.backend.common.budget import (
    BudgetExceededError,
    CourseLimitExceededError,
    StorageLimitExceededError,
    TierMismatchError,
    check_budget,
    check_course_limit,
    check_course_storage,
    check_total_storage,
    free_tier_overhead,
    verify_tier,
)
from src.backend.common.db import connection
from src.backend.common.schemas import CourseVisibility, UserTier
from src.backend.common.schemas.identity import User
from src.backend.common.tiers import TierPolicy, load_tier_policies


def _user() -> User:
    return users_repo.create(
        "Spend Tester",
        f"{uuid4().hex}@test.invalid",
        auth.hash_password("long-password"),
    )


@pytest.fixture
def user() -> User:
    return _user()


def test_tier_policies_load_and_route_models() -> None:
    policies = load_tier_policies()
    free = policies.policy_for(UserTier.FREE)
    paid = policies.policy_for(UserTier.PAID)
    assert free.weekly_token_budget < paid.weekly_token_budget
    assert free.model_for("tutor_answer") != paid.model_for("tutor_answer")
    assert free.model_for("toc_update") == paid.model_for("toc_update")


def test_tier_policy_requires_all_model_roles() -> None:
    with pytest.raises(ValueError, match="must cover exactly the known"):
        TierPolicy(
            tier=UserTier.FREE,
            weekly_token_budget=100,
            max_owned_courses=2,
            max_course_storage_bytes=1048576,
            max_total_storage_bytes=1048576,
            free_tier_overhead_percent=5,
            models={},
        )


def test_subscription_lifecycle_syncs_tier() -> None:
    account = _user()
    assert account.tier == UserTier.FREE
    spend_repo.start_subscription(account.user_id, UserTier.PAID)
    fetched = users_repo.get_by_id(account.user_id)
    assert fetched is not None
    assert fetched.tier == UserTier.PAID
    ended = spend_repo.end_active_subscription(account.user_id)
    assert ended is not None
    fetched = users_repo.get_by_id(account.user_id)
    assert fetched is not None
    assert fetched.tier == UserTier.FREE


def test_week_start_is_monday_midnight_utc() -> None:
    assert spend_repo.week_start(datetime(2026, 8, 28, 15, 30, tzinfo=UTC)) == datetime(
        2026, 8, 24, 0, 0, tzinfo=UTC
    )
    assert spend_repo.week_start(datetime(2026, 8, 24, 0, 0, tzinfo=UTC)) == datetime(
        2026, 8, 24, 0, 0, tzinfo=UTC
    )


def test_weekly_spend_sums_ledger_entries() -> None:
    account = _user()
    spend_repo.record_generation(
        account.user_id, "tutor_answer", "test-model", 500, 500
    )
    assert spend_repo.weekly_spend(account.user_id) == 1000
    spend_repo.record_generation(
        account.user_id, "toc_update", "test-model", 250, 250
    )
    assert spend_repo.weekly_spend(account.user_id) == 1500


def test_ledger_records_and_lists() -> None:
    account = _user()
    entry = spend_repo.record_generation(
        account.user_id, "tutor_answer", "deepseek-v4-flash", 100, 200
    )
    assert entry.input_tokens == 100
    assert entry.output_tokens == 200
    page = spend_repo.ledger_page(account.user_id)
    assert [item.ledger_id for item in page] == [entry.ledger_id]


def test_ledger_rejects_unknown_task_and_negative_tokens() -> None:
    account = _user()
    with pytest.raises(ValueError, match="unknown generation task"):
        spend_repo.record_generation(
            account.user_id, "definitely_not_a_task", "test-model", 1, 1
        )
    with pytest.raises(ValueError, match="negative"):
        spend_repo.record_generation(
            account.user_id, "tutor_answer", "test-model", -5, 0
        )


def test_check_budget_under_limit_passes() -> None:
    account = _user()
    policies = load_tier_policies()
    state = check_budget(
        account.user_id, UserTier.FREE, policies.policy_for(UserTier.FREE)
    )
    assert state.remaining == state.budget
    assert state.spent == 0


def test_check_budget_over_limit_raises() -> None:
    account = _user()
    policies = load_tier_policies()
    free = policies.policy_for(UserTier.FREE)
    with pytest.raises(BudgetExceededError):
        check_budget(
            account.user_id, UserTier.FREE, free, spent=free.weekly_token_budget + 1
        )


def _create_course(owner_id: object, name: str) -> object:
    with connection() as conn:
        course_id = conn.execute(
            "INSERT INTO courses (owner_user_id, code, name) "
            "VALUES (%s, %s, %s) RETURNING course_id",
            (owner_id, f"TEST-{name}", name),
        ).fetchone()[0]
        conn.commit()
    return course_id


def test_course_limit_blocks_at_tier_cap() -> None:
    account = _user()
    policies = load_tier_policies()
    free = policies.policy_for(UserTier.FREE)
    assert free.max_owned_courses >= 1
    for index in range(free.max_owned_courses):
        check_course_limit(account.user_id, UserTier.FREE, free)
        _create_course(account.user_id, f"Course {index}")
    with pytest.raises(CourseLimitExceededError):
        check_course_limit(account.user_id, UserTier.FREE, free)


def _insert_source_with_size(
    course_id: object, owner_id: object, size_bytes: int
) -> None:
    with connection() as conn:
        object_id = conn.execute(
            "INSERT INTO course_objects "
            "(course_id, created_by_user_id, kind, content_type, content, "
            "access_scope) VALUES (%s, %s, 'source', 'text/plain', '{}', "
            "'enrolled') RETURNING object_id",
            (course_id, owner_id),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO sources "
            "(object_id, uploaded_by_user_id, course_id, filename, mime_type, "
            "source_type, size_bytes) "
            "VALUES (%s, %s, %s, 'file.txt', 'text/plain', 'notes', %s)",
            (object_id, owner_id, course_id, size_bytes),
        )
        conn.commit()


def test_check_course_storage_projects_and_blocks() -> None:
    account = _user()
    policies = load_tier_policies()
    free = policies.policy_for(UserTier.FREE)
    course = courses_repo.create_course(account.user_id, "STOR", "Storage Test")
    course_id = course.course_id
    check_course_limit(account.user_id, UserTier.FREE, free)
    _insert_source_with_size(course_id, account.user_id, 600)
    projected = check_course_storage(
        course_id, UserTier.FREE, free, incoming_bytes=400
    )
    assert projected == 1000
    with pytest.raises(StorageLimitExceededError):
        check_course_storage(
            course_id, UserTier.FREE, free, incoming_bytes=free.max_course_storage_bytes
        )


def test_check_course_storage_rejects_negative() -> None:
    account = _user()
    policies = load_tier_policies()
    free = policies.policy_for(UserTier.FREE)
    course = courses_repo.create_course(account.user_id, "STORN", "Storage Neg")
    course_id = course.course_id
    with pytest.raises(ValueError, match="negative"):
        check_course_storage(course_id, UserTier.FREE, free, incoming_bytes=-1)


def test_total_storage_spans_all_owned_courses() -> None:
    account = _user()
    policies = load_tier_policies()
    free = policies.policy_for(UserTier.FREE)
    course_a = courses_repo.create_course(account.user_id, "AGGA", "Course A")
    course_b = courses_repo.create_course(account.user_id, "AGGB", "Course B")
    _insert_source_with_size(course_a.course_id, account.user_id, 300)
    _insert_source_with_size(course_b.course_id, account.user_id, 300)
    projected = check_total_storage(
        account.user_id, UserTier.FREE, free, incoming_bytes=400
    )
    assert projected == 1000
    with pytest.raises(StorageLimitExceededError):
        check_total_storage(
            account.user_id,
            UserTier.FREE,
            free,
            incoming_bytes=free.max_total_storage_bytes,
        )


def test_free_tier_overhead_applied_on_record_not_on_gate() -> None:
    policies = load_tier_policies()
    free = policies.policy_for(UserTier.FREE)
    paid = policies.policy_for(UserTier.PAID)
    assert free.free_tier_overhead_percent > 0
    assert paid.free_tier_overhead_percent == 0
    assert free_tier_overhead(free, 1000) == 50
    assert free_tier_overhead(paid, 1000) == 0
    assert free_tier_overhead(free, 0) == 0


def test_overhead_counts_toward_weekly_spend() -> None:
    account = _user()
    spend_repo.record_generation(
        account.user_id, "tutor_answer", "test-model", 500, 500, overhead_tokens=100
    )
    assert spend_repo.weekly_spend(account.user_id) == 1100


def test_ledger_keeps_course_label() -> None:
    account = _user()
    entry = spend_repo.record_generation(
        account.user_id,
        "tutor_answer",
        "test-model",
        10,
        10,
        course_label="MATH101 — Calculus",
    )
    assert entry.course_label == "MATH101 — Calculus"


def test_verify_tier_rejects_mismatch() -> None:
    account = _user()
    verify_tier(account.user_id, UserTier.FREE)
    with pytest.raises(TierMismatchError):
        verify_tier(account.user_id, UserTier.PAID)
    spend_repo.start_subscription(account.user_id, UserTier.PAID)
    verify_tier(account.user_id, UserTier.PAID)
    with pytest.raises(TierMismatchError):
        verify_tier(account.user_id, UserTier.FREE)


def test_downgrade_grace_sets_and_clears_deadline() -> None:
    account = _user()
    spend_repo.start_subscription(account.user_id, UserTier.PAID)
    with connection() as conn:
        deadline = conn.execute(
            "SELECT downgrade_grace_deadline FROM users WHERE user_id = %s",
            (account.user_id,),
        ).fetchone()[0]
        assert deadline is None
    spend_repo.end_active_subscription(account.user_id)
    with connection() as conn:
        deadline = conn.execute(
            "SELECT downgrade_grace_deadline FROM users WHERE user_id = %s",
            (account.user_id,),
        ).fetchone()[0]
        assert deadline is not None
    spend_repo.start_subscription(account.user_id, UserTier.PAID)
    with connection() as conn:
        deadline = conn.execute(
            "SELECT downgrade_grace_deadline FROM users WHERE user_id = %s",
            (account.user_id,),
        ).fetchone()[0]
        assert deadline is None


def test_revoked_enrollment_can_be_revalidated() -> None:
    account = _user()
    owner = _user()
    course = courses_repo.create_course(
        owner.user_id, "REAC", "Reactivation", CourseVisibility.PUBLIC
    )
    with connection() as conn:
        conn.execute(
            "INSERT INTO course_enrollments "
            "(course_id, user_id, enrollment_source, status, revoked_at) "
            "VALUES (%s, %s, 'self_service', 'revoked', now())",
            (course.course_id, account.user_id),
        )
        conn.execute(
            "UPDATE courses SET visibility = 'private' WHERE course_id = %s",
            (course.course_id,),
        )
        conn.commit()
        with pytest.raises(Exception, match="requires a public course"):
            conn.execute("SAVEPOINT blocked_reactivation")
            try:
                conn.execute(
                    "UPDATE course_enrollments "
                    "SET status = 'active', revoked_at = NULL "
                    "WHERE course_id = %s AND user_id = %s",
                    (course.course_id, account.user_id),
                )
            finally:
                conn.execute("ROLLBACK TO SAVEPOINT blocked_reactivation")
        conn.execute(
            "UPDATE courses SET visibility = 'public' WHERE course_id = %s",
            (course.course_id,),
        )
        conn.execute(
            "UPDATE course_enrollments SET status = 'active', revoked_at = NULL "
            "WHERE course_id = %s AND user_id = %s",
            (course.course_id, account.user_id),
        )
        conn.commit()
        status = conn.execute(
            "SELECT status FROM course_enrollments "
            "WHERE course_id = %s AND user_id = %s",
            (course.course_id, account.user_id),
        ).fetchone()[0]
        assert status == "active"
        conn.rollback()