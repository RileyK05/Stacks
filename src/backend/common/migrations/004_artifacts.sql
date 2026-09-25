-- Artifacts (docs/plan-notebook.md §4.3, decision 013): typed, editable
-- study material saved in a course — docs, sheets, slide decks, quizzes,
-- flashcards, code, charts — made by the student or with the model.
--
-- `content` is the artifact's typed JSON (src/backend/artifacts/content.py).
-- `sources` is the artifact's own ordered list of cited chunk ids: a "[n]"
-- anywhere in the content means sources[n-1], whichever chat or edit it
-- came from. A chunk removed with its source leaves a gap the citation
-- view reports, never a renumbering.
--
-- Every save is a version: `artifact_versions` keeps the full content, who
-- made the change (the student or the model, on the student's acceptance),
-- and a note. `version` on the artifact is the latest one, used to refuse
-- a save based on an outdated copy.
CREATE TABLE artifacts (
    artifact_id  UUID PRIMARY KEY,
    course_id    UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    kind         TEXT NOT NULL
                 CHECK (kind IN ('doc', 'sheet', 'slides', 'quiz', 'flashcards', 'code', 'chart')),
    title        TEXT NOT NULL,
    content      JSON NOT NULL CHECK (json_valid(content)),
    sources      JSON NOT NULL DEFAULT '[]' CHECK (json_valid(sources)),
    origin       JSON NOT NULL DEFAULT '{}' CHECK (json_valid(origin)),
    version      INTEGER NOT NULL DEFAULT 1,
    created_at   TIMESTAMP NOT NULL
                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    updated_at   TIMESTAMP NOT NULL
                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX idx_artifacts_course ON artifacts (course_id, updated_at);

CREATE TABLE artifact_versions (
    artifact_id  UUID NOT NULL REFERENCES artifacts (artifact_id) ON DELETE CASCADE,
    version      INTEGER NOT NULL,
    title        TEXT NOT NULL,
    content      JSON NOT NULL CHECK (json_valid(content)),
    sources      JSON NOT NULL CHECK (json_valid(sources)),
    author       TEXT NOT NULL CHECK (author IN ('you', 'model')),
    note         TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMP NOT NULL
                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    PRIMARY KEY (artifact_id, version)
);
