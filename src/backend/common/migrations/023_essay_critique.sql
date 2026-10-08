-- Essay critique settings live on the work session so the library, the
-- companion, and the Office pane share one harshness and one essay kind.
ALTER TABLE work_sessions ADD COLUMN critic_score INTEGER NOT NULL DEFAULT 50
    CHECK (critic_score BETWEEN 10 AND 100);
ALTER TABLE work_sessions ADD COLUMN essay_genre TEXT NOT NULL DEFAULT 'argumentative'
    CHECK (essay_genre IN (
        'argumentative', 'analytical', 'research', 'comparative',
        'creative', 'reflective', 'rhetorical'
    ));
