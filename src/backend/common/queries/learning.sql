-- name: create_suite
INSERT OR IGNORE INTO practice_suites(suite_id, course_id, title, questions, evidence, origin, method)
VALUES(:suite_id, :course_id, :title, :questions, :evidence, :origin, :method);

-- name: suite
SELECT * FROM practice_suites WHERE course_id = :course_id AND suite_id = :suite_id;

-- name: teach
INSERT INTO learning_teaching_events(event_id, course_id, method, source_ids, trace_ref, excerpt)
VALUES(:event_id, :course_id, :method, :source_ids, :trace_ref, :excerpt);

-- name: teaching_events
SELECT * FROM learning_teaching_events WHERE course_id = :course_id ORDER BY created_at DESC LIMIT 10;

-- name: suites
SELECT * FROM practice_suites WHERE course_id = :course_id ORDER BY created_at DESC;

-- name: runs
SELECT * FROM practice_runs WHERE course_id = :course_id ORDER BY created_at DESC, run_id;

-- name: run
SELECT * FROM practice_runs WHERE course_id = :course_id AND run_id = :run_id;

-- name: create_run
INSERT OR IGNORE INTO practice_runs(run_id, suite_id, course_id, answers, helped, requested_help, policy_version)
VALUES(:run_id, :suite_id, :course_id, :answers, :helped, :requested_help, :policy_version);

-- name: update_run_help
UPDATE practice_runs SET helped = :helped WHERE course_id = :course_id AND run_id = :run_id;

-- name: delete_run
DELETE FROM practice_runs WHERE course_id = :course_id AND run_id = :run_id RETURNING run_id;

-- name: assessments
SELECT * FROM practice_assessments WHERE suite_id = :suite_id;

-- name: correct_assessment
INSERT INTO practice_assessments(suite_id, question_index, answer, reason)
VALUES(:suite_id, :question_index, :answer, :reason)
ON CONFLICT(suite_id, question_index) DO UPDATE SET
answer = excluded.answer, reason = excluded.reason, updated_at = now_utc();

-- name: observations
SELECT * FROM learning_observations WHERE course_id = :course_id ORDER BY created_at, observation_id;

-- name: create_observation
INSERT INTO learning_observations(observation_id, course_id, run_ref, suite_ref,
question_index, fingerprint, topic, capability, correct, helped, fresh, method, evidence)
VALUES(:observation_id, :course_id, :run_ref, :suite_ref, :question_index, :fingerprint,
:topic, :capability, :correct, :helped, :fresh, :method, :evidence);

-- name: revise_observation
UPDATE learning_observations SET correct = :correct, evidence = :evidence
WHERE observation_id = :observation_id;

-- name: forget_target
DELETE FROM learning_observations
WHERE course_id = :course_id AND LOWER(topic) = LOWER(:topic) AND capability = :capability;

-- name: core_observations
SELECT * FROM core_method_observations ORDER BY created_at, observation_id;

-- name: core_observation
INSERT INTO core_method_observations(observation_id, course_ref, method, correct, helped, fresh, evidence)
VALUES(:observation_id, :course_ref, :method, :correct, :helped, :fresh, :evidence)
ON CONFLICT(observation_id) DO UPDATE SET correct = excluded.correct, evidence = excluded.evidence;

-- name: forget_method
DELETE FROM core_method_observations WHERE method = :method;

-- name: experiments
SELECT * FROM learning_experiments WHERE course_id = :course_id ORDER BY created_at, experiment_id;

-- name: create_experiment
INSERT OR IGNORE INTO learning_experiments(experiment_id, course_id, message_ref,
topic, capability, hypothesis, proposed_check, evidence, expires_at)
SELECT :experiment_id, :course_id, :message_ref, :topic, :capability, :hypothesis,
:proposed_check, :evidence, :expires_at
WHERE (SELECT COUNT(*) FROM learning_experiments
       WHERE course_id = :course_id AND status IN ('proposed','cooldown')
         AND expires_at > now_utc()) < :max_open
AND NOT EXISTS (SELECT 1 FROM learning_experiments WHERE course_id = :course_id
                AND LOWER(topic) = LOWER(:topic) AND capability = :capability);

-- name: update_experiment
UPDATE learning_experiments SET status = :status, checks = :checks, next_check_at = :next_check_at
WHERE experiment_id = :experiment_id AND course_id = :course_id;

-- name: forget_experiments
DELETE FROM learning_experiments WHERE course_id = :course_id AND LOWER(topic) = LOWER(:topic) AND capability = :capability;

-- name: experiment_evidence
UPDATE learning_experiments SET evidence = :evidence
WHERE experiment_id = :experiment_id AND course_id = :course_id;

-- name: import_suite
INSERT INTO practice_suites(suite_id, course_id, title, questions, evidence, origin, method, created_at)
VALUES(:suite_id, :course_id, :title, :questions, :evidence, :origin, :method, :created_at);

-- name: import_run
INSERT INTO practice_runs(run_id, suite_id, course_id, answers, helped, requested_help, policy_version, created_at)
VALUES(:run_id, :suite_id, :course_id, :answers, :helped, :requested_help, :policy_version, :created_at);

-- name: import_observation
INSERT INTO learning_observations(observation_id, course_id, run_ref, suite_ref,
question_index, fingerprint, topic, capability, correct, helped, fresh, method, evidence, created_at)
VALUES(:observation_id, :course_id, :run_ref, :suite_ref, :question_index, :fingerprint,
:topic, :capability, :correct, :helped, :fresh, :method, :evidence, :created_at);

-- name: import_experiment
INSERT INTO learning_experiments(experiment_id, course_id, message_ref, topic, capability,
hypothesis, proposed_check, evidence, status, checks, next_check_at, expires_at, created_at)
VALUES(:experiment_id, :course_id, :message_ref, :topic, :capability, :hypothesis,
:proposed_check, :evidence, :status, :checks, :next_check_at, :expires_at, :created_at);
