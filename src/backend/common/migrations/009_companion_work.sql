CREATE TABLE work_sessions (
    session_id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    purpose TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX work_sessions_course ON work_sessions(course_id, updated_at);
CREATE TABLE work_documents (
    session_id UUID NOT NULL REFERENCES work_sessions(session_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    payload JSON NOT NULL,
    captured_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    PRIMARY KEY(session_id, revision)
);
CREATE TABLE work_turns (
    request_id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES work_sessions(session_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    instruction TEXT NOT NULL,
    selection TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    reply JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX work_turns_session ON work_turns(session_id, created_at);
