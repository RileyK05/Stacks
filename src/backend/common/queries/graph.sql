-- Source passages and bounded, inferred cosine-similarity edges.

-- name: course_chunk_vectors
-- Every indexed chunk vector for a course under one embedding model.
-- Scoring happens in numpy (a course's vectors fit in memory).
SELECT chunk.chunk_id,
       chunk.source_id,
       chunk.locator_id,
       chunk.chunk_index,
       chunk.text,
       emb.model,
       emb.dimension,
       emb.embedding
FROM chunk_embeddings AS emb
JOIN chunks AS chunk ON chunk.chunk_id = emb.chunk_id
JOIN sources AS source ON source.source_id = chunk.source_id
WHERE source.course_id = :course_id
  AND (source.status = 'indexed' OR EXISTS (SELECT 1 FROM source_indexes WHERE source_id = source.source_id))
  AND EXISTS (SELECT 1 FROM courses WHERE course_id = source.course_id AND deleted_at IS NULL)
  AND emb.model = :model
ORDER BY chunk.chunk_id;

-- name: insert_graph_edge
INSERT INTO graph_edges
    (edge_id, course_id, model, chunk_a, chunk_b, weight, algorithm_version)
VALUES (:edge_id, :course_id, :model, :chunk_a, :chunk_b, :weight, :algorithm_version);

-- name: chunk_ids_by_source
SELECT chunk_id FROM chunks WHERE source_id = :source_id;

-- name: delete_edges_for_chunks
-- Rebuild one source's edges without touching the rest of the course.
DELETE FROM graph_edges
WHERE course_id = :course_id
  AND model = :model
  AND (
      chunk_a IN (SELECT value FROM json_each(:chunk_ids))
      OR chunk_b IN (SELECT value FROM json_each(:chunk_ids))
  );

-- name: course_graph_edges
SELECT chunk_a, chunk_b, weight
FROM graph_edges
WHERE course_id = :course_id
  AND model = :model;

