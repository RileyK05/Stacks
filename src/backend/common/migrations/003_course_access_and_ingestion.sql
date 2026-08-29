-- 003_course_access_and_ingestion.sql
-- Adds owner-controlled course sharing, links sources to their generic course
-- objects, records staged ingestion, and hardens auth/account boundaries.

CREATE TYPE course_visibility AS ENUM ('private', 'public');
CREATE TYPE course_member_role AS ENUM ('learner');
CREATE TYPE membership_status AS ENUM ('active', 'revoked');
CREATE TYPE object_access_scope AS ENUM ('course', 'members', 'creator');
CREATE TYPE ingestion_status AS ENUM ('pending', 'running', 'succeeded', 'failed');

ALTER TABLE courses RENAME COLUMN user_id TO owner_user_id;
ALTER TABLE course_objects RENAME COLUMN user_id TO created_by_user_id;
ALTER TABLE sources RENAME COLUMN user_id TO uploaded_by_user_id;

ALTER INDEX IF EXISTS idx_courses_user RENAME TO idx_courses_owner;

ALTER TABLE courses
    ADD COLUMN visibility course_visibility NOT NULL DEFAULT 'private';

ALTER TABLE course_objects
    ADD COLUMN access_scope object_access_scope NOT NULL DEFAULT 'creator';

CREATE TABLE course_memberships (
    membership_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id     UUID NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role          course_member_role NOT NULL DEFAULT 'learner',
    status        membership_status NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at    TIMESTAMPTZ,
    CONSTRAINT course_membership_unique UNIQUE (course_id, user_id),
    CONSTRAINT course_membership_revocation_state CHECK (
        (status = 'active' AND revoked_at IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL)
    )
);

ALTER TABLE sources ADD COLUMN object_id UUID;
UPDATE sources SET object_id = gen_random_uuid();

INSERT INTO course_objects (
    object_id,
    course_id,
    created_by_user_id,
    kind,
    content_type,
    content_uri,
    content,
    status,
    access_scope,
    created_at
)
SELECT
    object_id,
    course_id,
    uploaded_by_user_id,
    'source',
    mime_type,
    uri,
    CASE
        WHEN uri IS NULL THEN jsonb_build_object('source_id', source_id::text)
        ELSE NULL
    END,
    status::text,
    'members',
    created_at
FROM sources;

ALTER TABLE sources
    ALTER COLUMN object_id SET NOT NULL,
    ADD CONSTRAINT sources_object_unique UNIQUE (object_id),
    ADD CONSTRAINT sources_object_fk
        FOREIGN KEY (object_id)
        REFERENCES course_objects(object_id)
        ON DELETE CASCADE;

CREATE TABLE ingestion_runs (
    run_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id        UUID NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    pipeline_version TEXT NOT NULL,
    status           ingestion_status NOT NULL DEFAULT 'pending',
    configuration    JSONB NOT NULL DEFAULT '{}',
    error_message    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ
);

CREATE TABLE ingestion_stage_runs (
    stage_run_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id             UUID NOT NULL REFERENCES ingestion_runs(run_id) ON DELETE CASCADE,
    stage              TEXT NOT NULL,
    position           INTEGER NOT NULL CHECK (position >= 0),
    depends_on_stage_id UUID REFERENCES ingestion_stage_runs(stage_run_id),
    status              ingestion_status NOT NULL DEFAULT 'pending',
    attempt_count       INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts        INTEGER NOT NULL DEFAULT 2 CHECK (max_attempts >= 1),
    handler_version     TEXT NOT NULL,
    configuration       JSONB NOT NULL DEFAULT '{}',
    error_message       TEXT,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    CONSTRAINT ingestion_stage_unique UNIQUE (run_id, stage),
    CONSTRAINT ingestion_stage_position_unique UNIQUE (run_id, position),
    CONSTRAINT ingestion_attempt_limit CHECK (attempt_count <= max_attempts)
);

ALTER TABLE citation_snapshots
    ADD COLUMN source_hash TEXT,
    ADD COLUMN archive_reason TEXT NOT NULL DEFAULT 'source_deleted';

UPDATE users SET email = lower(trim(email)) WHERE email IS NOT NULL;
DROP INDEX idx_users_email;
CREATE UNIQUE INDEX idx_users_email ON users(lower(email)) WHERE email IS NOT NULL;

CREATE INDEX idx_course_memberships_user
    ON course_memberships(user_id) WHERE status = 'active';
CREATE INDEX idx_course_objects_creator ON course_objects(created_by_user_id);
CREATE INDEX idx_sources_object ON sources(object_id);
CREATE INDEX idx_ingestion_runs_source ON ingestion_runs(source_id);
CREATE INDEX idx_ingestion_stage_runs_run ON ingestion_stage_runs(run_id, position);
