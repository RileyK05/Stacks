-- 023_extracted_text.sql
-- Extracted text lives beside the source row so retrieval never needs the
-- original binary (raw files stay on disk untouched; nothing is destroyed
-- at ingest). Written by the extract_text stage; NULL until then.

ALTER TABLE sources ADD COLUMN extracted_text TEXT;