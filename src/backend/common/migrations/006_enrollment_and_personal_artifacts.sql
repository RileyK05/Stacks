-- 006_enrollment_and_personal_artifacts.sql
-- Separates public discovery, learner enrollment, canonical course content,
-- private learner artifacts, and tutor presentation preferences.

ALTER TYPE course_member_role RENAME TO course_enrollment_role;
ALTER TYPE membership_status RENAME TO enrollment_status;
ALTER TYPE object_access_scope RENAME VALUE 'course' TO 'published';
ALTER TYPE object_access_scope RENAME VALUE 'members' TO 'enrolled';
ALTER TYPE object_access_scope RENAME VALUE 'creator' TO 'private';

ALTER TABLE course_memberships RENAME TO course_enrollments;
ALTER TABLE course_enrollments RENAME COLUMN membership_id TO enrollment_id;
ALTER TABLE course_enrollments
    RENAME CONSTRAINT course_membership_unique TO course_enrollment_unique;
ALTER TABLE course_enrollments
    RENAME CONSTRAINT course_membership_revocation_state
    TO course_enrollment_revocation_state;
ALTER INDEX idx_course_memberships_user RENAME TO idx_course_enrollments_user;

CREATE TYPE enrollment_source AS ENUM ('self_service', 'invitation');

ALTER TABLE course_enrollments
    ADD COLUMN enrollment_source enrollment_source,
    ADD COLUMN invited_by_user_id UUID REFERENCES users(user_id);

UPDATE course_enrollments AS enrollment
SET enrollment_source = 'invitation',
    invited_by_user_id = course.owner_user_id
FROM courses AS course
WHERE course.course_id = enrollment.course_id;

ALTER TABLE course_enrollments
    ALTER COLUMN enrollment_source SET NOT NULL,
    ADD CONSTRAINT course_enrollment_source_consistency CHECK (
        (enrollment_source = 'self_service' AND invited_by_user_id IS NULL)
        OR (enrollment_source = 'invitation' AND invited_by_user_id IS NOT NULL)
    );

CREATE TYPE tutor_verbosity AS ENUM ('concise', 'balanced', 'detailed');
CREATE TYPE analogy_usage AS ENUM ('rare', 'when_helpful', 'frequent');
CREATE TYPE response_structure AS ENUM ('prose', 'mixed', 'bullets');
CREATE TYPE source_presentation AS ENUM (
    'paraphrase_first', 'balanced', 'quote_forward'
);

CREATE TABLE user_artifacts (
    artifact_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(user_id),
    source_course_id    UUID REFERENCES courses(course_id) ON DELETE SET NULL,
    source_course_label TEXT NOT NULL,
    kind                TEXT NOT NULL,
    content_type        TEXT NOT NULL,
    content_uri         TEXT,
    content             JSONB,
    status              TEXT NOT NULL DEFAULT 'draft',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT user_artifact_content_or_uri CHECK (
        content_uri IS NOT NULL OR content IS NOT NULL
    )
);

CREATE TABLE user_artifact_origins (
    artifact_id          UUID PRIMARY KEY
        REFERENCES user_artifacts(artifact_id) ON DELETE CASCADE,
    source_ids           JSONB NOT NULL DEFAULT '[]',
    concept_ids          JSONB NOT NULL DEFAULT '[]',
    model                TEXT,
    prompt_version       TEXT,
    tutor_profile_version TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO user_artifacts (
    artifact_id,
    user_id,
    source_course_id,
    source_course_label,
    kind,
    content_type,
    content_uri,
    content,
    status,
    created_at
)
SELECT
    object.object_id,
    object.created_by_user_id,
    object.course_id,
    concat_ws(' — ', NULLIF(course.code, ''), course.name),
    object.kind,
    object.content_type,
    object.content_uri,
    object.content,
    object.status,
    object.created_at
FROM course_objects AS object
JOIN courses AS course ON course.course_id = object.course_id
WHERE object.created_by_user_id <> course.owner_user_id;

INSERT INTO user_artifact_origins (
    artifact_id,
    source_ids,
    concept_ids,
    model,
    prompt_version,
    created_at
)
SELECT
    origin.artifact_id,
    origin.source_ids,
    origin.concept_ids,
    origin.model,
    origin.prompt_version,
    origin.created_at
FROM artifact_origins AS origin
JOIN user_artifacts AS artifact ON artifact.artifact_id = origin.artifact_id;

DELETE FROM artifact_origins
WHERE artifact_id IN (SELECT artifact_id FROM user_artifacts);

DELETE FROM course_objects
WHERE object_id IN (SELECT artifact_id FROM user_artifacts);

CREATE TABLE tutor_profiles (
    profile_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL UNIQUE REFERENCES users(user_id),
    profile_version      TEXT NOT NULL,
    verbosity            tutor_verbosity NOT NULL DEFAULT 'balanced',
    analogy_usage        analogy_usage NOT NULL DEFAULT 'when_helpful',
    response_structure   response_structure NOT NULL DEFAULT 'mixed',
    source_presentation  source_presentation NOT NULL DEFAULT 'balanced',
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER FUNCTION user_has_course_access(UUID, UUID)
    RENAME TO user_has_course_use_access;
ALTER FUNCTION enforce_user_course_access()
    RENAME TO enforce_user_course_use_access;

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
    ) OR EXISTS (
        SELECT 1
        FROM course_enrollments
        WHERE course_id = p_course_id
          AND user_id = p_user_id
          AND status = 'active'
    );
$$;

CREATE OR REPLACE FUNCTION enforce_user_course_use_access()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    actor_id UUID;
    target_course_id UUID;
BEGIN
    actor_id := (to_jsonb(NEW) ->> TG_ARGV[0])::UUID;
    target_course_id := (to_jsonb(NEW) ->> TG_ARGV[1])::UUID;
    IF NOT user_has_course_use_access(actor_id, target_course_id) THEN
        RAISE EXCEPTION 'user % cannot use course %', actor_id, target_course_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_course_object_access()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    course_owner_id UUID;
BEGIN
    SELECT owner_user_id INTO course_owner_id
    FROM courses
    WHERE course_id = NEW.course_id;

    IF NEW.created_by_user_id <> course_owner_id THEN
        RAISE EXCEPTION 'canonical course objects must be owner-created'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.kind = 'source' AND NEW.access_scope <> 'enrolled' THEN
        RAISE EXCEPTION 'base sources must be enrollment-scoped'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_source_object_kind()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM course_objects
        WHERE object_id = NEW.object_id
          AND kind = 'source'
          AND access_scope = 'enrolled'
    ) THEN
        RAISE EXCEPTION 'source detail requires an enrollment-scoped source object'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_mastery_course_access()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    target_course_id UUID;
BEGIN
    SELECT course_id INTO target_course_id
    FROM concepts
    WHERE concept_id = NEW.concept_id;
    IF NOT user_has_course_use_access(NEW.user_id, target_course_id) THEN
        RAISE EXCEPTION 'user % cannot use concept course', NEW.user_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION enforce_course_enrollment()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    course_owner_id UUID;
    target_visibility course_visibility;
BEGIN
    SELECT owner_user_id, visibility
    INTO course_owner_id, target_visibility
    FROM courses
    WHERE course_id = NEW.course_id;

    IF NEW.user_id = course_owner_id THEN
        RAISE EXCEPTION 'course owner does not enroll in their own course'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.enrollment_source = 'self_service' THEN
        IF target_visibility <> 'public' OR NEW.invited_by_user_id IS NOT NULL THEN
            RAISE EXCEPTION 'self-service enrollment requires a public course'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.invited_by_user_id <> course_owner_id THEN
        RAISE EXCEPTION 'only the course owner can invite a learner'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION enforce_user_artifact_access()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.source_course_id IS NULL THEN
        IF TG_OP = 'INSERT' THEN
            RAISE EXCEPTION 'new user artifact requires a source course'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NOT user_has_course_use_access(NEW.user_id, NEW.source_course_id) THEN
        RAISE EXCEPTION 'user % cannot generate from course %',
            NEW.user_id, NEW.source_course_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_course_enrollments_policy
BEFORE INSERT OR UPDATE OF course_id, user_id, enrollment_source, invited_by_user_id
ON course_enrollments
FOR EACH ROW EXECUTE FUNCTION enforce_course_enrollment();

CREATE TRIGGER trg_user_artifacts_access
BEFORE INSERT OR UPDATE OF user_id, source_course_id
ON user_artifacts
FOR EACH ROW EXECUTE FUNCTION enforce_user_artifact_access();

CREATE INDEX idx_user_artifacts_user ON user_artifacts(user_id, created_at DESC);
CREATE INDEX idx_user_artifacts_source_course ON user_artifacts(source_course_id);
