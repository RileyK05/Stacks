-- 001_init.sql
-- Initial schema for the Course Memory and Adaptive Study System.
-- Mirrors src/backend/common/schemas/ (see system.md section 2).
-- Enums first, then tables in dependency order.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================
-- Enums
-- =============================================================

CREATE TYPE source_type AS ENUM (
    'syllabus', 'slides', 'textbook', 'problem_set', 'solutions',
    'notes', 'feedback', 'exam', 'video', 'audio', 'code'
);

CREATE TYPE source_status AS ENUM ('uploaded', 'scanned', 'indexed', 'failed');

CREATE TYPE evidence_level AS ENUM ('direct', 'derived', 'hypothesis');

CREATE TYPE memory_object_kind AS ENUM (
    'concept', 'formula', 'theorem', 'example',
    'misconception', 'assessment_item'
);

CREATE TYPE mastery_state AS ENUM (
    'unseen', 'exposed', 'can_recognize', 'can_reproduce_with_cues',
    'can_apply_independently', 'can_transfer'
);

CREATE TYPE error_category AS ENUM (
    'definition', 'notation', 'assumption',
    'application', 'calculation', 'incomplete'
);

CREATE TYPE prereq_kind AS ENUM ('in_course', 'external');

CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');

-- =============================================================
-- Identity & course structure
-- =============================================================

CREATE TABLE users (
    user_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE courses (
    course_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(user_id),
    code        TEXT NOT NULL,
    name        TEXT NOT NULL
);

CREATE TABLE study_periods (
    period_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id   UUID NOT NULL REFERENCES courses(course_id),
    label       TEXT NOT NULL,
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL
);

CREATE TABLE course_objects (
    object_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id   UUID NOT NULL REFERENCES courses(course_id),
    user_id     UUID NOT NULL REFERENCES users(user_id),
    kind        TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content_uri TEXT,
    content     JSONB,
    origin      TEXT,
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT course_object_content_or_uri CHECK (
        content_uri IS NOT NULL OR content IS NOT NULL
    )
);

-- =============================================================
-- Source content
-- =============================================================

CREATE TABLE sources (
    source_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(user_id),
    course_id    UUID NOT NULL REFERENCES courses(course_id),
    filename     TEXT NOT NULL,
    mime_type    TEXT NOT NULL,
    source_type  source_type NOT NULL,
    version      TEXT,
    uri          TEXT,
    status       source_status NOT NULL DEFAULT 'uploaded',
    file_hash    TEXT,
    error_message TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE locators (
    locator_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id    UUID NOT NULL REFERENCES sources(source_id),
    locator_type TEXT NOT NULL,
    start        TEXT NOT NULL,
    end_value    TEXT,
    label        TEXT NOT NULL,
    description  TEXT
);

CREATE TABLE chunks (
    chunk_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id    UUID NOT NULL REFERENCES sources(source_id),
    locator_id   UUID NOT NULL REFERENCES locators(locator_id),
    chunk_index  INTEGER NOT NULL,
    text         TEXT NOT NULL
);

-- =============================================================
-- Course memory
-- =============================================================

CREATE TABLE concepts (
    concept_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id       UUID NOT NULL REFERENCES courses(course_id),
    name            TEXT NOT NULL,
    definition      TEXT NOT NULL,
    synonyms        JSONB NOT NULL DEFAULT '[]',
    evidence_level  evidence_level NOT NULL DEFAULT 'derived'
);

CREATE TABLE dependencies (
    dep_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prereq_id     UUID REFERENCES concepts(concept_id),
    dependent_id  UUID NOT NULL REFERENCES concepts(concept_id),
    prereq_kind   prereq_kind NOT NULL DEFAULT 'in_course',
    external_ref  TEXT
);

CREATE TABLE memory_objects (
    memory_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id      UUID NOT NULL REFERENCES concepts(concept_id),
    source_id       UUID NOT NULL REFERENCES sources(source_id),
    kind            memory_object_kind NOT NULL,
    content         TEXT NOT NULL,
    evidence_level  evidence_level NOT NULL DEFAULT 'derived'
);

CREATE TABLE tables_of_contents (
    toc_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id   UUID NOT NULL REFERENCES courses(course_id),
    version     INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tables_of_contents_course_version UNIQUE (course_id, version)
);

CREATE TABLE toc_entries (
    entry_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    toc_id      UUID NOT NULL REFERENCES tables_of_contents(toc_id),
    source_id   UUID NOT NULL REFERENCES sources(source_id),
    locator_id  UUID REFERENCES locators(locator_id),
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    concepts    JSONB NOT NULL DEFAULT '[]',
    position    INTEGER NOT NULL DEFAULT 0
);

-- =============================================================
-- Student model
-- =============================================================

CREATE TABLE assessment_items (
    item_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id   UUID NOT NULL REFERENCES courses(course_id),
    concepts    JSONB NOT NULL DEFAULT '[]',
    source_id   UUID REFERENCES sources(source_id),
    prompt      TEXT NOT NULL,
    solution    TEXT,
    difficulty  INTEGER NOT NULL DEFAULT 1 CHECK (difficulty BETWEEN 1 AND 5),
    rubric      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE attempts (
    attempt_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(user_id),
    course_id         UUID NOT NULL REFERENCES courses(course_id),
    item_id           UUID NOT NULL REFERENCES assessment_items(item_id),
    concept_ids       JSONB NOT NULL DEFAULT '[]',
    chunk_id          UUID REFERENCES chunks(chunk_id),
    answer            TEXT NOT NULL,
    confidence_before INTEGER NOT NULL CHECK (confidence_before BETWEEN 0 AND 100),
    evaluation        TEXT NOT NULL,
    score             INTEGER CHECK (score BETWEEN 0 AND 100),
    error_category    error_category,
    used_help         BOOLEAN NOT NULL DEFAULT FALSE,
    time_spent        INTEGER,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE concept_mastery (
    mastery_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(user_id),
    concept_id  UUID NOT NULL REFERENCES concepts(concept_id),
    state       mastery_state NOT NULL DEFAULT 'unseen',
    confidence  INTEGER CHECK (confidence BETWEEN 0 AND 100),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT concept_mastery_user_concept UNIQUE (user_id, concept_id)
);

CREATE TABLE recommendations (
    recommendation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(user_id),
    course_id         UUID NOT NULL REFERENCES courses(course_id),
    concept_id        UUID NOT NULL REFERENCES concepts(concept_id),
    reason            TEXT NOT NULL,
    source            TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================
-- Chat history
-- =============================================================

CREATE TABLE conversations (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(user_id),
    course_id       UUID NOT NULL REFERENCES courses(course_id),
    title           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversation_turns (
    turn_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(conversation_id),
    role            message_role NOT NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chat_summaries (
    summary_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(conversation_id),
    summary         TEXT NOT NULL,
    version         INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================
-- Evidence & provenance
-- =============================================================

CREATE TABLE retrieval_traces (
    trace_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID NOT NULL REFERENCES users(user_id),
    course_id             UUID NOT NULL REFERENCES courses(course_id),
    conversation_id       UUID REFERENCES conversations(conversation_id),
    query                 TEXT NOT NULL,
    retrieved_chunk_ids   JSONB NOT NULL DEFAULT '[]',
    retrieved_toc_entry_ids JSONB NOT NULL DEFAULT '[]',
    model                 TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE responses (
    response_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(conversation_id),
    turn_id         UUID REFERENCES conversation_turns(turn_id),
    trace_id        UUID REFERENCES retrieval_traces(trace_id),
    content         TEXT NOT NULL,
    model           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE claims (
    claim_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_id UUID NOT NULL REFERENCES responses(response_id),
    claim_type  TEXT NOT NULL,
    text        TEXT NOT NULL
);

CREATE TABLE citations (
    citation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id    UUID NOT NULL REFERENCES claims(claim_id),
    target_type TEXT NOT NULL,
    target_id   UUID NOT NULL,
    trace_id    UUID REFERENCES retrieval_traces(trace_id)
);

CREATE TABLE memory_object_evidence (
    evidence_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id       UUID NOT NULL REFERENCES memory_objects(memory_id),
    chunk_id        UUID NOT NULL REFERENCES chunks(chunk_id),
    evidence_level  evidence_level NOT NULL DEFAULT 'direct'
);

CREATE TABLE artifact_origins (
    artifact_id     UUID PRIMARY KEY REFERENCES course_objects(object_id),
    source_ids      JSONB NOT NULL DEFAULT '[]',
    concept_ids     JSONB NOT NULL DEFAULT '[]',
    model           TEXT,
    prompt_version  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_decisions (
    record_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID NOT NULL REFERENCES sources(source_id),
    model       TEXT,
    decision    JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================
-- Indexes
-- =============================================================

CREATE INDEX idx_courses_user ON courses(user_id);
CREATE INDEX idx_sources_course ON sources(course_id);
CREATE INDEX idx_locators_source ON locators(source_id);
CREATE INDEX idx_chunks_source ON chunks(source_id);
CREATE INDEX idx_chunks_locator ON chunks(locator_id);
CREATE INDEX idx_concepts_course ON concepts(course_id);
CREATE INDEX idx_memory_objects_concept ON memory_objects(concept_id);
CREATE INDEX idx_memory_objects_source ON memory_objects(source_id);
CREATE INDEX idx_toc_entries_toc ON toc_entries(toc_id);
CREATE INDEX idx_attempts_user ON attempts(user_id);
CREATE INDEX idx_attempts_item ON attempts(item_id);
CREATE INDEX idx_attempts_concept ON attempts USING GIN (concept_ids);
CREATE INDEX idx_concept_mastery_user ON concept_mastery(user_id);
CREATE INDEX idx_concept_mastery_concept ON concept_mastery(concept_id);
CREATE INDEX idx_conversations_user ON conversations(user_id);
CREATE INDEX idx_turns_conversation ON conversation_turns(conversation_id);
CREATE INDEX idx_responses_conversation ON responses(conversation_id);
CREATE INDEX idx_claims_response ON claims(response_id);
CREATE INDEX idx_citations_claim ON citations(claim_id);

-- Hot-path FK indexes (Postgres does not auto-index FKs)
CREATE INDEX idx_memory_object_evidence_memory ON memory_object_evidence(memory_id);
CREATE INDEX idx_memory_object_evidence_chunk ON memory_object_evidence(chunk_id);
CREATE INDEX idx_dependencies_dependent ON dependencies(dependent_id);
CREATE INDEX idx_responses_trace ON responses(trace_id);
CREATE INDEX idx_chat_summaries_conversation ON chat_summaries(conversation_id);
CREATE INDEX idx_attempts_course ON attempts(course_id);

-- Dedup check on ingest: course + file hash
CREATE INDEX idx_sources_course_hash ON sources(course_id, file_hash);
