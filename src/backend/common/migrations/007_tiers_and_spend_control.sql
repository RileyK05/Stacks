-- 007_tiers_and_spend_control.sql
-- Customer tiers with weekly generation budgets, tier-routed model access,
-- and an append-only generation ledger for spend inspection.

CREATE TYPE user_tier AS ENUM ('free', 'paid');

ALTER TABLE users ADD COLUMN tier user_tier NOT NULL DEFAULT 'free';

CREATE TABLE user_subscriptions (
    subscription_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tier            user_tier NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    CONSTRAINT user_subscription_period CHECK (
        ended_at IS NULL OR ended_at >= started_at
    )
);

CREATE UNIQUE INDEX user_subscription_one_active
    ON user_subscriptions(user_id) WHERE ended_at IS NULL;

CREATE FUNCTION sync_user_tier()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    subscription_user_id UUID;
BEGIN
    IF TG_OP = 'DELETE' THEN
        subscription_user_id := OLD.user_id;
    ELSE
        subscription_user_id := NEW.user_id;
    END IF;
    UPDATE users
    SET tier = COALESCE((
        SELECT subscription.tier
        FROM user_subscriptions AS subscription
        WHERE subscription.user_id = subscription_user_id
          AND subscription.ended_at IS NULL
        ORDER BY subscription.started_at DESC
        LIMIT 1
    ), 'free')
    WHERE users.user_id = subscription_user_id;
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER trg_user_subscriptions_sync_tier
AFTER INSERT OR UPDATE OR DELETE ON user_subscriptions
FOR EACH ROW EXECUTE FUNCTION sync_user_tier();

CREATE TABLE generation_ledger (
    ledger_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    course_id     UUID REFERENCES courses(course_id) ON DELETE SET NULL,
    task          TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_generation_ledger_user_time
    ON generation_ledger(user_id, created_at DESC);