-- 008_source_size_tracking.sql
-- Record uploaded file sizes so per-course storage caps can be enforced.

ALTER TABLE sources ADD COLUMN size_bytes BIGINT;

ALTER TABLE sources
    ADD CONSTRAINT sources_size_non_negative CHECK (size_bytes IS NULL OR size_bytes >= 0);

CREATE INDEX idx_sources_course_size ON sources(course_id) WHERE size_bytes IS NOT NULL;