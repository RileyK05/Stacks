-- 005_course_access_invariants.sql
-- Shared users may create derived materials and private study state, but only
-- while they have active course access. Base source objects remain owner-only.

CREATE FUNCTION user_has_course_access(p_user_id UUID, p_course_id UUID)
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
        FROM course_memberships
        WHERE course_id = p_course_id
          AND user_id = p_user_id
          AND status = 'active'
    );
$$;

CREATE FUNCTION enforce_user_course_access()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    actor_id UUID;
    target_course_id UUID;
BEGIN
    actor_id := (to_jsonb(NEW) ->> TG_ARGV[0])::UUID;
    target_course_id := (to_jsonb(NEW) ->> TG_ARGV[1])::UUID;
    IF NOT user_has_course_access(actor_id, target_course_id) THEN
        RAISE EXCEPTION 'user % has no access to course %', actor_id, target_course_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION enforce_course_object_access()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    course_owner_id UUID;
BEGIN
    SELECT owner_user_id INTO course_owner_id
    FROM courses
    WHERE course_id = NEW.course_id;

    IF NEW.kind = 'source' THEN
        IF NEW.created_by_user_id <> course_owner_id
           OR NEW.access_scope <> 'members' THEN
            RAISE EXCEPTION 'base sources must be owner-created and member-scoped'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NOT user_has_course_access(NEW.created_by_user_id, NEW.course_id) THEN
        RAISE EXCEPTION 'creator % has no access to course %',
            NEW.created_by_user_id, NEW.course_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION enforce_source_object_kind()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM course_objects
        WHERE object_id = NEW.object_id
          AND kind = 'source'
          AND access_scope = 'members'
    ) THEN
        RAISE EXCEPTION 'source detail requires a member-scoped source object'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION enforce_mastery_course_access()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    target_course_id UUID;
BEGIN
    SELECT course_id INTO target_course_id
    FROM concepts
    WHERE concept_id = NEW.concept_id;
    IF NOT user_has_course_access(NEW.user_id, target_course_id) THEN
        RAISE EXCEPTION 'user % has no access to concept course', NEW.user_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_course_objects_access
BEFORE INSERT OR UPDATE OF course_id, created_by_user_id, kind, access_scope
ON course_objects
FOR EACH ROW EXECUTE FUNCTION enforce_course_object_access();

CREATE TRIGGER trg_sources_object_kind
BEFORE INSERT OR UPDATE OF object_id
ON sources
FOR EACH ROW EXECUTE FUNCTION enforce_source_object_kind();

CREATE TRIGGER trg_attempts_course_access
BEFORE INSERT OR UPDATE OF user_id, course_id
ON attempts
FOR EACH ROW EXECUTE FUNCTION enforce_user_course_access('user_id', 'course_id');

CREATE TRIGGER trg_recommendations_course_access
BEFORE INSERT OR UPDATE OF user_id, course_id
ON recommendations
FOR EACH ROW EXECUTE FUNCTION enforce_user_course_access('user_id', 'course_id');

CREATE TRIGGER trg_conversations_course_access
BEFORE INSERT OR UPDATE OF user_id, course_id
ON conversations
FOR EACH ROW EXECUTE FUNCTION enforce_user_course_access('user_id', 'course_id');

CREATE TRIGGER trg_retrieval_traces_course_access
BEFORE INSERT OR UPDATE OF user_id, course_id
ON retrieval_traces
FOR EACH ROW EXECUTE FUNCTION enforce_user_course_access('user_id', 'course_id');

CREATE TRIGGER trg_concept_mastery_course_access
BEFORE INSERT OR UPDATE OF user_id, concept_id
ON concept_mastery
FOR EACH ROW EXECUTE FUNCTION enforce_mastery_course_access();
