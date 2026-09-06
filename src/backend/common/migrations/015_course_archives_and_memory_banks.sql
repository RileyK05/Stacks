-- 015_course_archives_and_memory_banks.sql
-- Random course join codes, consent-based invitations, 90-day archives,
-- permanent per-user memories, and durable physical-storage cleanup jobs.

ALTER TABLE courses
    ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN archived_at TIMESTAMPTZ,
    ADD COLUMN purge_after TIMESTAMPTZ,
    ADD CONSTRAINT courses_lifecycle_known CHECK (
        lifecycle_status IN ('active', 'archived')
    ),
    ADD CONSTRAINT courses_archive_state CHECK (
        (lifecycle_status = 'active' AND archived_at IS NULL AND purge_after IS NULL)
        OR
        (lifecycle_status = 'archived' AND archived_at IS NOT NULL AND purge_after IS NOT NULL)
    );

UPDATE courses
SET code = upper(encode(gen_random_bytes(12), 'hex'));

DROP INDEX idx_courses_owner_code;
CREATE UNIQUE INDEX idx_courses_join_code ON courses(code);
CREATE INDEX idx_courses_archive_purge
    ON courses(purge_after) WHERE lifecycle_status = 'archived';

ALTER TABLE course_enrollments ADD COLUMN responded_at TIMESTAMPTZ;

ALTER TABLE course_enrollments
    DROP CONSTRAINT course_enrollment_revocation_state,
    DROP CONSTRAINT course_enrollment_source_consistency;

ALTER TABLE course_enrollments
    ADD CONSTRAINT course_enrollment_state CHECK (
        (status = 'active' AND revoked_at IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL)
        OR (status = 'invited' AND revoked_at IS NULL AND responded_at IS NULL)
        OR (status = 'declined' AND revoked_at IS NULL AND responded_at IS NOT NULL)
    ),
    ADD CONSTRAINT course_enrollment_source_consistency CHECK (
        (enrollment_source IN ('self_service', 'join_code')
            AND invited_by_user_id IS NULL)
        OR (enrollment_source = 'invitation' AND invited_by_user_id IS NOT NULL)
    );

ALTER TABLE course_memories RENAME COLUMN code TO course_ref;
ALTER TABLE course_memories
    ADD COLUMN token_budget INTEGER NOT NULL DEFAULT 1000
        CHECK (token_budget > 0),
    ADD COLUMN summary_version TEXT NOT NULL DEFAULT 'deterministic-v1';

DELETE FROM course_memories AS older
USING course_memories AS newer
WHERE older.user_id = newer.user_id
  AND older.course_id = newer.course_id
  AND (older.created_at, older.memory_id) < (newer.created_at, newer.memory_id);

CREATE UNIQUE INDEX course_memories_user_course
    ON course_memories(user_id, course_id);

CREATE TABLE course_archive_access (
    course_id       UUID NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at      TIMESTAMPTZ NOT NULL,
    copied_course_id UUID REFERENCES courses(course_id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (course_id, user_id),
    CONSTRAINT archive_expiry_after_creation CHECK (expires_at > created_at)
);

CREATE INDEX idx_course_archive_access_user
    ON course_archive_access(user_id, expires_at DESC);

CREATE TABLE storage_cleanup_jobs (
    job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id       UUID NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    attempt_count   INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    error_message   TEXT,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX storage_cleanup_one_open_job
    ON storage_cleanup_jobs(course_id)
    WHERE status IN ('pending', 'running', 'failed');
CREATE INDEX storage_cleanup_ready
    ON storage_cleanup_jobs(next_attempt_at, created_at)
    WHERE status IN ('pending', 'failed');

CREATE OR REPLACE FUNCTION user_has_course_use_access(
    p_user_id UUID,
    p_course_id UUID
)
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM courses
        WHERE course_id = p_course_id
          AND owner_user_id = p_user_id
          AND lifecycle_status = 'active'
    ) OR EXISTS (
        SELECT 1
        FROM course_enrollments AS enrollment
        JOIN courses AS course ON course.course_id = enrollment.course_id
        WHERE enrollment.course_id = p_course_id
          AND enrollment.user_id = p_user_id
          AND enrollment.status = 'active'
          AND course.lifecycle_status = 'active'
    );
$$;

CREATE OR REPLACE FUNCTION enforce_course_enrollment()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    course_owner_id UUID;
    target_visibility course_visibility;
    target_lifecycle TEXT;
BEGIN
    SELECT owner_user_id, visibility, lifecycle_status
    INTO course_owner_id, target_visibility, target_lifecycle
    FROM courses
    WHERE course_id = NEW.course_id;

    IF target_lifecycle <> 'active' THEN
        RAISE EXCEPTION 'cannot enroll in an archived course'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.user_id = course_owner_id THEN
        RAISE EXCEPTION 'course owner does not enroll in their own course'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.enrollment_source = 'invitation' THEN
        IF NEW.invited_by_user_id <> course_owner_id THEN
            RAISE EXCEPTION 'only the course owner can invite a learner'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'active' AND NEW.enrollment_source = 'self_service' THEN
        IF target_visibility <> 'public' THEN
            RAISE EXCEPTION 'self-service enrollment requires a public course'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'active' AND NEW.enrollment_source = 'join_code' THEN
        IF target_visibility NOT IN ('public', 'invite_only') THEN
            RAISE EXCEPTION 'join-code enrollment requires a joinable course'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
