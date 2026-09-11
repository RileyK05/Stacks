-- 022_ingestion_spend_pool.sql
-- Splits the weekly token budget into two pools: generation (tutor answers,
-- probes, artifacts) and ingestion (TOC updates, course-knowledge
-- extraction). An ingestion upload can therefore never drain the budget a
-- user needs for interactive answers. Historical rows default to
-- 'generation' because pre-split spend was overwhelmingly generation; the
-- ingestion tasks were ratified but never wired to real calls (2026-09-11).

ALTER TABLE generation_ledger
    ADD COLUMN spend_kind TEXT NOT NULL DEFAULT 'generation'
        CONSTRAINT generation_ledger_spend_kind_known
        CHECK (spend_kind IN ('generation', 'ingestion'));