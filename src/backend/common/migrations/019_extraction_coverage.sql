-- Per-source page coverage from extraction (blank pages, garbled text
-- layers, and how many of those OCR later replaced). NULL on an index
-- published before this migration: the counts are unknown until reindex.
ALTER TABLE source_indexes ADD COLUMN pages_total INTEGER;
ALTER TABLE source_indexes ADD COLUMN pages_empty INTEGER;
ALTER TABLE source_indexes ADD COLUMN pages_low_quality INTEGER;
ALTER TABLE source_indexes ADD COLUMN pages_ocr INTEGER;
