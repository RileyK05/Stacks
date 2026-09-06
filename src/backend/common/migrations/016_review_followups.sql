-- 016_review_followups.sql
-- Account hard-delete must not landmine on user-owned distilled records:
-- memory banks and citation snapshots now cascade with the account, because
-- account deletion already owns the evidence-retention ceremony at its layer.
-- Memory-bank refresh history becomes inspectable via updated_at. Cleanup
-- jobs gain a terminal 'dead' status so wedged jobs stop retrying forever.

ALTER TABLE course_memories
    DROP CONSTRAINT course_memories_user_id_fkey,
    ADD CONSTRAINT course_memories_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;

ALTER TABLE citation_snapshots
    DROP CONSTRAINT citation_snapshots_user_id_fkey,
    ADD CONSTRAINT citation_snapshots_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;

ALTER TABLE course_memories
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD CONSTRAINT memories_updated_after_created
        CHECK (updated_at >= created_at);

ALTER TABLE storage_cleanup_jobs
    DROP CONSTRAINT storage_cleanup_jobs_status_check,
    ADD CONSTRAINT storage_cleanup_jobs_status_check
        CHECK (status IN ('pending', 'running', 'failed', 'succeeded', 'dead'));