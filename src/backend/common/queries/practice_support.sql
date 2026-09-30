-- name: help
SELECT * FROM practice_help WHERE suite_id = :suite_id AND run_ref = :run_ref
AND question_index = :question_index AND kind = :kind AND context_key = :context_key;

-- name: live_model_choice
SELECT c.model_choice FROM messages m JOIN conversations c USING(conversation_id)
WHERE c.course_id = :course_id AND (m.message_id = :message_id OR m.trace_id = :trace_id)
ORDER BY m.created_at DESC LIMIT 1;

-- name: claim
INSERT INTO practice_help(help_id, suite_id, run_ref, question_index, kind, context_key, status, claim, content)
VALUES(:help_id, :suite_id, :run_ref, :question_index, :kind, :context_key, 'pending', :claim, '{}')
ON CONFLICT(suite_id, run_ref, question_index, kind, context_key) DO UPDATE SET
status = 'pending', claim = excluded.claim, updated_at = now_utc()
WHERE practice_help.status = 'failed'
OR (practice_help.status = 'pending' AND practice_help.updated_at < :expired);

-- name: finish
UPDATE practice_help SET status = :status, content = :content, model = :model,
prompt_version = :prompt_version, fell_back_to_local = :fell_back_to_local, updated_at = now_utc()
WHERE help_id = :help_id AND claim = :claim AND status = 'pending';

-- name: course_help
SELECT h.*, s.questions FROM practice_help h JOIN practice_suites s USING(suite_id)
WHERE s.course_id = :course_id AND h.status = 'ready';

-- name: pending
SELECT h.help_id FROM practice_help h JOIN practice_suites s USING(suite_id)
WHERE s.course_id = :course_id AND h.suite_id = :suite_id AND h.run_ref = :run_ref
AND h.status = 'pending' AND h.updated_at >= :expired;

-- name: feedback
SELECT f.* FROM practice_feedback f JOIN practice_suites s USING(suite_id)
WHERE s.course_id = :course_id AND f.suite_id = :suite_id ORDER BY f.question_index, f.target;

-- name: rate
INSERT INTO practice_feedback(suite_id, question_index, target, help_id, rating, reason)
VALUES(:suite_id, :question_index, :target, :help_id, :rating, :reason)
ON CONFLICT(suite_id, question_index, target) DO UPDATE SET
help_id = excluded.help_id, rating = excluded.rating, reason = excluded.reason, updated_at = now_utc();

-- name: unrate
DELETE FROM practice_feedback WHERE suite_id = :suite_id AND question_index = :question_index AND target = :target;

-- name: feedback_context
SELECT f.*, s.questions, s.evidence, h.content FROM practice_feedback f
JOIN practice_suites s USING(suite_id) LEFT JOIN practice_help h USING(help_id)
WHERE s.course_id = :course_id ORDER BY f.updated_at DESC LIMIT :limit;

-- name: exported_help
SELECT h.* FROM practice_help h JOIN practice_suites s USING(suite_id)
WHERE s.course_id = :course_id AND h.status = 'ready';

-- name: exported_feedback
SELECT f.* FROM practice_feedback f JOIN practice_suites s USING(suite_id)
WHERE s.course_id = :course_id;

-- name: import_help
INSERT INTO practice_help(help_id, suite_id, run_ref, question_index, kind, context_key, status, claim, content, model, prompt_version, fell_back_to_local, updated_at)
VALUES(:help_id, :suite_id, :run_ref, :question_index, :kind, :context_key, 'ready', :claim, :content, :model, :prompt_version, :fell_back_to_local, :updated_at);

-- name: import_feedback
INSERT INTO practice_feedback(suite_id, question_index, target, help_id, rating, reason, updated_at)
VALUES(:suite_id, :question_index, :target, :help_id, :rating, :reason, :updated_at);
