-- 010_downgrade_grace.sql
-- A downgraded user keeps excess courses/storage for 60 days; after that the
-- free caps apply and excess may be removed (archive-first per policy).

ALTER TABLE users ADD COLUMN downgrade_grace_deadline TIMESTAMPTZ;

CREATE FUNCTION set_downgrade_grace_deadline()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.ended_at IS NOT NULL AND NEW.tier = 'paid' THEN
        UPDATE users
        SET downgrade_grace_deadline = NEW.ended_at + INTERVAL '60 days'
        WHERE users.user_id = NEW.user_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_subscription_end_grace
AFTER UPDATE OF ended_at ON user_subscriptions
FOR EACH ROW
    WHEN (OLD.ended_at IS NULL AND NEW.ended_at IS NOT NULL)
EXECUTE FUNCTION set_downgrade_grace_deadline();

CREATE FUNCTION clear_downgrade_grace_deadline()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.ended_at IS NULL THEN
        UPDATE users
        SET downgrade_grace_deadline = NULL
        WHERE users.user_id = NEW.user_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_subscription_restart_clears_grace
AFTER INSERT OR UPDATE OF ended_at ON user_subscriptions
FOR EACH ROW
    WHEN (NEW.ended_at IS NULL)
EXECUTE FUNCTION clear_downgrade_grace_deadline();