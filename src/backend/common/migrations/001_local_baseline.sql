-- 001_local_baseline.sql
-- Local-first baseline (docs/plan-local-first.md §8). One user per
-- database file: no users, accounts, tiers, enrollment, or sharing
-- tables. Every foreign key cascades, so deleting a course is one
-- statement and can never strand derived rows.
--
-- Type conventions (decoded by common/db.py via declared types):
--   UUID       TEXT holding a canonical UUID string
--   TIMESTAMP  TEXT, UTC ISO-8601 with microseconds: 2026-09-25T10:00:00.123456Z
--              (fixed width, so lexicographic order == time order)
--   JSON       TEXT holding valid JSON
--   BLOB       little-endian float32 vectors (chunk_embeddings)

CREATE TABLE courses (
    course_id    UUID PRIMARY KEY,
    name         TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    created_at   TIMESTAMP NOT NULL
                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    -- Trash: a deleted course keeps its rows until purge_after, and can
    -- be restored until then. Both set or both NULL.
    deleted_at   TIMESTAMP,
    purge_after  TIMESTAMP,
    CHECK ((deleted_at IS NULL) = (purge_after IS NULL))
);
CREATE INDEX idx_courses_purge ON courses (purge_after)
    WHERE purge_after IS NOT NULL;

CREATE TABLE sources (
    source_id        UUID PRIMARY KEY,
    course_id        UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    filename         TEXT NOT NULL,
    mime_type        TEXT NOT NULL,
    source_type      TEXT NOT NULL CHECK (source_type IN (
                         'syllabus', 'slides', 'textbook', 'problem_set',
                         'solutions', 'notes', 'feedback', 'exam', 'video',
                         'audio', 'code')),
    version          TEXT,
    uri              TEXT,
    status           TEXT NOT NULL DEFAULT 'uploaded'
                     CHECK (status IN ('uploaded', 'scanned', 'indexed', 'failed')),
    file_hash        TEXT,
    error_message    TEXT,
    created_at       TIMESTAMP NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    size_bytes       INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    stored_encoding  TEXT CHECK (stored_encoding IS NULL
                                 OR stored_encoding IN ('identity', 'gzip'))
);
CREATE INDEX idx_sources_course ON sources (course_id);
CREATE UNIQUE INDEX uq_sources_course_hash ON sources (course_id, file_hash)
    WHERE file_hash IS NOT NULL;

CREATE TABLE locators (
    locator_id    UUID PRIMARY KEY,
    source_id     UUID NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    locator_type  TEXT NOT NULL,
    start         TEXT NOT NULL,
    end_value     TEXT,
    label         TEXT NOT NULL,
    description   TEXT
);
CREATE INDEX idx_locators_source ON locators (source_id);

-- chunk_rowid is the stable INTEGER PRIMARY KEY the FTS5 index keys on:
-- an implicit rowid may be renumbered by VACUUM, which would silently
-- desynchronize an external-content FTS table.
CREATE TABLE chunks (
    chunk_rowid  INTEGER PRIMARY KEY,
    chunk_id     UUID NOT NULL UNIQUE,
    source_id    UUID NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    locator_id   UUID NOT NULL REFERENCES locators (locator_id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    text         TEXT NOT NULL,
    UNIQUE (source_id, chunk_index)
);
CREATE INDEX idx_chunks_locator ON chunks (locator_id);

-- Keyword seam (decision 008): porter-stemmed full text over chunks.
CREATE VIRTUAL TABLE chunks_fts USING fts5 (
    text,
    content = 'chunks',
    content_rowid = 'chunk_rowid',
    tokenize = 'porter unicode61 remove_diacritics 2'
);
CREATE TRIGGER chunks_fts_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts (rowid, text) VALUES (new.chunk_rowid, new.text);
END;
CREATE TRIGGER chunks_fts_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text)
    VALUES ('delete', old.chunk_rowid, old.text);
END;
CREATE TRIGGER chunks_fts_update AFTER UPDATE OF text ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text)
    VALUES ('delete', old.chunk_rowid, old.text);
    INSERT INTO chunks_fts (rowid, text) VALUES (new.chunk_rowid, new.text);
END;

-- One row per LOGICAL chunk; the full locator span is the citation map.
CREATE TABLE chunk_locators (
    chunk_id    UUID NOT NULL REFERENCES chunks (chunk_id) ON DELETE CASCADE,
    locator_id  UUID NOT NULL REFERENCES locators (locator_id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, locator_id)
);

-- One row per chunk keyed by model name: a model swap orphans old rows
-- (filtered out by model) instead of mixing vector spaces.
CREATE TABLE chunk_embeddings (
    chunk_id    UUID PRIMARY KEY REFERENCES chunks (chunk_id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    dimension   INTEGER NOT NULL CHECK (dimension > 0),
    embedding   BLOB NOT NULL CHECK (length(embedding) = dimension * 4),
    created_at  TIMESTAMP NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX idx_chunk_embeddings_model ON chunk_embeddings (model);

CREATE TABLE ingestion_runs (
    run_id            UUID PRIMARY KEY,
    source_id         UUID NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    pipeline_version  TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    configuration     JSON NOT NULL DEFAULT '{}' CHECK (json_valid(configuration)),
    error_message     TEXT,
    created_at        TIMESTAMP NOT NULL
                      DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    started_at        TIMESTAMP,
    completed_at      TIMESTAMP
);
CREATE INDEX idx_ingestion_runs_source ON ingestion_runs (source_id);

CREATE TABLE ingestion_stage_runs (
    stage_run_id         UUID PRIMARY KEY,
    run_id               UUID NOT NULL REFERENCES ingestion_runs (run_id) ON DELETE CASCADE,
    stage                TEXT NOT NULL,
    position             INTEGER NOT NULL CHECK (position >= 0),
    depends_on_stage_id  UUID REFERENCES ingestion_stage_runs (stage_run_id)
                         ON DELETE CASCADE,
    status               TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    attempt_count        INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts         INTEGER NOT NULL DEFAULT 2 CHECK (max_attempts >= 1),
    handler_version      TEXT NOT NULL,
    configuration        JSON NOT NULL DEFAULT '{}' CHECK (json_valid(configuration)),
    error_message        TEXT,
    started_at           TIMESTAMP,
    completed_at         TIMESTAMP,
    CHECK (attempt_count <= max_attempts),
    UNIQUE (run_id, stage),
    UNIQUE (run_id, position)
);

-- The ingestion queue. Claims are persistent state transitions
-- (claimed_at), heartbeat-fenced so a laptop that slept or crashed
-- mid-run releases its claim instead of stranding the source.
CREATE TABLE pending_ingestion (
    source_id         UUID PRIMARY KEY REFERENCES sources (source_id) ON DELETE CASCADE,
    course_id         UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    reason            TEXT NOT NULL,
    created_at        TIMESTAMP NOT NULL
                      DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    claimed_at        TIMESTAMP,
    claimed_runs      INTEGER NOT NULL DEFAULT 0 CHECK (claimed_runs >= 0),
    claimed_runs_max  INTEGER NOT NULL DEFAULT 5,
    heartbeat_at      TIMESTAMP
);
CREATE INDEX idx_pending_ingestion_course ON pending_ingestion (course_id);

CREATE TABLE ingestion_history (
    history_id  UUID PRIMARY KEY,
    source_id   UUID NOT NULL,
    course_id   UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    reason      TEXT NOT NULL,
    queued_at   TIMESTAMP NOT NULL,
    cleared_at  TIMESTAMP NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX idx_ingestion_history_course ON ingestion_history (course_id);

-- Course knowledge (decision 007): what the course SAYS.
CREATE TABLE concepts (
    concept_id      UUID PRIMARY KEY,
    course_id       UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    definition      TEXT NOT NULL,
    synonyms        JSON NOT NULL DEFAULT '[]' CHECK (json_valid(synonyms)),
    evidence_level  TEXT NOT NULL DEFAULT 'derived'
                    CHECK (evidence_level IN ('direct', 'derived', 'hypothesis'))
);
CREATE INDEX idx_concepts_course ON concepts (course_id);

CREATE TABLE dependencies (
    dep_id        UUID PRIMARY KEY,
    prereq_id     UUID REFERENCES concepts (concept_id) ON DELETE CASCADE,
    dependent_id  UUID NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    prereq_kind   TEXT NOT NULL DEFAULT 'in_course'
                  CHECK (prereq_kind IN ('in_course', 'external')),
    external_ref  TEXT
);
CREATE INDEX idx_dependencies_prereq ON dependencies (prereq_id);
CREATE INDEX idx_dependencies_dependent ON dependencies (dependent_id);

CREATE TABLE memory_objects (
    memory_id       UUID PRIMARY KEY,
    concept_id      UUID NOT NULL REFERENCES concepts (concept_id) ON DELETE CASCADE,
    source_id       UUID NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN (
                        'concept', 'formula', 'theorem', 'example',
                        'misconception', 'assessment_item')),
    content         TEXT NOT NULL,
    evidence_level  TEXT NOT NULL DEFAULT 'derived'
                    CHECK (evidence_level IN ('direct', 'derived', 'hypothesis'))
);
CREATE INDEX idx_memory_objects_concept ON memory_objects (concept_id);
CREATE INDEX idx_memory_objects_source ON memory_objects (source_id);

CREATE TABLE memory_object_evidence (
    evidence_id     UUID PRIMARY KEY,
    memory_id       UUID NOT NULL REFERENCES memory_objects (memory_id) ON DELETE CASCADE,
    chunk_id        UUID NOT NULL REFERENCES chunks (chunk_id) ON DELETE CASCADE,
    evidence_level  TEXT NOT NULL DEFAULT 'direct'
                    CHECK (evidence_level IN ('direct', 'derived', 'hypothesis'))
);
CREATE INDEX idx_memory_object_evidence_memory ON memory_object_evidence (memory_id);
CREATE INDEX idx_memory_object_evidence_chunk ON memory_object_evidence (chunk_id);

CREATE TABLE tables_of_contents (
    toc_id      UUID PRIMARY KEY,
    course_id   UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    created_at  TIMESTAMP NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    UNIQUE (course_id, version)
);

CREATE TABLE toc_entries (
    entry_rowid  INTEGER PRIMARY KEY,
    entry_id     UUID NOT NULL UNIQUE,
    toc_id       UUID NOT NULL REFERENCES tables_of_contents (toc_id) ON DELETE CASCADE,
    source_id    UUID NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    locator_id   UUID REFERENCES locators (locator_id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    concepts     JSON NOT NULL DEFAULT '[]' CHECK (json_valid(concepts)),
    position     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_toc_entries_toc ON toc_entries (toc_id);

-- TOC seam: same stemming as the keyword seam over title + description.
CREATE VIRTUAL TABLE toc_entries_fts USING fts5 (
    title,
    description,
    content = 'toc_entries',
    content_rowid = 'entry_rowid',
    tokenize = 'porter unicode61 remove_diacritics 2'
);
CREATE TRIGGER toc_entries_fts_insert AFTER INSERT ON toc_entries BEGIN
    INSERT INTO toc_entries_fts (rowid, title, description)
    VALUES (new.entry_rowid, new.title, new.description);
END;
CREATE TRIGGER toc_entries_fts_delete AFTER DELETE ON toc_entries BEGIN
    INSERT INTO toc_entries_fts (toc_entries_fts, rowid, title, description)
    VALUES ('delete', old.entry_rowid, old.title, old.description);
END;
CREATE TRIGGER toc_entries_fts_update AFTER UPDATE OF title, description
ON toc_entries BEGIN
    INSERT INTO toc_entries_fts (toc_entries_fts, rowid, title, description)
    VALUES ('delete', old.entry_rowid, old.title, old.description);
    INSERT INTO toc_entries_fts (rowid, title, description)
    VALUES (new.entry_rowid, new.title, new.description);
END;

-- Golden rule 2: every retrieval stores what was retrieved and why.
CREATE TABLE retrieval_traces (
    trace_id                 UUID PRIMARY KEY,
    course_id                UUID NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    query                    TEXT NOT NULL,
    retrieved_chunk_ids      JSON NOT NULL DEFAULT '{}'
                             CHECK (json_valid(retrieved_chunk_ids)),
    retrieved_toc_entry_ids  JSON NOT NULL DEFAULT '[]'
                             CHECK (json_valid(retrieved_toc_entry_ids)),
    model                    TEXT,
    created_at               TIMESTAMP NOT NULL
                             DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX idx_retrieval_traces_course ON retrieval_traces (course_id);

-- Usage ledger (plan §7.4): real token counts from each response's usage
-- field, per task and provider. Informational locally; an optional
-- user-set budget reads it for paid providers.
CREATE TABLE usage_ledger (
    ledger_id      UUID PRIMARY KEY,
    course_id      UUID REFERENCES courses (course_id) ON DELETE SET NULL,
    course_label   TEXT,
    task           TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    input_tokens   INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens  INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    created_at     TIMESTAMP NOT NULL
                   DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
CREATE INDEX idx_usage_ledger_created ON usage_ledger (created_at);

-- Course memory (decision 007): the per-course keepsake node. No FK to
-- courses on purpose — it survives the course's purge.
CREATE TABLE course_memories (
    memory_id        UUID PRIMARY KEY,
    course_id        UUID NOT NULL UNIQUE,
    course_ref       TEXT NOT NULL,
    name             TEXT NOT NULL,
    summary          TEXT NOT NULL,
    key_concepts     JSON NOT NULL DEFAULT '[]' CHECK (json_valid(key_concepts)),
    token_budget     INTEGER NOT NULL DEFAULT 1000 CHECK (token_budget > 0),
    summary_version  TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    updated_at       TIMESTAMP NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now')),
    CHECK (updated_at >= created_at)
);

-- User-changeable settings (provider mode, model choice, budget). Keys
-- never live here — they go in the OS credential store.
CREATE TABLE app_settings (
    key         TEXT PRIMARY KEY,
    value       JSON NOT NULL CHECK (json_valid(value)),
    updated_at  TIMESTAMP NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
