-- 027_chunk_embeddings_model_index.sql
-- The embedding seam filters chunk_embeddings by model on every query
-- (a course can hold rows from more than one model across a model swap),
-- but 025 created the table with only its chunk_id primary key. Without
-- this index the seam scans every embedding row in the table before the
-- per-course join can narrow it.
-- Its own migration because 025 is already applied (never edit an applied
-- migration).

CREATE INDEX idx_chunk_embeddings_model ON chunk_embeddings(model);
