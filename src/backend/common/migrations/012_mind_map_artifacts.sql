CREATE TEMP TABLE kept_artifact_versions AS SELECT * FROM artifact_versions;
DROP TABLE artifact_versions;

CREATE TABLE artifacts_next (
    artifact_id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('doc', 'sheet', 'slides', 'quiz', 'flashcards', 'code', 'chart', 'mind_map')),
    title TEXT NOT NULL,
    content JSON NOT NULL CHECK (json_valid(content)),
    sources JSON NOT NULL DEFAULT '[]' CHECK (json_valid(sources)),
    origin JSON NOT NULL DEFAULT '{}' CHECK (json_valid(origin)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    updated_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
INSERT INTO artifacts_next SELECT artifact_id, course_id, kind, title, content, sources, origin, version, created_at, updated_at FROM artifacts;
DROP TABLE artifacts;
ALTER TABLE artifacts_next RENAME TO artifacts;

CREATE TABLE artifact_versions (
    artifact_id UUID NOT NULL REFERENCES artifacts (artifact_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    content JSON NOT NULL CHECK (json_valid(content)),
    sources JSON NOT NULL CHECK (json_valid(sources)),
    author TEXT NOT NULL CHECK (author IN ('you', 'model')),
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    PRIMARY KEY (artifact_id, version)
);
INSERT INTO artifact_versions SELECT * FROM kept_artifact_versions;
DROP TABLE kept_artifact_versions;

CREATE INDEX idx_artifacts_course ON artifacts (course_id, updated_at);
CREATE UNIQUE INDEX idx_artifacts_message_item
ON artifacts(course_id, json_extract(origin, '$.message_id'), json_extract(origin, '$.item_index'))
WHERE json_extract(origin, '$.adopted') = 1;
CREATE UNIQUE INDEX idx_artifacts_map_request
ON artifacts(course_id, json_extract(origin, '$.map_request_id'))
WHERE kind = 'quiz' AND json_extract(origin, '$.map_request_id') IS NOT NULL;
