-- 019_pending_ingestion.sql
-- Copy semantics (plan phase 1.3, recommended strategy): copied sources
-- pass through ingestion again; derived concepts/dependencies are not
-- copied (re-derived by ingestion). This table is the explicit seam that
-- records which sources need ingestion, so a copied course is never falsely
-- considered indexed. Milestone 1's ingestion wiring will claim rows here;
-- until then the rows are inspectable proof that copying queues work.

CREATE TABLE pending_ingestion (
    source_id   UUID PRIMARY KEY REFERENCES sources(source_id) ON DELETE CASCADE,
    course_id   UUID NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    reason      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_pending_ingestion_course ON pending_ingestion(course_id);

CREATE TABLE ingestion_history (
    history_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID NOT NULL,
    course_id   UUID NOT NULL,
    reason      TEXT NOT NULL,
    queued_at   TIMESTAMPTZ NOT NULL,
    cleared_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ingestion_history_course ON ingestion_history(course_id);

-- Backfill: every copied source already in the database was created by
-- _copy_course_contents with origin 'copied_from_archive:*' and status
-- 'uploaded'; record them so no existing copy is silently forgotten.
INSERT INTO pending_ingestion (source_id, course_id, reason)
SELECT source.source_id, source.course_id, 'copied_from_archive:backfill'
FROM sources AS source
JOIN course_objects AS object ON object.object_id = source.object_id
WHERE object.origin LIKE 'copied_from_archive:%';