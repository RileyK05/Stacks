CREATE TABLE practice_help (
    help_id UUID PRIMARY KEY,
    suite_id UUID NOT NULL REFERENCES practice_suites(suite_id) ON DELETE CASCADE,
    run_ref UUID NOT NULL,
    question_index INTEGER NOT NULL CHECK(question_index >= 0),
    kind TEXT NOT NULL CHECK(kind IN ('hint', 'explain')),
    context_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('pending', 'ready', 'failed')),
    claim UUID NOT NULL,
    content JSON NOT NULL CHECK(json_valid(content)),
    model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    fell_back_to_local INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    UNIQUE(suite_id, run_ref, question_index, kind, context_key)
);
CREATE TABLE practice_feedback (
    suite_id UUID NOT NULL REFERENCES practice_suites(suite_id) ON DELETE CASCADE,
    question_index INTEGER NOT NULL CHECK(question_index >= 0),
    target TEXT NOT NULL CHECK(target IN ('question', 'hint', 'explain')),
    help_id UUID REFERENCES practice_help(help_id) ON DELETE CASCADE,
    rating TEXT NOT NULL CHECK(rating IN ('good', 'bad')),
    reason TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    PRIMARY KEY(suite_id, question_index, target),
    CHECK((target = 'question' AND help_id IS NULL) OR (target != 'question' AND help_id IS NOT NULL))
);
