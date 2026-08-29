-- 011_enrollment_reactivation.sql
-- Allow a revoked learner to be re-enrolled through the validated path, and
-- close the trigger-bypass where a status-only UPDATE skipped policy checks.

CREATE OR REPLACE FUNCTION enforce_course_enrollment()
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
    IF NEW.status = 'active' THEN
        IF NEW.enrollment_source = 'self_service' THEN
            IF target_visibility <> 'public' OR NEW.invited_by_user_id IS NOT NULL
            THEN
                RAISE EXCEPTION 'self-service enrollment requires a public course'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.invited_by_user_id <> course_owner_id THEN
            RAISE EXCEPTION 'only the course owner can invite a learner'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER trg_course_enrollments_policy ON course_enrollments;

CREATE TRIGGER trg_course_enrollments_policy
BEFORE INSERT OR UPDATE
ON course_enrollments
FOR EACH ROW EXECUTE FUNCTION enforce_course_enrollment();