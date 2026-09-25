-- Saved chats (migration 003).

-- name: list_for_course
SELECT conversation.conversation_id, conversation.course_id, conversation.title,
       conversation.model_choice, conversation.source_ids,
       conversation.created_at, conversation.updated_at,
       COUNT(message.message_id) AS message_count
FROM conversations AS conversation
LEFT JOIN messages AS message
       ON message.conversation_id = conversation.conversation_id
WHERE conversation.course_id = :course_id
GROUP BY conversation.conversation_id
ORDER BY conversation.updated_at DESC;

-- name: get
SELECT conversation.conversation_id, conversation.course_id, conversation.title,
       conversation.model_choice, conversation.source_ids, conversation.summary,
       conversation.summary_through, conversation.created_at, conversation.updated_at,
       (SELECT COUNT(*) FROM messages AS message
        WHERE message.conversation_id = conversation.conversation_id) AS message_count
FROM conversations AS conversation
WHERE conversation.conversation_id = :conversation_id
  AND conversation.course_id = :course_id;

-- name: create
INSERT INTO conversations (conversation_id, course_id, title)
VALUES (:conversation_id, :course_id, :title);

-- name: update
UPDATE conversations
SET title = :title,
    model_choice = :model_choice,
    source_ids = :source_ids,
    updated_at = now_utc()
WHERE conversation_id = :conversation_id AND course_id = :course_id;

-- name: touch
UPDATE conversations SET updated_at = now_utc()
WHERE conversation_id = :conversation_id;

-- name: set_title_if_empty
UPDATE conversations SET title = :title
WHERE conversation_id = :conversation_id AND title = '';

-- name: set_summary
UPDATE conversations
SET summary = :summary, summary_through = :summary_through
WHERE conversation_id = :conversation_id AND summary_through < :summary_through;

-- name: delete
DELETE FROM conversations
WHERE conversation_id = :conversation_id AND course_id = :course_id;

-- name: messages
SELECT message_id, conversation_id, seq, role, text, trace_id, payload, created_at
FROM messages
WHERE conversation_id = :conversation_id
ORDER BY seq;

-- name: next_seq
SELECT COALESCE(MAX(seq), 0) + 1 AS seq
FROM messages WHERE conversation_id = :conversation_id;

-- name: add_message
INSERT INTO messages (message_id, conversation_id, seq, role, text, trace_id, payload)
VALUES (:message_id, :conversation_id, :seq, :role, :text, :trace_id, :payload);
