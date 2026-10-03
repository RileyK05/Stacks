-- Source overlap alone never established that a quiz followed a teaching event.
-- Keep the discarded association for inspection; remove only method evidence,
-- preserving the question answers and course capability observations.
UPDATE practice_suites
SET origin = json_set(origin,
        '$.discarded_teaching_context', json_extract(origin, '$.teaching_context'),
        '$.discarded_teaching_method', method,
        '$.teaching_context_invalidated', 1,
        '$.teaching_context', NULL),
    method = NULL
WHERE json_extract(origin, '$.teaching_context.trace_ref') IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM messages AS quiz
    JOIN messages AS teaching
      ON teaching.conversation_id = quiz.conversation_id
     AND teaching.seq < quiz.seq
    WHERE quiz.trace_id = json_extract(practice_suites.origin, '$.trace_id')
      AND teaching.trace_id = json_extract(
          practice_suites.origin, '$.teaching_context.trace_ref')
  );

DELETE FROM core_method_observations
WHERE observation_id IN (
    SELECT observation.observation_id FROM learning_observations AS observation
    JOIN practice_suites AS suite ON suite.suite_id = observation.suite_ref
    WHERE json_extract(suite.origin, '$.teaching_context_invalidated') = 1
);

UPDATE learning_observations
SET method = NULL,
    evidence = json_set(evidence,
        '$.discarded_teaching_context', json_extract(evidence, '$.teaching_context'),
        '$.teaching_context_invalidated', 1,
        '$.teaching_context', NULL)
WHERE suite_ref IN (
    SELECT suite_id FROM practice_suites
    WHERE json_extract(origin, '$.teaching_context_invalidated') = 1
);
