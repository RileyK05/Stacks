-- 018_copy_any_time.sql
-- Copy-any-time policy: an archive participant may copy their archive as many
-- times as they like during the grace period. The copy-once bookkeeping column
-- is dropped; nothing survives purge (migration adds course_memories to the
-- purge block's coverage via course_deletion.sql, enforced by tests).

ALTER TABLE course_archive_access DROP COLUMN copied_course_id;