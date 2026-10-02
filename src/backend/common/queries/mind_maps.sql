-- name: message
SELECT m.message_id, m.payload, c.model_choice, c.source_ids
FROM messages m JOIN conversations c USING(conversation_id)
WHERE c.course_id = :course_id AND m.message_id = :message_id
  AND m.role = 'assistant';

-- name: quiz_request
SELECT artifact_id FROM artifacts
WHERE course_id = :course_id AND kind = 'quiz'
  AND json_extract(origin, '$.map_request_id') = :request_id;
