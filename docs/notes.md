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
