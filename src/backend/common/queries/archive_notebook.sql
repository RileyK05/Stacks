-- Notebook export/import for .course format v2.

-- name: conversations
SELECT * FROM conversations WHERE course_id = :course_id ORDER BY created_at;

-- name: messages
SELECT seq, role, text, trace_id, payload, created_at
FROM messages WHERE conversation_id = :conversation_id ORDER BY seq;

-- name: artifacts
SELECT * FROM artifacts WHERE course_id = :course_id ORDER BY created_at;

-- name: versions
SELECT version, title, content, sources, author, note, created_at
FROM artifact_versions WHERE artifact_id = :artifact_id ORDER BY version;

-- name: trace
SELECT query, retrieved_chunk_ids, model FROM retrieval_traces
WHERE trace_id = :trace_id AND course_id = :course_id;

-- name: insert_snapshot
INSERT INTO citation_snapshots
    (chunk_id, course_id, source_id, chunk_index, text, locator_type,
     label, description)
VALUES (:chunk_id, :course_id, :source_id, :chunk_index, :text,
        :locator_type, :label, :description);

-- name: insert_trace
INSERT INTO retrieval_traces
    (trace_id, course_id, query, retrieved_chunk_ids,
     retrieved_toc_entry_ids, model)
VALUES (:trace_id, :course_id, :query, :chunk_ids, '[]', :model);

-- name: insert_conversation
INSERT INTO conversations
    (conversation_id, course_id, title, model_choice, source_ids, summary,
     summary_through, created_at, updated_at)
VALUES (:conversation_id, :course_id, :title, :model_choice, :source_ids, :summary,
        :summary_through, :created_at, :updated_at);

-- name: insert_message
INSERT INTO messages
    (message_id, conversation_id, seq, role, text, trace_id, payload,
     created_at)
VALUES (:message_id, :conversation_id, :seq, :role, :text, :trace_id,
        :payload, :created_at);

-- name: insert_artifact
INSERT INTO artifacts
    (artifact_id, course_id, kind, title, content, sources, origin, version,
     created_at, updated_at)
VALUES (:artifact_id, :course_id, :kind, :title, :content, :sources, :origin,
        :version, :created_at, :updated_at);

-- name: insert_version
INSERT INTO artifact_versions
    (artifact_id, version, title, content, sources, author, note, created_at)
VALUES (:artifact_id, :version, :title, :content, :sources, :author, :note,
        :created_at);
