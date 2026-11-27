-- Required points of a written practice answer that the model credited after
-- the word matcher missed them (student_model/short_answer_judge.py), by
-- question index. Saved with the run so a stored grade never changes when it
-- is viewed again.
ALTER TABLE practice_runs ADD COLUMN judged_points JSON NOT NULL DEFAULT '{}'
    CHECK (json_valid(judged_points));
