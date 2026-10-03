-- `chunks` remains the one authoritative passage table. Its historical name
-- and IDs keep saved citations readable; windows never copy passage text.
CREATE TABLE source_indexes (
    source_id UUID PRIMARY KEY REFERENCES sources(source_id) ON DELETE CASCADE,
    revision TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    extraction_version TEXT NOT NULL,
    segmentation_version TEXT NOT NULL,
    semantic_used INTEGER NOT NULL CHECK (semantic_used IN (0, 1)),
    warning TEXT,
    published_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z', 'now'))
);
INSERT INTO source_indexes
    (source_id, revision, file_hash, extraction_version, segmentation_version, semantic_used)
SELECT source_id, 'legacy:' || COALESCE(file_hash, ''), COALESCE(file_hash, ''),
       'legacy', 'legacy', 0
FROM sources WHERE status = 'indexed';

CREATE TABLE passage_containers (
    container_id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    revision TEXT NOT NULL,
    parent_id UUID REFERENCES passage_containers(container_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level >= 0),
    char_start INTEGER NOT NULL CHECK (char_start >= 0),
    char_end INTEGER NOT NULL CHECK (char_end > char_start),
    UNIQUE(source_id, revision, char_start, level)
);
CREATE INDEX idx_passage_containers_parent ON passage_containers(parent_id);

CREATE TRIGGER passage_container_parent_insert BEFORE INSERT ON passage_containers
WHEN NEW.parent_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM passage_containers AS parent
    WHERE parent.container_id = NEW.parent_id
      AND parent.source_id = NEW.source_id AND parent.revision = NEW.revision
      AND parent.level < NEW.level
      AND parent.char_start <= NEW.char_start AND parent.char_end >= NEW.char_end
)
BEGIN SELECT RAISE(ABORT, 'invalid passage container parent'); END;

CREATE TRIGGER passage_container_immutable BEFORE UPDATE ON passage_containers
BEGIN SELECT RAISE(ABORT, 'replace passage containers during publication'); END;

ALTER TABLE chunks ADD COLUMN container_id UUID REFERENCES passage_containers(container_id);
ALTER TABLE chunks ADD COLUMN revision TEXT;
ALTER TABLE chunks ADD COLUMN char_start INTEGER;
ALTER TABLE chunks ADD COLUMN char_end INTEGER;
ALTER TABLE chunks ADD COLUMN unit_kind TEXT NOT NULL DEFAULT 'passage';
ALTER TABLE chunks ADD COLUMN boundary TEXT NOT NULL DEFAULT 'legacy';
CREATE INDEX idx_chunks_container_order ON chunks(container_id, chunk_index);

CREATE TRIGGER passage_parent_insert BEFORE INSERT ON chunks
WHEN NEW.container_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM passage_containers AS parent
    WHERE parent.container_id = NEW.container_id AND parent.source_id = NEW.source_id
      AND parent.revision = NEW.revision
      AND parent.char_start <= NEW.char_start AND parent.char_end >= NEW.char_end
)
BEGIN SELECT RAISE(ABORT, 'invalid passage parent'); END;

CREATE TABLE passage_windows (
    window_id UUID PRIMARY KEY,
    chunk_id UUID NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    char_start INTEGER NOT NULL CHECK (char_start >= 0),
    char_end INTEGER NOT NULL CHECK (char_end > char_start),
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    embedding BLOB NOT NULL,
    text_hash TEXT NOT NULL,
    UNIQUE(chunk_id, char_start, char_end, model),
    CHECK (length(embedding) = dimension * 4)
);
CREATE INDEX idx_passage_windows_chunk ON passage_windows(chunk_id);

-- Old indexed sources remain searchable until their replacement publishes.
-- No destructive conversion or learner-data write occurs in this migration.
