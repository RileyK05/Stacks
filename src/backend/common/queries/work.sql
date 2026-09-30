-- name: list
SELECT * FROM work_sessions WHERE course_id = :course_id ORDER BY updated_at DESC, session_id;
-- name: session
SELECT * FROM work_sessions WHERE session_id = :session_id AND course_id = :course_id;
-- name: create
INSERT INTO work_sessions(session_id, course_id, title, purpose) VALUES(:session_id, :course_id, :title, :purpose);
-- name: document
SELECT * FROM work_documents WHERE session_id = :session_id AND revision = :revision;
-- name: documents
SELECT * FROM work_documents WHERE session_id = :session_id ORDER BY revision;
-- name: advance
UPDATE work_sessions SET revision = revision + 1, updated_at = now_utc()
WHERE session_id = :session_id AND course_id = :course_id AND revision = :expected_revision;
-- name: insert_document
INSERT INTO work_documents(session_id, revision, payload) VALUES(:session_id, :revision, :payload);
-- name: turns
SELECT * FROM work_turns WHERE session_id = :session_id ORDER BY created_at, request_id;
-- name: request
SELECT * FROM work_turns WHERE request_id = :request_id;
-- name: insert_turn
INSERT INTO work_turns(request_id, session_id, action, instruction, selection, document_revision, reply)
VALUES(:request_id, :session_id, :action, :instruction, :selection, :document_revision, :reply);
-- name: touch
UPDATE work_sessions SET updated_at = now_utc() WHERE session_id = :session_id;
-- name: lock_document
UPDATE work_sessions SET revision = revision WHERE session_id = :session_id AND course_id = :course_id;
-- name: delete
DELETE FROM work_sessions WHERE session_id = :session_id AND course_id = :course_id;
-- name: import_session
INSERT INTO work_sessions(session_id, course_id, title, purpose, revision, updated_at)
VALUES(:session_id, :course_id, :title, :purpose, :revision, :updated_at);
-- name: import_document
INSERT INTO work_documents(session_id, revision, payload, captured_at)
VALUES(:session_id, :revision, :payload, :captured_at);
-- name: import_turn
INSERT INTO work_turns(request_id, session_id, action, instruction, selection, document_revision, reply, created_at)
VALUES(:request_id, :session_id, :action, :instruction, :selection, :document_revision, :reply, :created_at);
