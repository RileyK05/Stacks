# 008 — Hybrid four-seam retrieval (with dormant expansion seams)

Date: 2026-09-12
Status: Ratified (revised same day after design conversation — fusion is
mixing, not scoring; expansion seams are built up front and activate as
their data arrives)
Supersedes: the "embeddings only when the TOC path fails an eval" posture
(decision 001-era; system.md prior retrieval-evolution list). TOC-as-index
structure (system.md §2.3) unchanged.

## Context

The original plan was embeddings + a vector DB. The operator rejected it on
two grounds: (1) many similar course documents → embedding search returns
many near-duplicate hits (precision at the top of the ranking); (2) the
cascading-TOC idea fits the domain better. Fork A's conversation surfaced
the deciding case: "When did we use linearity?" — the TOC locates where a
topic is *primarily taught* but under-retrieves where it is *used*. A
single retrieval path is structurally biased toward canonical treatments.

## Decision

**Four retrieval seams, one funnel, all candidates cited.** Each seam is a
candidate generator; the funnel merges. Seams activate as their data
arrives — a seam with no data contributes nothing and breaks nothing
(build-the-seam-whenever, turn-it-on-when-real).

1. **Keyword (tsvector)** — term overlap over chunks. Works with zero model
   dependency, day one. Catches scattered mentions ("where we *used*
   linearity" in chapters 5–6).
2. **TOC regions** — question → TOC entries → chunks under those entries.
   Coarse, canonical location. Static matching (entry titles/descriptions +
   concept synonyms) first; a model-routed upgrade is a measured option.
   Dormant until entries exist (provider-gated).
3. **Dependency walk** — question → matched concept → walk
   `dependencies` edges (prereqs + dependents) → add their chunks. Built as
   a seam in v1, dormant until model-extracted edges exist AND pass an
   edge-confidence bar (only edges the extractor could cite evidence for
   are auto-walked; lower-confidence edges are flagged for review). A wrong
   edge misdirects silently, so dormant-until-trustworthy is the design,
   not an accident.
4. **Embeddings (pgvector)** — ingestion-time chunk embeddings; query time
   is vector-only. Its role is *ranking* what the first three found (plus a
   small quota of semantic-only extras), not competing scores. Gated on the
   provider pick (no-retention embedding endpoint) and on measured help.

**Funnel roles (mixing, not score-fighting):**

- TOC = scope-giver: partitions candidates by region; no cross-region score
  comparison is needed.
- Keyword = precision net: exact terminology (formulas, definitions) that
  semantic ranking may undervalue.
- Dependency walk = expansion: prerequisite/dependent context the query
  didn't name.
- Embeddings = the relevance ordering over the merged set. This avoids
  weighted-score fusion entirely — incompatible units never compete.
- Caps: per-source/per-chapter candidate caps at fusion absorb the
  near-duplicate-flood concern.

**The citation contract is the harness.** Every chunk surviving fusion
carries its locator; citations are layer-agnostic. Retrieval strategy is an
internal, swappable detail; trust lives at the citation boundary.

**Traceability:** every query stores a retrieval trace recording which
layers contributed which candidates (retrieval_traces schema already has
chunk + TOC ids; per-layer contribution is part of the trace), so layer
contributions stay inspectable.

## Measured, not assumed

- Eval set: hand-written questions in *students' voice* (messy, paraphrased,
  "when did we use X" phrasing) against a real uploaded course, with
  known-answer chunks marked. Lives in `data/eval/` (committed).
- Metric: recall@k per layer AND fused. Fusion must beat the best single
  layer or it is simplified. Each seam must beat the funnel without it, or
  it is turned off (golden rule 5 applies to combinations and to dormant
  seams being activated).
- Fusion policy (quotas, caps, k) lives in versioned configs, never
  hardcoded.

## Ship order

1. Keyword — works today.
2. TOC regions — activates when the provider lands and entries are written.
3. Dependency-walk seam — built now, dormant until trustworthy edges exist.
4. Embeddings — provider-gated; last because it is the ranking function.

## Non-decisions (open)

- Static vs model-routed TOC matching (default static, measured upgrade).
- Embedding model choice (part of the provider pick).
- Funnel quotas/caps/k values — config tunables set by measurement.