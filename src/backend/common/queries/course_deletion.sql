-- name: delete_course_subtree
DELETE FROM user_artifacts WHERE source_course_id = %(course_id)s;
DELETE FROM citation_snapshots WHERE course_id = %(course_id)s;
DELETE FROM attempts
WHERE course_id = %(course_id)s
   OR item_id IN (
       SELECT item_id FROM assessment_items WHERE course_id = %(course_id)s
   )
   OR chunk_id IN (
       SELECT chunk_id FROM chunks
       WHERE source_id IN (
           SELECT source_id FROM sources WHERE course_id = %(course_id)s
       )
   );
DELETE FROM recommendations
WHERE course_id = %(course_id)s
   OR concept_id IN (
       SELECT concept_id FROM concepts WHERE course_id = %(course_id)s
   );
DELETE FROM concept_mastery
WHERE concept_id IN (
    SELECT concept_id FROM concepts WHERE course_id = %(course_id)s
);
DELETE FROM assessment_items
WHERE course_id = %(course_id)s
   OR source_id IN (
       SELECT source_id FROM sources WHERE course_id = %(course_id)s
   );
DELETE FROM citations
WHERE claim_id IN (
    SELECT claim.claim_id
    FROM claims AS claim
    JOIN responses AS response ON response.response_id = claim.response_id
    WHERE response.conversation_id IN (
        SELECT conversation_id FROM conversations WHERE course_id = %(course_id)s
    )
       OR response.trace_id IN (
        SELECT trace_id FROM retrieval_traces WHERE course_id = %(course_id)s
    )
)
   OR trace_id IN (
       SELECT trace_id FROM retrieval_traces WHERE course_id = %(course_id)s
   );
DELETE FROM claims WHERE response_id IN
    (SELECT response_id FROM responses
     WHERE conversation_id IN (
         SELECT conversation_id FROM conversations WHERE course_id = %(course_id)s
     )
        OR trace_id IN (
         SELECT trace_id FROM retrieval_traces WHERE course_id = %(course_id)s
     ));
DELETE FROM responses
WHERE conversation_id IN (
        SELECT conversation_id FROM conversations WHERE course_id = %(course_id)s
    )
   OR trace_id IN (
        SELECT trace_id FROM retrieval_traces WHERE course_id = %(course_id)s
    );
DELETE FROM retrieval_traces WHERE course_id = %(course_id)s;
DELETE FROM chat_summaries WHERE conversation_id IN
    (SELECT conversation_id FROM conversations WHERE course_id = %(course_id)s);
DELETE FROM conversation_turns WHERE conversation_id IN
    (SELECT conversation_id FROM conversations WHERE course_id = %(course_id)s);
DELETE FROM conversations WHERE course_id = %(course_id)s;
DELETE FROM memory_object_evidence
WHERE memory_id IN (
        SELECT memory_id FROM memory_objects
        WHERE concept_id IN (
            SELECT concept_id FROM concepts WHERE course_id = %(course_id)s
        )
           OR source_id IN (
            SELECT source_id FROM sources WHERE course_id = %(course_id)s
        )
    )
   OR chunk_id IN (
        SELECT chunk_id FROM chunks
        WHERE source_id IN (
            SELECT source_id FROM sources WHERE course_id = %(course_id)s
        )
    );
DELETE FROM memory_objects
WHERE concept_id IN (
        SELECT concept_id FROM concepts WHERE course_id = %(course_id)s
    )
   OR source_id IN (
        SELECT source_id FROM sources WHERE course_id = %(course_id)s
    );
DELETE FROM dependencies WHERE dependent_id IN (SELECT concept_id FROM concepts WHERE course_id = %(course_id)s);
DELETE FROM dependencies WHERE prereq_id IN (SELECT concept_id FROM concepts WHERE course_id = %(course_id)s);
DELETE FROM concepts WHERE course_id = %(course_id)s;
DELETE FROM toc_entries
WHERE toc_id IN (
        SELECT toc_id FROM tables_of_contents WHERE course_id = %(course_id)s
    )
   OR source_id IN (
        SELECT source_id FROM sources WHERE course_id = %(course_id)s
    )
   OR locator_id IN (
        SELECT locator_id FROM locators
        WHERE source_id IN (
            SELECT source_id FROM sources WHERE course_id = %(course_id)s
        )
    );
DELETE FROM tables_of_contents WHERE course_id = %(course_id)s;
DELETE FROM model_decisions WHERE source_id IN (SELECT source_id FROM sources WHERE course_id = %(course_id)s);
DELETE FROM artifact_origins WHERE artifact_id IN (SELECT object_id FROM course_objects WHERE course_id = %(course_id)s);
DELETE FROM ingestion_runs WHERE source_id IN (SELECT source_id FROM sources WHERE course_id = %(course_id)s);
DELETE FROM ingestion_history WHERE course_id = %(course_id)s;
DELETE FROM chunks WHERE source_id IN (SELECT source_id FROM sources WHERE course_id = %(course_id)s);
DELETE FROM locators WHERE source_id IN (SELECT source_id FROM sources WHERE course_id = %(course_id)s);
DELETE FROM sources WHERE course_id = %(course_id)s;
DELETE FROM course_objects WHERE course_id = %(course_id)s;
DELETE FROM course_enrollments WHERE course_id = %(course_id)s;
DELETE FROM study_periods WHERE course_id = %(course_id)s;
DELETE FROM courses WHERE course_id = %(course_id)s;
