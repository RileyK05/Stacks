# Open design decisions (recorded 2026-10-07)

Four product decisions with real tradeoffs, carried over when the working
documents were retired. Each is **open** — no selection has been made. Decide
before the relevant feature is finalized; until then the current behavior stands.

## B-04 — Local runner scheduling

One llama-server switches models under a lock while generation HTTP runs outside
that lock. Changing models can interrupt a request; status/stop may wait through
startup. A runner lease and queue fit the 8 GB floor but add waiting/reloads.
Concurrent runners improve overlap but require RAM limits and eviction.
**Recommendation:** one runner with foreground priority, optional concurrency later.
Before selecting cancellation/shutdown behavior, reproduce competing
foreground/background calls and stop-during-load. No scheduler is implemented yet.

## B-05 — Office pairing and integration authority

Native export selection is decided: the shell opens Save, confirms replacement and
writes the selected file. The backend rejects caller-supplied write paths and
provides rendered cited bytes; browser development exports use exclusively reserved
names in the configured export folder.

**Open:** authenticated one-time Office pairing and grants for opening selected
Office documents. Custom local/LAN model URLs and opening chosen Office files are
intended capabilities. Optional Office authentication exists; a launch token does
not promise isolation from every program running as the same OS user. Choose an
Office pairing policy.

## B-14 — Backup fidelity

Full/partial/heavy tiers currently choose retained categories; ZIP compression
preserves retained content exactly. Willingness to lose detail in reduced tiers is
already authorized. **Open:** which source representations may lose detail while
exact passages/locators remain recoverable. Lossy downsampling can discard visual
evidence; compressing memory into summaries can discard history. No lossy source
rewriting has been added.

## C-63 — Cloud budget semantics

Budget checks are currently a soft stop between requests, not reservations:
concurrent in-flight calls can overshoot the remaining allowance. Usage includes
empty, truncated and reasoning-retry responses; local traffic is classified
separately. Missing-usage reporting is fixed in code (migration 022); historical
rows cannot be retrospectively verified without independent provider evidence.

**Open:** whether a hard ceiling is required. A hard cap needs token reservations
and rules for missing/late provider usage (added cost/queuing). Do not describe the
present soft stop as a strict spending cap.

## B-15 — Retrieval cutoff: top-k vs score floor

Retrieval now merges every seam through one step and can rerank in two modes
(`[rerank] mode` in `configs/retrieval.toml`). `top_k` (the shipped default)
keeps the fused order trimmed to `generation_k`, with a minimum of one slot per
contributing source. `score` scores the whole wide pool with the cross-encoder
and keeps what clears an absolute floor `min_score` and a relative floor
`max_drop` below the best, so a query the material cannot answer can return
nothing instead of the least-bad passages. Explicit-address routing pins a named
label ("Table 2.2") and filters a named week to its source regardless of mode.

**Open:** which mode ships by default, and the floor values. A fixed-count cut
cannot express "nothing here is relevant", which is what the round-5 false
refusals (STK-025/044, STK-039) need; but a floor that is too high turns real
answers into refusals. The plan (`docs/plan-score-retrieval.md`) requires the
floor to be calibrated on the user's own course with
`scripts/calibrate_rerank.py` and the answer-level tester before the default
changes. Until then `score` is opt-in and `top_k` stays the fallback.

**Recommendation:** adopt `score` after calibration if it beats `top_k` on
precision and `empty_correct` without losing recall on the label cases; record
the two runs' numbers here when the default flips.
