-- Retain generated course annotations as ordinary, inspectable saved material.
-- Original files, passages, citation snapshots and learner records are untouched.
INSERT INTO artifacts (artifact_id, course_id, kind, title, content, sources, origin)
SELECT concept.concept_id, concept.course_id, 'doc', 'Imported annotation: ' || concept.name,
       json_object('markdown', 'Imported course annotation; verify against its sources.'
           || char(10) || char(10) || concept.definition),
       COALESCE((SELECT json_group_array(chunk_id) FROM (
           SELECT chunk_id FROM concept_chunks WHERE concept_id = concept.concept_id
           ORDER BY chunk_id)), '[]'),
       json_object('type', 'legacy_knowledge_annotation', 'concept_id', concept.concept_id,
                   'evidence_level', concept.evidence_level, 'synonyms', json(concept.synonyms))
FROM concepts AS concept;

INSERT INTO artifacts (artifact_id, course_id, kind, title, content, sources, origin)
SELECT memory.memory_id, concept.course_id, 'doc',
       'Imported ' || memory.kind || ': ' || concept.name,
       json_object('markdown', 'Imported course annotation; verify against its sources.'
           || char(10) || char(10) || memory.content),
       COALESCE((SELECT json_group_array(chunk_id) FROM (
           SELECT chunk_id FROM memory_object_evidence WHERE memory_id = memory.memory_id
           ORDER BY chunk_id)), '[]'),
       json_object('type', 'legacy_knowledge_annotation', 'memory_id', memory.memory_id,
                   'concept_id', memory.concept_id, 'source_id', memory.source_id,
                   'evidence_level', memory.evidence_level)
FROM memory_objects AS memory JOIN concepts AS concept ON concept.concept_id = memory.concept_id;

INSERT INTO artifact_versions (artifact_id, version, title, content, sources, author, note)
SELECT artifact_id, 1, title, content, sources, 'model', 'Retained from the retired course-knowledge store'
FROM artifacts WHERE json_extract(origin, '$.type') = 'legacy_knowledge_annotation';

DROP TABLE graph_cluster_members;
DROP TABLE graph_clusters;
DROP TABLE dependencies;
DROP TABLE memory_object_evidence;
DROP TABLE memory_objects;
DROP TABLE concept_chunks;
DROP TABLE concepts;
DROP TRIGGER toc_entries_fts_insert;
DROP TRIGGER toc_entries_fts_delete;
DROP TRIGGER toc_entries_fts_update;
DROP TABLE toc_entries_fts;
DROP TABLE toc_entries;
DROP TABLE tables_of_contents;

UPDATE retrieval_traces SET retrieved_chunk_ids = json_set(
    retrieved_chunk_ids, '$.legacy_toc_entry_ids', json(retrieved_toc_entry_ids))
WHERE json_array_length(retrieved_toc_entry_ids) > 0;
ALTER TABLE retrieval_traces DROP COLUMN retrieved_toc_entry_ids;
