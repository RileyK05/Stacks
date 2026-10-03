ALTER TABLE graph_edges ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'legacy';
DELETE FROM graph_edges WHERE algorithm_version = 'legacy';

CREATE TRIGGER passage_parent_update
BEFORE UPDATE OF container_id, source_id, revision, char_start, char_end ON chunks
WHEN NEW.container_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM passage_containers AS parent
    WHERE parent.container_id = NEW.container_id AND parent.source_id = NEW.source_id
      AND parent.revision = NEW.revision
      AND parent.char_start <= NEW.char_start AND parent.char_end >= NEW.char_end
)
BEGIN SELECT RAISE(ABORT, 'invalid passage parent'); END;

CREATE TRIGGER passage_window_span_insert BEFORE INSERT ON passage_windows
WHEN NEW.char_end > (SELECT length(text) FROM chunks WHERE chunk_id = NEW.chunk_id)
BEGIN SELECT RAISE(ABORT, 'window exceeds its passage'); END;

CREATE TRIGGER graph_edge_course_insert BEFORE INSERT ON graph_edges
WHEN NOT EXISTS (
    SELECT 1 FROM chunks a JOIN sources sa ON sa.source_id = a.source_id
    JOIN chunks b ON b.chunk_id = NEW.chunk_b
    JOIN sources sb ON sb.source_id = b.source_id
    WHERE a.chunk_id = NEW.chunk_a
      AND sa.course_id = NEW.course_id AND sb.course_id = NEW.course_id
)
BEGIN SELECT RAISE(ABORT, 'graph edge crosses course scope'); END;
