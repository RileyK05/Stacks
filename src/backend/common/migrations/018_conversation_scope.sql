-- Source-scope revisions within a chat (B-02).
--
-- When the student changes which sources a chat may use, answers already
-- in the chat were established against the old selection. The rolling
-- summary must not re-assert those facts, and the next answer must treat
-- the conversation as context only. Recording the message seq at the
-- moment the scope changes lets the summarizer fold the pre-change turns
-- into a topic-only summary and exclude the post-change turns until the
-- topic is re-established against current material.
--
-- 0 means "no scope revision recorded" and is the value every existing
-- row takes, so upgraded chats behave exactly as before until the next
-- scope change.
ALTER TABLE conversations ADD COLUMN scope_revised_seq INTEGER NOT NULL DEFAULT 0;
-- The source selection in force when the scope last changed; NULL means
-- every source (the same meaning as `source_ids`). Used only for audit
-- and to report the revision back to the client.
ALTER TABLE conversations ADD COLUMN scope_revised_ids JSON
    CHECK (scope_revised_ids IS NULL OR json_valid(scope_revised_ids));
