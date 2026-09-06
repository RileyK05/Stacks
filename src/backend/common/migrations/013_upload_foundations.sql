-- 013_storage_foundations.sql
-- Per-owner unique course codes and recorded storage encoding for uploads.

CREATE UNIQUE INDEX idx_courses_owner_code
    ON courses(owner_user_id, code);

ALTER TABLE sources ADD COLUMN stored_encoding TEXT;

ALTER TABLE sources
    ADD CONSTRAINT sources_stored_encoding_known CHECK (
        stored_encoding IS NULL OR stored_encoding IN ('identity', 'gzip')
    );