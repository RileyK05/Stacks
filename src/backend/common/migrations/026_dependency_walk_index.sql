-- 026_dependency_walk_index.sql
-- The dependency-walk seam (decision 008) walks both directions of every
-- dependency edge; the prereq_id side had no index (001 only indexed
-- dependent_id). Added in its own migration because 025 was already applied.

CREATE INDEX idx_dependencies_prereq ON dependencies(prereq_id);
