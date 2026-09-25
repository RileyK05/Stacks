-- Artifacts (migration 004).

-- name: list_for_course
SELECT artifact_id, course_id, kind, title, origin, version, created_at, updated_at
FROM artifacts
WHERE course_id = :course_id
ORDER BY updated_at DESC;

-- name: get
SELECT artifact_id, course_id, kind, title, content, sources, origin, version,
       created_at, updated_at
FROM artifacts
WHERE artifact_id = :artifact_id AND course_id = :course_id;

-- name: create
INSERT INTO artifacts (artifact_id, course_id, kind, title, content, sources, origin)
VALUES (:artifact_id, :course_id, :kind, :title, :content, :sources, :origin);

-- name: save
-- A new version on top of `expected_version`; no row changes when the
-- artifact moved on meanwhile (the caller reports a conflict).
UPDATE artifacts
SET title = :title,
    content = :content,
    sources = :sources,
    version = version + 1,
    updated_at = now_utc()
WHERE artifact_id = :artifact_id
  AND course_id = :course_id
  AND version = :expected_version;

-- name: add_version
INSERT INTO artifact_versions (artifact_id, version, title, content, sources, author, note)
VALUES (:artifact_id, :version, :title, :content, :sources, :author, :note);

-- name: versions
SELECT version, title, author, note, created_at
FROM artifact_versions
WHERE artifact_id = :artifact_id
ORDER BY version DESC;

-- name: version
SELECT version, title, content, sources, author, note, created_at
FROM artifact_versions
WHERE artifact_id = :artifact_id AND version = :version;

-- name: delete
DELETE FROM artifacts WHERE artifact_id = :artifact_id AND course_id = :course_id;

-- name: chunks_in_course
-- Which of the given chunk ids belong to this course (an artifact may only
-- cite its own course's material).
SELECT chunk.chunk_id
FROM chunks AS chunk
JOIN sources AS source ON source.source_id = chunk.source_id
WHERE source.course_id = :course_id
  AND chunk.chunk_id IN (SELECT value FROM json_each(:chunk_ids));
