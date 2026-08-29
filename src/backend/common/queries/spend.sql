-- name: active_subscription
SELECT subscription_id, user_id, tier, started_at, ended_at
FROM user_subscriptions
WHERE user_id = %(user_id)s AND ended_at IS NULL;

-- name: start_subscription
INSERT INTO user_subscriptions (user_id, tier)
VALUES (%(user_id)s, %(tier)s)
RETURNING subscription_id, user_id, tier, started_at, ended_at;

-- name: end_active_subscription
UPDATE user_subscriptions
SET ended_at = now()
WHERE user_id = %(user_id)s AND ended_at IS NULL
RETURNING subscription_id, user_id, tier, started_at, ended_at;

-- name: weekly_spend
SELECT COALESCE(SUM(input_tokens + output_tokens + overhead_tokens), 0) AS spent
FROM generation_ledger
WHERE user_id = %(user_id)s
  AND created_at >= %(week_start)s;

-- name: record
INSERT INTO generation_ledger
    (user_id, course_id, course_label, task, model, input_tokens, output_tokens, overhead_tokens)
VALUES (%(user_id)s, %(course_id)s, %(course_label)s, %(task)s, %(model)s, %(input_tokens)s, %(output_tokens)s, %(overhead_tokens)s)
RETURNING ledger_id, user_id, course_id, course_label, task, model, input_tokens, output_tokens, overhead_tokens, created_at;

-- name: ledger_page
SELECT ledger_id, user_id, course_id, course_label, task, model, input_tokens, output_tokens, overhead_tokens, created_at
FROM generation_ledger
WHERE user_id = %(user_id)s
ORDER BY created_at DESC
LIMIT %(limit)s;