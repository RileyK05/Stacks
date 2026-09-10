-- 021_email_verification_and_password_reset.sql
-- Email verification + password reset. Tokens are stored as SHA-256 hashes
-- (a DB leak reveals nothing usable, same principle as premium claim
-- codes) and are single-use with an expiry. Outbound emails land in
-- email_outbox — an operator/worker seam, not a delivery service; a future
-- SMTP worker drains it. Verification gates new resource creation
-- (courses/uploads), not login, so existing accounts are never locked out.

ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMPTZ;

CREATE TABLE email_outbox (
    message_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID REFERENCES users(user_id) ON DELETE CASCADE,
    to_email     TEXT NOT NULL,
    kind         TEXT NOT NULL,
    subject      TEXT NOT NULL,
    body         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_email_outbox_created ON email_outbox(created_at);

CREATE TABLE email_tokens (
    token_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('email_verification', 'password_reset')),
    token_hash   TEXT NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    expires_at   TIMESTAMPTZ NOT NULL,
    used_at      TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX email_tokens_one_open_per_kind
    ON email_tokens(user_id, kind)
    WHERE used_at IS NULL;
CREATE INDEX idx_email_tokens_hash ON email_tokens(token_hash);