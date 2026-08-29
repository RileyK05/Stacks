-- 012_premium_claim_codes.sql
-- Operator-issued claim codes. Every account is issued a personal code at
-- registration (non-premium); the operator flags codes as premium-granting.
-- A signed-in user claiming a valid premium code starts a paid subscription
-- through the standard subscription machinery.

CREATE TABLE premium_codes (
    code_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_hash          TEXT NOT NULL UNIQUE,
    issued_for_user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    grants_premium     BOOLEAN NOT NULL DEFAULT FALSE,
    claimed_by_user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    claimed_at         TIMESTAMPTZ,
    revoked_at         TIMESTAMPTZ,
    note               TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT premium_code_claim_state CHECK (
        (claimed_by_user_id IS NULL AND claimed_at IS NULL)
        OR (claimed_by_user_id IS NOT NULL AND claimed_at IS NOT NULL)
    )
);

CREATE FUNCTION release_dangling_premium_claim()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.claimed_by_user_id IS NULL AND NEW.claimed_at IS NOT NULL THEN
        NEW.claimed_at = NULL;
        NEW.grants_premium = FALSE;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_premium_codes_release_claim
BEFORE UPDATE OF claimed_by_user_id ON premium_codes
FOR EACH ROW
    WHEN (OLD.claimed_by_user_id IS NOT NULL AND NEW.claimed_by_user_id IS NULL)
EXECUTE FUNCTION release_dangling_premium_claim();