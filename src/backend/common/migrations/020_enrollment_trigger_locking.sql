-- 020_enrollment_trigger_locking.sql
-- Close the accept-vs-archival race: the enrollment policy trigger read the
-- courses row with a plain SELECT, so a concurrent archival could commit
-- between the trigger's read and the enrollment's commit — leaving an
-- 'active' enrollment on an archived course, granted after participants
-- were snapshotted (the learner never received their archive access).
-- FOR SHARE blocks delete_course's FOR UPDATE on the same row until the
-- enrollment transaction commits, making the check and the transition
-- atomic with respect to archival.

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
    WHERE course_id = NEW.course_id
    FOR SHARE;

    IF NOT FOUND THEN
        RETURN NEW;
    END IF;
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