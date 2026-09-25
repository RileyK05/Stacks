-- Saved chats (docs/plan-notebook.md §4.2, decision 013): unlimited
-- conversations per course. A conversation is a working session; what
-- persists across them (memory, artifacts, course knowledge) lives
-- elsewhere.
--
-- `model_choice` pins the chat to one endpoint + model ({"connection",
-- "model"}); NULL follows Settings. `source_ids` narrows retrieval to
-- chosen sources; NULL means every source in the course. `summary` is the
-- rolling digest of messages up to `summary_through` (a message seq), so a
-- small model reads the digest plus the recent turns instead of the whole
-- chat.
CREATE TABLE conversations (
    conversation_id  UUID PRIMARY KEY,
    course_id        UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    title            TEXT NOT NULL DEFAULT '',
    model_choice     JSON CHECK (model_choice IS NULL OR json_valid(model_choice)),
    source_ids       JSON CHECK (source_ids IS NULL OR json_valid(source_ids)),
    summary          TEXT NOT NULL DEFAULT '',
    summary_through  INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMP NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    updated_at       TIMESTAMP NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX idx_conversations_course ON conversations (course_id, updated_at);

-- One row per turn half. `payload` carries what the chat shows beside the
-- text (citations' chunk ids, workspace items, model, cache and fallback
-- flags) in the same shape the ask API returns; `trace_id` links the
-- evidence so an old answer still opens its sources.
CREATE TABLE messages (
    message_id       UUID PRIMARY KEY,
    conversation_id  UUID NOT NULL
                     REFERENCES conversations (conversation_id) ON DELETE CASCADE,
    seq              INTEGER NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text             TEXT NOT NULL,
    trace_id         UUID REFERENCES retrieval_traces (trace_id) ON DELETE SET NULL,
    payload          JSON NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    created_at       TIMESTAMP NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    UNIQUE (conversation_id, seq)
);
CREATE INDEX idx_messages_trace ON messages (trace_id);
