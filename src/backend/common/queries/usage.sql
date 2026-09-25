-- name: record
INSERT INTO usage_ledger
    (ledger_id, course_id, course_label, task, provider, model,
     input_tokens, output_tokens)
VALUES
    (:ledger_id, :course_id,
     (SELECT name FROM courses WHERE course_id = :course_id),
     :task, :provider, :model, :input_tokens, :output_tokens)
RETURNING ledger_id, course_id, course_label, task, provider, model,
          input_tokens, output_tokens, created_at;

-- name: ledger_page
SELECT ledger_id, course_id, course_label, task, provider, model,
       input_tokens, output_tokens, created_at
FROM usage_ledger
ORDER BY created_at DESC
LIMIT :limit;

-- name: cloud_tokens_since
-- Tokens sent to non-local providers since a point in time: what the
-- optional monthly budget measures (local calls cost nothing).
SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS spent
FROM usage_ledger
WHERE created_at >= :since AND provider <> 'local';

-- name: totals_since
SELECT provider, model, task,
       COUNT(*) AS calls,
       COALESCE(SUM(input_tokens), 0) AS input_tokens,
       COALESCE(SUM(output_tokens), 0) AS output_tokens
FROM usage_ledger
WHERE created_at >= :since
GROUP BY provider, model, task
ORDER BY provider, model, task;
