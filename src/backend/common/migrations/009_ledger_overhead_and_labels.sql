-- 009_ledger_overhead_and_labels.sql
-- Free-tier spend overhead + course label snapshots that survive course deletion.

ALTER TABLE generation_ledger
    ADD COLUMN overhead_tokens INTEGER NOT NULL DEFAULT 0
        CONSTRAINT generation_ledger_overhead_non_negative CHECK (overhead_tokens >= 0);

ALTER TABLE generation_ledger ADD COLUMN course_label TEXT;

UPDATE generation_ledger AS ledger
SET course_label = course.code || ' — ' || course.name
FROM courses AS course
WHERE ledger.course_id = course.course_id;