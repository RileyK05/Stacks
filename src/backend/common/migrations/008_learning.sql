CREATE TABLE practice_suites (
    suite_id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    questions JSON NOT NULL CHECK(json_valid(questions)),
    evidence JSON NOT NULL CHECK(json_valid(evidence)),
    origin JSON NOT NULL CHECK(json_valid(origin)),
    method TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    UNIQUE(course_id, origin)
);
CREATE INDEX idx_practice_suites_course ON practice_suites(course_id);

CREATE TABLE learning_teaching_events (
    event_id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    method TEXT NOT NULL,
    source_ids JSON NOT NULL CHECK(json_valid(source_ids)),
    trace_ref UUID NOT NULL,
    excerpt TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);

CREATE TABLE practice_runs (
    run_id UUID PRIMARY KEY,
    suite_id UUID NOT NULL REFERENCES practice_suites(suite_id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    answers JSON NOT NULL CHECK(json_valid(answers)),
    helped JSON NOT NULL CHECK(json_valid(helped)),
    requested_help JSON NOT NULL CHECK(json_valid(requested_help)),
    policy_version TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX idx_practice_runs_suite ON practice_runs(suite_id, created_at);

CREATE TABLE practice_assessments (
    suite_id UUID NOT NULL REFERENCES practice_suites(suite_id) ON DELETE CASCADE,
    question_index INTEGER NOT NULL CHECK(question_index >= 0),
    answer INTEGER,
    reason TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    PRIMARY KEY(suite_id, question_index)
);

-- Distilled observations deliberately outlive deletion of a raw test run.
CREATE TABLE learning_observations (
    observation_id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    run_ref UUID NOT NULL,
    suite_ref UUID NOT NULL,
    question_index INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    topic TEXT NOT NULL,
    capability TEXT NOT NULL,
    correct INTEGER CHECK(correct IN (0, 1)),
    helped INTEGER NOT NULL CHECK(helped IN (0, 1)),
    fresh INTEGER NOT NULL CHECK(fresh IN (0, 1)),
    method TEXT,
    evidence JSON NOT NULL CHECK(json_valid(evidence)),
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    UNIQUE(run_ref, question_index)
);
CREATE INDEX idx_learning_observations_course ON learning_observations(course_id);
CREATE INDEX idx_learning_observations_question ON learning_observations(course_id, fingerprint);

CREATE TABLE learning_experiments (
    experiment_id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    message_ref UUID NOT NULL,
    topic TEXT NOT NULL,
    capability TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    proposed_check TEXT NOT NULL,
    evidence JSON NOT NULL CHECK(json_valid(evidence)),
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK(status IN ('proposed','cooldown','resolved','retired')),
    checks INTEGER NOT NULL DEFAULT 0,
    next_check_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    UNIQUE(course_id, message_ref, topic, capability)
);

-- CORE observations cross course boundaries and survive course purges.
CREATE TABLE core_method_observations (
    observation_id UUID PRIMARY KEY,
    course_ref TEXT NOT NULL,
    method TEXT NOT NULL,
    correct INTEGER CHECK(correct IN (0, 1)),
    helped INTEGER NOT NULL CHECK(helped IN (0, 1)),
    fresh INTEGER NOT NULL CHECK(fresh IN (0, 1)),
    evidence JSON NOT NULL CHECK(json_valid(evidence)),
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
