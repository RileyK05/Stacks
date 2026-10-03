-- name: source_fence
SELECT source.source_id, source.course_id, COALESCE(source.file_hash, '') AS file_hash, source.status,
       course.deleted_at, idx.revision
FROM sources AS source
JOIN courses AS course ON course.course_id = source.course_id
LEFT JOIN source_indexes AS idx ON idx.source_id = source.source_id
WHERE source.source_id = :source_id;

-- name: delete_containers
DELETE FROM passage_containers WHERE source_id = :source_id;

-- name: insert_container
INSERT INTO passage_containers
    (container_id, source_id, revision, parent_id, title, level, char_start, char_end, origin)
VALUES (:container_id, :source_id, :revision, :parent_id, :title, :level, :char_start, :char_end, :origin);

-- name: insert_passage
INSERT INTO chunks (chunk_id, source_id, locator_id, chunk_index, text,
                    container_id, revision, char_start, char_end, unit_kind, boundary)
VALUES (:chunk_id, :source_id, :locator_id, :chunk_index, :text,
        :container_id, :revision, :char_start, :char_end, :unit_kind, :boundary);

-- name: insert_window
INSERT INTO passage_windows (window_id, chunk_id, char_start, char_end,
                             model, dimension, embedding, text_hash)
VALUES (:window_id, :chunk_id, :char_start, :char_end, :model, :dimension, :embedding, :text_hash);

-- name: publish_index
INSERT INTO source_indexes (source_id, revision, file_hash, extraction_version,
                            segmentation_version, semantic_used, warning)
VALUES (:source_id, :revision, :file_hash, :extraction_version,
        :segmentation_version, :semantic_used, :warning)
ON CONFLICT(source_id) DO UPDATE SET revision = excluded.revision,
    file_hash = excluded.file_hash, extraction_version = excluded.extraction_version,
    segmentation_version = excluded.segmentation_version, semantic_used = excluded.semantic_used,
    warning = excluded.warning, published_at = now_utc();

-- name: previous_passages
SELECT chunk_id, text, char_start, char_end, locator_id FROM chunks
WHERE source_id = :source_id ORDER BY chunk_index;

-- name: eligible_neighbors
SELECT neighbor.chunk_id, neighbor.source_id, neighbor.locator_id,
       neighbor.chunk_index, neighbor.text,
       abs(neighbor.chunk_index - hit.chunk_index) AS distance,
       hit.chunk_id AS anchor_id,
       hit_vector.dimension AS anchor_dimension, hit_vector.embedding AS anchor_vector,
       neighbor_vector.dimension AS neighbor_dimension,
       neighbor_vector.embedding AS neighbor_vector
FROM chunks AS hit
JOIN chunks AS neighbor ON neighbor.source_id = hit.source_id
    AND neighbor.container_id IS hit.container_id
JOIN sources AS source ON source.source_id = neighbor.source_id
JOIN courses AS course ON course.course_id = source.course_id
LEFT JOIN chunk_embeddings AS hit_vector ON hit_vector.chunk_id = hit.chunk_id
    AND hit_vector.model = :model
LEFT JOIN chunk_embeddings AS neighbor_vector ON neighbor_vector.chunk_id = neighbor.chunk_id
    AND neighbor_vector.model = :model
WHERE hit.chunk_id IN (SELECT value FROM json_each(:chunk_ids))
  AND source.course_id = :course_id AND course.deleted_at IS NULL
  AND (source.status = 'indexed' OR EXISTS (
      SELECT 1 FROM source_indexes WHERE source_id = source.source_id))
  AND abs(neighbor.chunk_index - hit.chunk_index) BETWEEN 1 AND :radius
  AND (:source_ids IS NULL OR source.source_id IN (SELECT value FROM json_each(:source_ids)))
ORDER BY distance, neighbor.source_id, neighbor.chunk_index
LIMIT :limit;

-- name: course_containers
SELECT container.* FROM passage_containers AS container
JOIN sources AS source ON source.source_id = container.source_id
JOIN courses AS course ON course.course_id = source.course_id
WHERE source.course_id = :course_id AND course.deleted_at IS NULL
  AND (:source_ids IS NULL OR source.source_id IN (SELECT value FROM json_each(:source_ids)))
ORDER BY container.source_id, container.char_start, container.level;

-- name: saved_generated_materials
SELECT artifact.artifact_id, artifact.version, artifact.title,
       version.content, version.sources, artifact.origin,
       EXISTS (SELECT 1 FROM artifact_versions AS prior
               WHERE prior.artifact_id = artifact.artifact_id
                 AND prior.author = 'model') AS has_model_history
FROM artifacts AS artifact
JOIN artifact_versions AS version ON version.artifact_id = artifact.artifact_id
    AND version.version = artifact.version
WHERE artifact.course_id = :course_id
ORDER BY artifact.updated_at DESC, artifact.artifact_id;

-- name: eligible_support
SELECT chunk.chunk_id, chunk.source_id, chunk.locator_id, chunk.chunk_index, chunk.text
FROM chunks AS chunk
JOIN sources AS source ON source.source_id = chunk.source_id
JOIN courses AS course ON course.course_id = source.course_id
WHERE chunk.chunk_id IN (SELECT value FROM json_each(:chunk_ids))
  AND source.course_id = :course_id AND course.deleted_at IS NULL
  AND (source.status = 'indexed' OR EXISTS (
      SELECT 1 FROM source_indexes WHERE source_id = source.source_id))
  AND (:source_ids IS NULL OR source.source_id IN (SELECT value FROM json_each(:source_ids)))
ORDER BY chunk.source_id, chunk.chunk_index;

-- name: course_passages
SELECT chunk.*, source.filename FROM chunks AS chunk
JOIN sources AS source ON source.source_id = chunk.source_id
JOIN courses AS course ON course.course_id = source.course_id
WHERE source.course_id = :course_id AND course.deleted_at IS NULL
  AND (source.status = 'indexed' OR EXISTS (
      SELECT 1 FROM source_indexes WHERE source_id = source.source_id))
  AND (:source_ids IS NULL OR source.source_id IN (SELECT value FROM json_each(:source_ids)))
ORDER BY chunk.source_id, chunk.chunk_index;
