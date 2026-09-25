-- Course memory (decision 007): the per-course keepsake node.

-- name: memory_concepts
SELECT name, definition
FROM concepts
WHERE course_id = :course_id
ORDER BY name;

-- name: memory_sources
SELECT filename
FROM sources
WHERE course_id = :course_id
ORDER BY created_at, filename;

-- name: memory_objects
SELECT memory.kind AS kind, memory.content
FROM memory_objects AS memory
JOIN concepts AS concept ON concept.concept_id = memory.concept_id
WHERE concept.course_id = :course_id
ORDER BY memory.kind, memory.memory_id;

-- name: memory_evidence
WITH representative_chunks AS (
    SELECT source.source_id, source.filename, source.file_hash,
           locator.label, chunk.text,
           ROW_NUMBER() OVER (
               PARTITION BY source.source_id ORDER BY chunk.chunk_index
           ) AS source_rank
    FROM sources AS source
    LEFT JOIN chunks AS chunk ON chunk.source_id = source.source_id
    LEFT JOIN locators AS locator ON locator.locator_id = chunk.locator_id
    WHERE source.course_id = :course_id
)
SELECT filename, file_hash, label, substr(text, 1, 240) AS excerpt
FROM representative_chunks
WHERE source_rank = 1
ORDER BY filename
LIMIT 10;

-- name: course_name
SELECT name FROM courses WHERE course_id = :course_id;

-- name: upsert_memory
INSERT INTO course_memories
    (memory_id, course_id, course_ref, name, summary, key_concepts,
     token_budget, summary_version)
VALUES
    (:memory_id, :course_id, :course_ref, :name, :summary, :key_concepts,
     :token_budget, :summary_version)
ON CONFLICT (course_id) DO UPDATE
SET name = excluded.name,
    summary = excluded.summary,
    key_concepts = excluded.key_concepts,
    token_budget = excluded.token_budget,
    summary_version = excluded.summary_version,
    updated_at = now_utc();

-- name: list_memories
SELECT memory_id, course_id, course_ref, name, summary, key_concepts,
       token_budget, summary_version, created_at, updated_at
FROM course_memories
ORDER BY updated_at DESC;

-- name: get_memory
SELECT memory_id, course_id, course_ref, name, summary, key_concepts,
       token_budget, summary_version, created_at, updated_at
FROM course_memories
WHERE course_id = :course_id;
