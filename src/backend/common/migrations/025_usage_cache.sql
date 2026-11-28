-- Input tokens a provider served from, or wrote to, its prompt cache
-- (common/prompt_cache.py). They are already part of input_tokens; kept
-- apart so Settings can show what caching saved.
ALTER TABLE usage_ledger ADD COLUMN cache_read_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE usage_ledger ADD COLUMN cache_write_tokens INTEGER NOT NULL DEFAULT 0;
