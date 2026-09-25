-- Answer cache (docs/plan-local-first.md §6 item 11): an identical plain
-- question on an unchanged course, answered by the same model under the
-- same prompts and retrieval settings, returns the stored answer instead
-- of spending another (possibly long, on a laptop) generation.
--
-- `cache_key` hashes every input that shapes the answer, including the
-- course's content fingerprint, so a changed course simply stops hitting;
-- rows whose fingerprint is stale are deleted when the next answer for the
-- course is stored. The answer's trace is reused for its citations, and
-- deleting either the course or the trace removes the row.
CREATE TABLE answer_cache (
    cache_key     TEXT PRIMARY KEY,
    course_id     UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    fingerprint   TEXT NOT NULL,
    trace_id      UUID NOT NULL
                  REFERENCES retrieval_traces (trace_id) ON DELETE CASCADE,
    answer_text   TEXT NOT NULL,
    chunk_ids     JSON NOT NULL CHECK (json_valid(chunk_ids)),
    model         TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL
                  DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX idx_answer_cache_course ON answer_cache (course_id);
CREATE INDEX idx_answer_cache_trace ON answer_cache (trace_id);
