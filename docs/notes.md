# Design Notes & Open Issues

Living log of design observations, schema concerns, and deferred fixes.
Each entry is dated and tagged so it can be revisited or closed out.
If a concern is a **schema** problem, it gets a `[schema]` tag; if it is a
**non-schema** design issue, it gets a `[design]` tag. Decisions that are
resolved get moved to `docs/decisions/`.

> Nothing here is ever deleted. Resolved items are moved to **Closed** with a
> date and outcome, keeping a full log of what we decided and why.

## Open

- [empty]

## Closed

- **[schema] "Week" is too rigid.** Fixed by replacing `Week` with `StudyPeriod`
  (`period_id`, `course_id`, `label`, `start_date`, `end_date`). The window is
  user-definable (lecture, month, semester, before-exam) rather than a fixed
  week. Implemented in `schemas/identity.py`. Closed 2026-08-17.
- **[schema] `Page` and `Chunk` semantics.** Resolved to a generic **locator**
  model: object stored whole, `Locator(type, start, end, label)` as a per-format
  index ("table of contents"), and `Chunk` as a token-bounded slice pointing back
  to a locator. Citations use locator type + label. New formats = new locator
  type, no redesign. Implemented in `schemas/source_content.py`. Closed
  2026-08-17.
- **[schema] `Dependency` assumes in-course prereqs.** Fixed: `prereq_id` is now
  nullable (a concept may have no prereq), plus `prereq_kind` (`in_course` /
  `external`) and `external_ref` for out-of-course prereqs. Implemented in
  `schemas/memory.py`. Closed 2026-08-17.
- **[schema] `course_objects` storage/serving.** Split into `kind` (semantic
  purpose, free string so new kinds need no schema change), `content_type`
  (format), and `content_uri` (pointer to format-appropriate storage) + optional
  `content` dict. Implemented in `schemas/identity.py`. Closed 2026-08-17.

- **[schema] `Attempt` had no machine-readable score.** `evaluation` was free
  text only, leaving the mastery-ladder transitions nothing structured to
  consume. Added `score: float | None` (0.0–1.0, nullable so free-form attempts
  aren't forced into fake precision); `evaluation` stays as the narrative.
  Implemented in `schemas/student_model.py`. Closed 2026-08-18.
  *(Amended 2026-08-18: changed to `score: int | None`, 0–6 grade-like scale —
  0=incomplete, 1=fail, then D→A+ — matching how the student model will
  actually grade probes.)*
- **[schema] `Source` had no dedup or failure tracking.** Added `file_hash`
  (SHA-256 of file bytes, distinguishes revised upload from duplicate re-ingest
  regardless of filename) and `error_message` (populated when
  `status == failed`). Implemented in `schemas/source_content.py`. Closed
  2026-08-18.
- **[schema] `TocEntry` had no deterministic ordering.** Added
  `order_index: int = 0` so the outline can be reconstructed and re-ordered
  explicitly. A `parent_entry_id` hierarchy pointer was considered and deferred
  until something consumes it. Implemented in `schemas/memory.py`. Closed
  2026-08-18. *(Amended 2026-08-18: renamed `order_index` → `position` for
  clarity.)*
- **[schema] `Conversation` had no `updated_at`.** Added so the sidebar can sort
  by most recent activity without aggregating turn timestamps. Implemented in
  `schemas/chat.py`. Closed 2026-08-18.
- **[schema] `Concept` had no alternate names.** Added `aliases: list[str]`
  for alternative phrasings (e.g. "Factorization Theorem" vs "Fisher-Neyman").
  Implemented in `schemas/memory.py`. Closed 2026-08-18.
  *(Amended 2026-08-18: renamed `aliases` → `synonyms` for clarity.)*
- **[schema] Denormalized `course_id` on `Chunk` / `Dependency` /
  `ConceptMastery` — rejected.** Considered for query performance and declined:
  at single-user MVP scale the joins are negligible, and denormalization adds a
  consistency hazard. Revisit only with measured evidence. Closed 2026-08-18.
- **[schema] Cached `label`/`quote` on `Citation` — deferred.** Display-cache
  denormalization; joins are cheap at MVP scale. Can be added later as nullable
  fields with no migration pain if citation rendering or snapshotting needs it.
  Closed 2026-08-18.
- **[schema] `MemoryObjectEvidence.evidence_level` was a raw `str`.** Inconsistent
  with every other model (which uses the `EvidenceLevel` enum), so typos would
  pass validation. Changed to `evidence_level: EvidenceLevel =
  EvidenceLevel.DIRECT`. Implemented in `schemas/evidence.py`. Closed 2026-08-19.
- **[schema] `Attempt.score` locked in a 0–6 grade-like scale.** Conflicted with
  project.md's "do not collapse to a single fake-precise score too early."
  Loosened to `score: int | None` with a 0–100 bound, keeping it as structured
  evidence without hardcoding one grading scheme. `evaluation` stays narrative.
  Implemented in `schemas/student_model.py`. Closed 2026-08-19.
- **[schema] No canonical values for `Claim.claim_type` / `Citation.target_type`.**
  The fields stay free strings for extensibility, but there was no single source
  of truth for spelling, risking silent mismatches (e.g. "chunk" vs "chunks").
  Added `KNOWN_CLAIM_TYPES` and `KNOWN_CITATION_TARGETS` frozensets as the
  reference. Implemented in `schemas/base.py`. Closed 2026-08-19.
- **[schema] `CourseObject` could be created dangling.** Both `content_uri` and
  `content` were optional, so an object with neither was valid. Added a
  `model_validator` requiring at least one be present. Implemented in
  `schemas/identity.py`; test added in `tests/test_schemas.py`. Closed 2026-08-19.

## Resolved by design discussion (this session)

- **Embedding misalignment** avoided by not relying on embeddings for retrieval.
  Instead: a model-written, per-course **Table of Contents** (`TableOfContents` +
  `TocEntry`) describes what's in the course and where. Written by a small, stable
  TOC model so descriptions stay consistent over time. Grows and is versioned.
  Implemented in `schemas/memory.py`. Closed 2026-08-17.
- **Chat history in two forms**: raw chat (`Conversation` + `ConversationTurn`)
  shown to the user, and a compressed summary (`ChatSummary`) used as LLM context,
  regenerated when the conversation grows past a threshold. Implemented in
  `schemas/chat.py`. Closed 2026-08-17.
- **Multi-model strategy** (leaving "one model to rule"): a small TOC-updating
  model, plus the generative model, plus optional OCR/embedding models, each for
  its own task. Recorded as a direction; not yet fully engineered.

## Schema review pass (2026-08-19)

Code review pass on the full schema. Renames and structural fixes:

- **[design] "Provenance" naming removed.** The term was disliked; renamed the
  file `provenance.py` → `evidence.py`, and the classes/field:
  `ArtifactProvenance` → `ArtifactOrigin`, `ProvenanceRecord` → `ModelDecision`,
  `CourseObject.provenance` → `CourseObject.origin`. Implemented in
  `schemas/evidence.py`, `schemas/identity.py`.
- **[schema] `LocatorType` was an enum — defeated extensibility.** Same bug class
  as `kind`; a new locator type (e.g. `cell_range`) would require a code change.
  Removed the enum; `Locator.locator_type` is now a free `str`. Implemented in
  `schemas/source_content.py`.
- **[schema] `Attempt.concept_id` (single) vs `AssessmentItem.concepts` (list).**
  An item can test multiple concepts; an attempt must record against all of them.
  Changed `Attempt.concept_id` → `Attempt.concept_ids: list[UUID]`. Implemented in
  `schemas/student_model.py`.
- **[schema] `ConceptMastery` had no `user_id`.** Mastery is per-student, but the
  model only carried `concept_id` — two students' mastery would collide. Added
  `user_id`. Implemented in `schemas/student_model.py`.
- **[schema] `Claim.response_id` dangled (no `Response` object).** The tutor's
  answer wasn't modeled. Added a `Response` model (`response_id`, `conversation_id`,
  `turn_id`, `trace_id`, `content`, `model`). The source-grounding chain is now
  `Response → Claim → Citation → RetrievalTrace`. Implemented in
  `schemas/evidence.py`.
- **[schema] `ConversationTurn.role` was a free `str`.** Bounded to a new
  `MessageRole` enum (`user`/`assistant`/`system`) so typos are caught and
  filtering is reliable. Implemented in `schemas/base.py`, `schemas/chat.py`.
- **[schema] `Chunk.embedding` removed.** Leftover from the old embedding approach;
  TOC-based retrieval made it dead weight. Removed from `schemas/source_content.py`.
- **[schema] `MemoryObjectEvidence` had no primary key.** Added surrogate
  `evidence_id` UUID, consistent with every other table and avoiding composite-key
  friction in raw SQL. Implemented in `schemas/evidence.py`.
