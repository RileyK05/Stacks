-- 002_auth_and_distilled_records.sql
-- Adds:
--   * auth + account-lifecycle columns on users (email, password hash, soft-delete)
--   * course_memories: distilled record that survives course deletion
--   * citation_snapshots: compressed evidence record written before source removal

ALTER TABLE users
    ADD COLUMN email TEXT,
    ADD COLUMN password_hash TEXT,
    ADD COLUMN delete_requested_at TIMESTAMPTZ;

CREATE UNIQUE INDEX idx_users_email ON users(email) WHERE email IS NOT NULL;

-- Distilled memory of a course that survives the course row being deleted.
-- course_id is stored without a hard FK so the memory outlives the course.
CREATE TABLE course_memories (
    memory_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(user_id),
    course_id    UUID NOT NULL,
    code         TEXT NOT NULL,
    name         TEXT NOT NULL,
    summary      TEXT NOT NULL,
    key_concepts JSONB NOT NULL DEFAULT '[]',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Compressed record of citations + why each was valid, written before a
-- source's citations are removed. Survives the source row being deleted.
CREATE TABLE citation_snapshots (
    snapshot_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(user_id),
    course_id    UUID NOT NULL,
    source_id    UUID NOT NULL,
    source_name  TEXT NOT NULL,
    citations    JSONB NOT NULL DEFAULT '[]',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
