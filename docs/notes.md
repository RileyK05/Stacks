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

## Deletion & account lifecycle design (2026-08-20)

Unifying principle: **destruction leaves a distilled record.** Instead of hard
cascading deletes that silently wipe everything, we archive a distilled summary
before removal. Implemented across migrations `001`/`002` + schemas.

- **[design] Course deletion keeps a memory.** Before a course row is removed, a
  distilled `course_memories` record is written (code, name, summary, key concepts)
  so the course can still be referenced/answered-about later. The `course_id` in
  `course_memories` is stored without a hard FK so the memory outlives the course.
  Tables: `course_memories`. Closed 2026-08-20.
- **[design] Source removal compresses its citations.** Before a source's citations
  are removed, a `citation_snapshots` record is written (the citations + why each
  was valid) so grounding evidence is preserved even after the source is gone.
  Tables: `citation_snapshots`. Closed 2026-08-20.
- **[design] Account deletion uses a 7-day grace period.** `users` gained
  `delete_requested_at`; a delete is a soft marker, and the account is hard-removed
  after 7 days (cancel = clear the marker). Closed 2026-08-20.
- **[design] `ON DELETE` split, not blanket cascade.** Ownership trees (course →
  content, user → courses) cascade; evidence/grounding links (chunk → citation,
  memory_object → evidence) `RESTRICT` so the app is forced to snapshot before
  removing evidence. Implemented via app-layer archive-then-delete.
- **[auth] Added `users.email` + `users.password_hash`.** Auth is planned for the
  MVP (not deferred) since it's a known, easily-implemented problem. Email is
  unique (partial index, non-null emails only). Password hashing (bcrypt/argon2)
  and sessions are still to be built. Closed 2026-08-20.

## Migration layer (2026-08-20)

- `src/backend/common/migrations/001_init.sql` — full six-layer schema (9 enums,
  26 tables, indexes). Applied against `course_assistant`.
- `src/backend/common/migrations/002_auth_and_distilled_records.sql` — auth columns
  + `course_memories` + `citation_snapshots`. Applied.
- Cross-check fixes folded into `001` (re-applied cleanly): `idx_attempts_concept`
  → GIN (JSONB containment); UNIQUE `(user_id, concept_id)` on `concept_mastery`;
  UNIQUE `(course_id, version)` on `tables_of_contents`; hot-path FK indexes
  (`memory_object_evidence`, `dependencies.dependent_id`, `responses.trace_id`,
  `chat_summaries.conversation_id`, `attempts.course_id`); `idx_sources_course_hash`
  for dedup.
- `Locator.end` → `end_value` in SQL (reserved word); data layer maps it back to
  the Pydantic field `end`.
- **Pending:** a migrations runner to apply versioned `.sql` in order (currently
  applied manually via `psql`).
  *(Resolved 2026-08-20: `common/migrate.py` runner built — tracks applied
  versions in a `schema_migrations` table and applies pending `.sql` in order.
  Run via `python -m src.backend.common.migrate`.)*

## Auth foundation (2026-08-20)

- **[auth] Decided: JWT + bcrypt.** Stateless tokens (no session table), pairs
  with FastAPI + separate frontend. bcrypt is battle-tested and simple. Deps
  added: `bcrypt`, `PyJWT`. Closed 2026-08-20.
- **[infra] `common/config.py`** — minimal `.env` loader (no python-dotenv dep)
  exposing `Settings` (Postgres DSN + `jwt_secret` + `jwt_expire_minutes`).
  Closed 2026-08-20.
- **[infra] `common/db.py`** — the single Postgres connection seam (`connect()` +
  `connection()` context manager). Closed 2026-08-20.
- **[auth] `common/auth.py`** — pure auth utilities: `hash_password`/
  `verify_password` (bcrypt, salt-random), `create_access_token`/
  `decode_access_token`/`token_user_id` (JWT HS256, 7-day expiry from config).
  No FastAPI coupling; fully unit-tested. Closed 2026-08-20.
- **[config] `JWT_SECRET` required in `.env`.** Dev default is short and emits an
  `InsecureKeyLengthWarning`; a real 32+ byte secret silences it. User to set.

## Auth API + query layer (2026-08-20)

- **[infra] `common/queries/`** — raw SQL lives in `.sql` files (per AGENTS.md
  convention). A tiny loader (`common/queries/__init__.py`) splits files into
  named blocks via `-- name: block` markers and caches them. Every subsystem
  uses this; no inline SQL strings. Closed 2026-08-20.
- **[repo] `common/users_repo.py`** — user CRUD via the query loader + `db.py`.
  `create` uses autocommit (INSERT...RETURNING); reads use `dict_row` cursors.
  Closed 2026-08-20.
- **[api] `src/backend/api/auth.py`** — FastAPI router: `POST /auth/register`,
  `POST /auth/login` (returns JWT), `GET /auth/me` (protected). `current_user`
  dependency decodes the bearer token, looks up the user, and blocks
  pending-deletion accounts. Closed 2026-08-20.
- **[api] `src/backend/main.py`** — FastAPI app factory (`create_app`) + `app`
  instance. Run with `uvicorn src.backend.main:app`. Closed 2026-08-20.
- **[deps] Added `fastapi`, `uvicorn[standard]`, `httpx` (dev/test).** Closed
  2026-08-20.
- **[tests] Repository + endpoint tests** against the live Postgres (autouse
  fixture cleans `*@test.invalid` users). 46 tests total, all green.

## Architecture review implementation (2026-08-25)

- **[security] Public/internal user boundary.** `User` no longer carries
  `password_hash` or `delete_requested_at`; internal account state moved to
  `UserAccount`. Auth endpoints explicitly return the public model, with tests
  proving credential fields are absent. Registration now normalizes email and
  validates bcrypt-safe password bounds. JWT issuer/audience/required claims are
  enforced, pending-deletion login is blocked, and production rejects the
  development signing secret. Closed 2026-08-25.
- **[schema] Course access model.** Courses now have an owner and private/public
  visibility. `course_memberships` grants a learner read/use access without
  source mutation. Authorship (`created_by_user_id`) is distinct from ownership;
  personal attempts, mastery, chat, and recommendations remain private. Member
  copying/forking is deferred. Decision: `docs/decisions/001_course_access_and_source_objects.md`.
  Closed 2026-08-25.
- **[schema] Source/course-object specialization.** `sources.object_id` is a
  unique FK to `course_objects.object_id`; migration 003 backfilled generic
  object rows for existing sources. Migration 004 makes the FK include course
  and creator identity so the two records cannot cross tenants. Source creation
  must write both rows in one transaction. Closed 2026-08-25.
- **[security] Course access database invariants.** Migration 005 rejects
  course-object and private student records whose user is neither the owner nor
  an active member. It also enforces that base source objects are owner-created,
  member-scoped, and backed by a source-kind generic object. Application
  permission checks remain the actor-level authorization boundary. Closed
  2026-08-25.
- **[ingest] Ordered retryable pipeline.** Added persisted ingestion run/stage
  state, dependency links, attempt counts, handler/config versions, and an
  executor that retries a failed stage twice in total, then stops before later
  stages. Versioned defaults live in `configs/ingestion.toml`. Closed 2026-08-25.
- **[evidence] Citation snapshot contract.** Archived citations now require the
  original claim, target, locator, excerpt, and explanation of validity; source
  hash and archive reason are retained when available. The archive-then-delete
  service itself remains unimplemented and is explicitly marked planned in
  `system.md`. Closed 2026-08-25.

## Open after architecture review (2026-08-25)

- **[security] External-deployment auth controls.** Add login throttling and
  decide token revocation/rotation before exposing the service publicly.
- **[design] Shared-course copying.** Members can currently view/use base sources
  and create their own artifacts but cannot copy/fork the base course. Revisit
  only when a concrete copying workflow is requested.

## Public discovery and enrollment revision (2026-08-26)

- **[access] Visibility and enrollment separated.** Anonymous visitors may view
  owner-published canonical objects on public courses, but source use and model
  generation require a signed-in owner or active enrollment. Public courses
  allow self-enrollment; private courses require an owner invitation. Migration
  006 replaces course-membership terminology with course enrollment. Decision:
  `docs/decisions/003_public_enrollment_and_personal_artifacts.md`. Closed
  2026-08-26.
- **[privacy] Learner generations are personal artifacts.** Learner-generated
  materials now live outside canonical course objects and remain visible only to
  their learner, including after enrollment revocation or course deletion. A
  course owner cannot inspect or mutate them merely by owning the source course.
  Copying or promotion into canonical content remains deferred. Closed
  2026-08-26.
- **[tutor] Requester-scoped presentation.** Owners may use their own structured
  tutor profile; non-owners use the versioned generic profile in
  `configs/tutor.toml`. Profiles may change presentation but never TOC,
  retrieval, evidence, citations, evaluation, or mastery. Closed 2026-08-26.

## Session status (2026-08-29)

Verified baseline at session start — full quality gate green:

- **Tests:** 81 passed (pytest).
- **Lint:** ruff clean.
- **Typecheck:** mypy clean across 30 source files.
- **Working tree:** uncommitted — migrations 003–006, `common/permissions.py`,
  `ingest/pipeline.py` + `ingest/config.py`, `tutor/profile.py`,
  `schemas/ingestion.py` + `tutor.py`, `configs/` (`ingestion.toml`,
  `tutor.toml`), `docs/decisions/001–003`, and matching test updates. This is
  the 2026-08-25/26 architecture-review + enrollment-revision work, complete
  and verified but not yet committed.
- **Milestone position:** Milestone 0 done. Milestone 1 (auth + source-grounded
  retrieval) in progress: auth, course access model, and the ordered ingestion
  pipeline skeleton are implemented; file parsing, locators/chunks population,
  TOC-guided retrieval, cited answers, and retrieval traces remain planned.
- **Still open (carried):** login throttling + token revocation before external
  deployment; archive-then-delete services unimplemented; model provider
  unchosen (no-retention policy must be verified).

## Pre-commit review of uncommitted changeset (2026-08-29)

Tactical review before committing: deep pass on security + business logic
(permissions.py, migrations 003–006, auth stack, ingest pipeline); light pass
on schemas/tests/docs. Baseline gate was green (81 tests, ruff, mypy).

- **[security] Clean.** Permission matrix matches decision 003 exactly
  (anonymous → published objects only; enrollment → use/generate, never
  canonical mutation; artifacts private to learner). DB invariants in 005/006
  back the app layer correctly; 004's composite FK prevents cross-tenant
  source/object mismatch. Auth: dummy-hash anti-enumeration on login, bcrypt
  72-byte bound handled, JWT iss/aud/claims enforced, production rejects dev
  secret. No findings requiring code change now.
- **[design] Revoked enrollment has no re-activation path.** `can_self_enroll`
  requires `enrollment is None`, and the UNIQUE `(course_id, user_id)`
  constraint blocks a new row, so a revoked learner can never return without
  manual SQL. Worse: the enrollment policy trigger only fires on
  INSERT/UPDATE OF (course_id, user_id, enrollment_source, invited_by_user_id)
  — a direct `UPDATE ... SET status='active'` bypasses re-validation (e.g.
  course went private meanwhile). Acceptable for MVP; must be closed before
  any real invitation flow ships.
- **[security, low] Pending-deletion login leaks state pre-auth.** `/auth/login`
  returned 403 before password verification for `delete_requested_at` accounts —
  disclosing account existence + deletion state without credentials, and timing
  differed from the dummy-hash path. **Fixed 2026-08-29:** password is now
  verified before the deletion check, so unauthenticated callers cannot probe
  account state.
- **[design, low] Enrollment trigger vs CHECK ordering.** An invitation row
  with NULL inviter passes `enforce_course_enrollment` (`NULL <> owner` →
  NULL → no raise) but is caught by the `course_enrollment_source_consistency`
  CHECK with a less clear error. Net safe; cosmetic only.
- **[design, low, deferred] `content_uri` is unvalidated.** Both
  `course_objects` and `user_artifacts` store free URIs; the future serving
  layer must resolve them safely (no arbitrary path reads). Noted for
  Milestone 1 retrieval work.
- **[perf, negligible] `get_settings()` re-reads `.env` per call** (every token
  create/decode). Fine at MVP scale; add an lru_cache if it ever shows up.

### Ingestion business-logic review (2026-08-29)

Traced config → executor → schema → Pydantic models end to end.

- **[design] The pipeline is a skeleton with unwired seams.** All pieces exist
  independently — `ingestion_runs`/`ingestion_stage_runs` tables (003),
  `IngestionRun`/`IngestionStageRun` schemas, `execute_pipeline` with its
  `observe` hook, and versioned config — but nothing connects them: there is
  no ingestion repo (queries dir only has `users.sql`), no caller of
  `execute_pipeline`, and no code that transitions run-level
  `pending → running → succeeded/failed`. This is the actual Milestone 1 gap:
  wiring, not pieces.
- **[design] Run-level failure ownership is unspecified.** If the caller of
  `execute_pipeline` forgets to catch `IngestionPipelineError` and mark the
  run failed, a failed run stays `running` in the DB forever. The repo layer
  should own this (context-manager or explicit try/finally), not each caller.
- **[design] `StageHandler = Callable[[], None]` carries no context.** Real
  handlers (parse, locators, chunks, TOC, memory) need source/run/config
  context; the signature will change or handlers become closures. Decide when
  wiring the first real handler.
- **[design] Idempotency is documented but unenforced.** system.md requires
  retry-safe handlers; `execute_pipeline` neither provides delete-before-write
  hooks nor checkpoints. Enforcement will live entirely in handlers — make it
  a stated contract when the first real handler lands.
- **[design, minor] `depends_on_stage_id` has no producer.** The schema stores
  per-stage dependency links but `execute_pipeline` uses the hardcoded linear
  `PIPELINE_STAGES` order. Consistent today (linear == dependency order);
  either populate the links when wiring or drop the column later if the
  pipeline stays linear.
- **[verified clean]** Config validation forces exact stage order match;
  retry-then-halt semantics match system.md (2 total attempts, later stages
  unstarted); `except Exception` doesn't swallow KeyboardInterrupt; observer
  sees final FAILED before the raise. Tutor profile selection logic (generic
  must be user-less, owner profile ownership-checked, non-owners always
  generic) is correct. 006 backfill ordering is trigger-safe (backfill runs
  before the policy trigger exists).
- **[security, low, app-layer] Artifact ownership transfer unchecked at DB
  level.** `enforce_user_artifact_access` validates only that the (possibly
  new) `user_id` has course access — it cannot check the mutating actor.
  Ownership enforcement must come from `can_manage_user_artifact` at the API
  layer when mutation endpoints exist.

### Broad-review gaps: compute-spend control (2026-08-29)

Architectural pass for the "wasted tokens" class of business rule. Verified
covered: anonymous users cannot generate (`can_generate_materials` requires
auth), sources are enrollment-scoped so raw material is not anonymously
scrapable. Not covered — all one class, **nothing limits spend**:

- **[design] Stranger token-spend chain.** Open registration (no invite code,
  no throttle) + public-course self-enrollment + generation rights = anyone
  can burn the operator's API budget. Acceptable while the user base is known
  people; must be closed (per-user daily generation budget, or generation
  restricted to invited enrollments) before any course goes truly public.
- **[design] No rate limiting on any model-compute path** — generation
  frequency, registration spam, ingestion frequency. Generalizes the already
  open login-throttling item to all compute endpoints.
- **[design] No upload size limit / per-course ingestion budget.** One huge
  upload = one expensive ingestion run (TOC-writer + memory extraction are
  model calls).
- **[design] Retry double-spend.** Model-calling stages (TOC, memory) are not
  idempotent-by-contract yet: if the model call succeeds but the DB write
  fails, the retry re-pays for model output. The idempotency contract needs
  "persist model output before any failure point."
- **[design] Chat caps absent.** Summary compression caps context, not
  conversation/turn count.
- Linked to known-open items: login throttling, token revocation (a leaked
  7-day JWT is 7 days of generation spend).

## Tiers and spend control implementation (2026-08-29)

Closes the spend-control class above at the schema/config level. Decision:
`docs/decisions/004_tiers_and_spend_control.md`. Migration 007 applied.

- **[schema] `users.tier` (default free), synced from `user_subscriptions`.**
  Subscription history is append-only; at most one active subscription per
  user (partial unique index); a trigger is the sole writer of `users.tier`, so
  tier can never disagree with history. Ending the last subscription resets to
  free.
- **[schema] `generation_ledger` is append-only.** One row per model call:
  user, course, task, model, input/output tokens. Spend is inspectable, never
  edited. `KNOWN_GENERATION_TASKS` in `schemas/base.py` is the spelling source
  of truth (tasks stay free strings).
- **[config] `configs/tiers.toml` — versioned tier policy.** Per tier: weekly
  token budget + model routing per task role (`answer`, `toc_writer`, `probe`,
  `extraction`). Free runs the cheap generative model, paid the newer one,
  TOC-writer shared. Loader validates every tier defines every role. New tiers
  are a config section + enum value, not a schema redesign.
  *(Amended 2026-08-29: routing keys were unified to the
  `KNOWN_GENERATION_TASKS` vocabulary — the config now routes
  `tutor_answer`/`toc_update`/`probe_generation`/`probe_evaluation`/
  `memory_extraction`/`artifact_generation` — closing a two-vocabulary
  mismatch between the ledger's task strings and the config's routing keys.
  See "Session review fixes" below.)*
- **[code] `common/tiers.py` + `common/spend_repo.py` + `common/budget.py`.**
  Weekly window is rolling Monday 00:00 UTC. `check_budget` gates compute and
  returns an inspectable `BudgetState` (spent/budget/remaining/week start);
  it gates but does not reserve (brief overshoot under concurrency accepted).
- Tests: 88 passing (migration invariants, subscription lifecycle sync, tier
  routing, weekly window, ledger, budget guard, tier on auth responses).
- **Still open:** payment/billing flow (operator-managed for now); rate
  limiting per request (budget caps weekly volume, not burst rate); the
  ingestion model calls must actually be recorded when wired (the seam exists,
  the callers don't yet); retry double-spend remains open per above.

## Course limits per tier (2026-08-29)

Added `max_owned_courses` to tier policy (`configs/tiers.toml` v2: free 2,
paid 20). `budget.check_course_limit` gates course creation against the
count of owned courses; enrollment elsewhere is unlimited, course deletion
frees the slot. Rationale: cap storage/quota farming, not collaboration.
Decision doc 004 updated; conftest now also cleans `TEST-%` courses.

## Paid budget bump + course storage caps (2026-08-29)

- **[config] tiers.toml v3.** Paid weekly token budget 1M → 2M (free stays
  100k). New `max_course_storage_bytes`: free 500 MB, paid 5 GB per course.
  *(Config is now v4 — routing keys unified to `KNOWN_GENERATION_TASKS`, see
  "Session review fixes".)*
- **[schema] Migration 008.** `sources.size_bytes BIGINT` (nullable,
  non-negative check, course-size partial index). The upload path records
  actual stored bytes; accounting reflects files on disk, not requests.
- **[code] `budget.check_course_storage(course_id, tier, policy,
  incoming_bytes)`** — pre-upload gate; sums course sources, projects with the
  incoming file, raises `StorageLimitExceededError` past the cap, returns the
  projected total for headroom display. A file larger than the entire cap is
  rejected outright.
- **[test-infra] conftest cleanup order fixed.** Test-course teardown now
  deletes generation_ledger → course_objects → courses → users (FK direction),
  keyed off test users rather than course-code patterns.
- Still open: a per-course *source count* cap was considered and skipped —
  storage bytes + weekly ingestion budget cover the farming vector.

## Funky business logic: ratification list (2026-08-29)

End-to-end review pass. None of these are wrong; all are defensible but
arguable. Each needs an explicit "intended" or a change before/with commit.

1. **Spend follows the spender, not the course.** An enrolled free-tier
   learner generating inside a paid owner's public course uses their own
   (free) model routing and budget. "Paid gets better models" applies to the
   person who paid, never to everyone in their course. Ratify: spend always
   bills the requester.
2. **Owner-subsidized course upkeep.** Ingestion model calls (TOC updates,
   memory extraction) charge the *uploading owner's* budget, but enrolled
   learners retrieve against that maintained TOC for free. Course maintenance
   is an owner cost; learning is a learner cost. Ratify.
3. **Downgrade never destroys data (soft landing).** A paid user with 20
   courses / 5 GB-per-course storage who downgrades keeps everything; they
   are only blocked from *new* courses/uploads until under the free caps.
   Alternative would be forced deletion — rejected; deletion requires the
   distilled-record ceremony. Ratify.
4. **Caps are per-course, not per-user aggregate.** Theoretical worst case
   per paid user: 20 courses × 5 GB = 100 GB. There is no aggregate
   user-level storage cap. Consider: add one if real usage ever approaches
   operator disk; config knob, not schema change.
5. **Ownership capped, enrollment uncapped.** A learner may enroll in any
   number of public courses; enrollment stores no bytes and generation bills
   their own budget. Ratify.
6. **No independent per-file size cap.** A single upload is only bounded by
   the course cap (so a 499 MB file into an empty free course is accepted,
   then ingestion token-charges the owner for it). Consider: a small
   per-file ceiling (e.g. 100 MB) as a cheap early rejection.
7. **Budget gate-not-reserve.** Concurrent requests can overshoot the weekly
   budget slightly. Accepted at MVP scale; reservation would need locking.
   Ratify.
8. **Weekly window is Monday 00:00 UTC**, not user-local, so a Sunday-night
   burst plus Monday-morning burst both fit fresh budgets ~hours apart.
   Standard behavior for weekly limits; ratify the definition.
9. **Token budgets price tokens, not dollars.** Paid users get a bigger
   token budget *and* pricier models — in dollar terms the tiers differ even
   more than the numbers suggest. Fine while we pay the provider bill; a
   dollar-denominated budget is a possible future switch.
10. **Callers pass the tier into `check_budget`/`check_course_limit`.** The
    gates trust the caller-supplied tier; nothing cross-checks
    `users.tier` at that seam. The endpoint contract (gates-without-callers)
    resolves tier from the authenticated account; a defensive re-check
    inside the gate is possible if we want belt-and-braces.
11. **Ledger survives course deletion with `course_id` nulled.** Spend
    history loses course attribution when a course is deleted. Consistent
    with distilled-record principle (row survives, reference does not).
    Ratify.
12. **Known-open carried items:** revoked-enrollment dead end;
    re-activation bypasses the enrollment policy trigger (status-only UPDATE
    doesn't fire it); no burst rate limiting; billing flow is operator
    manual.

Verified during this pass: one-active-subscription partial unique index
blocks a second active row per user (probe confirmed UniqueViolation);
migration chain 001→008 applies cleanly to an empty schema; DB columns match
Pydantic models field-for-field on every touched table.

## Open: gates without callers (2026-08-29)

**Contract reminder for Milestone 1 wiring.** The spend/limit gates exist and
are tested, but their enforcement points are future endpoints. When building
them, the caller is responsible for the full gate sequence — the gates do not
call each other:

- **Upload endpoint** (course sources): owner-only (`can_manage_sources`) →
  course-limit check → storage checks (per-course AND aggregate) with actual
  file bytes → compress on entry where the format allows → write source +
  course object rows → then ingestion pipeline starts. All gates must run
  *before* any file write; `size_bytes` records post-compression stored bytes.
- **Generation endpoints** (tutor answers, probes, artifacts, summaries):
  authn → enrollment/access check (`can_generate_materials`) → `verify_tier` →
  `check_budget` → resolve model via tier policy → call model →
  `spend_repo.record_generation` with real token counts plus
  `free_tier_overhead` for free-tier users (record *after* the call; record
  even if the caller's access lapsed mid-flight — spend must be visible; the
  overhead only affects the *next* gate, never an in-flight answer).
- **Course creation endpoint:** `check_course_limit` before insert.

Every endpoint that spends tokens or accepts bytes must go through these
seams; none of the gates self-execute. Whoever builds the endpoints wires the
calls; if an endpoint exists without its gate calls, that is a bug, not a
shortcut.

## Ratified business-logic decisions (2026-08-29)

Operator review of the ratification list above. All decisions final for this
changeset; migrations 009/010/011 + `tiers.toml` v5 implement them.

1. **Spend bills the requester, not the course.** Confirmed as intended —
   usage credits are user-scoped, so making 20 duplicate courses cannot
   multiply generation. (Was already the behavior; now ratified.)
2. **Course upkeep is owner-paid.** Ingestion model calls charge the
   uploading owner's budget; enrolled learners generate against their own.
3. **Downgrade soft landing + 60-day limit.** Excess kept while blocked from
   new creation; `downgrade_grace_deadline` set by trigger on subscription
   end, cleared on resubscribe. Past 60 days, excess may be removed by the
   operator (archive-first). Removal sweep itself is still a planned service.
4. **Caps reduced.** Per-course: free 100 MB, paid 1 GB. Aggregate per owner:
   free 1 GB, paid 10 GB (`max_total_storage_bytes`, migration-checked gate
   `check_total_storage`). Compression on entry to be implemented in the
   upload path.
5. **Enrollment fixed.** Migration 011 revalidates on any enrollment UPDATE
   (status-only re-activation no longer bypasses policy: self-service
   re-activation on a since-privatized course is rejected; valid invitations
   re-activate cleanly). Revoked learners can return through the validated
   path.
6. **Compression on entry.** Upload contract: compress where the format
   allows; `size_bytes` records stored bytes. Implementation lands with the
   upload endpoint.
7. **Free-tier 5% overhead.** Applied at record time (`overhead_tokens`,
   migration 009; counts in `weekly_spend`), never mid-generation. Gate
   semantics unchanged: in-flight answers are never cut off.
8. **Weekly window Monday 00:00 UTC** — ratified as-is.
9. **Token-denominated budgets** — ratified; dollar budgets deferred.
10. **Tier double-verification.** `budget.verify_tier(user_id, tier)` re-checks
    against `users.tier`; endpoints must call it.
11. **Ledger keeps `course_label`** snapshot (migration 009 backfilled), so
    spend attribution survives course deletion.
12. **Carried open items:** burst rate limiting is *rejected by design* — the
    weekly budget is the only throttle; a user burning their whole budget in
    one session is intended behavior (operator ruling 2026-08-29). Billing
    flow is operator-manual until Stripe (or similar) is integrated. Removal
    sweep for post-grace downgrades waits on the archive-then-delete service.

Gate after implementation: 99 tests, ruff, mypy green.

## Premium claim codes (2026-08-29)

Operator request: every account can hold a code that may or may not grant
premium, serving as a recovery path ("enter premium code") if authentication
misbehaves, plus easy manual testing before Stripe. Migration 012 +
`premium_codes_repo`.

- **[security] Codes stored as SHA-256 hashes** (plaintext shown once at
  issue, code alphabet excludes ambiguous glyphs, normalization strips
  separators and case). A DB leak reveals no usable codes — same principle
  as password hashing.
- **[design] Claim requires an authenticated user.** Anonymous callers can
  never flip tiers (decision 003 boundary holds). Tiers are granted by
  `redeem` starting a paid subscription through the existing machinery.
- **[schema] Bound codes:** `issued_for_user_id` binds a code to one account;
  claiming user deletion fully releases the claim (trigger resets claimed_at
  and grants_premium so the code is claimable again — caught via teardown
  FK-SET-NULL probing).
- **[bugfix from tests] `mark_claimed` originally forced
  `grants_premium = TRUE`**, which would have made every personal recovery
  code a premium code on claim. Fixed: claiming never changes what a code
  grants; the operator flag decides.
- Duplicate code issue surfaces as `ValueError("code already exists")`.
- Still open: registration wiring to auto-issue a personal code per account
  (repo seam ready), operator CLI/endpoint for issuing and flagging codes.

## Customer-support code clarification (2026-08-30)

The per-account claim code is a customer-support and entitlement-pipeline
identifier, not a primary login factor, authentication fallback, or course
sharing credential. It supports cases such as subscriptions or payments handled
through another avenue. Registration displays the code once and stores only its
hash. Course invitation/share codes, if adopted, are a separate future concept
with their own lifecycle and permissions; course creation must not mint another
account support code.

## Superseding support-code and archive decision (2026-08-30)

The sentence above saying registration displays the support code is rejected.
Registration creates the bound hash record but **no API ever returns the
plaintext or code metadata**. The initial plaintext is discarded; support must
rotate internally and deliver a replacement out of band. Redemption requires an
already authenticated account and grants an entitlement only. It never proves
identity, replaces login, or participates in ordinary billing.

Course sharing now uses a distinct server-generated random join code with
private / invite-only / public exposure rules and explicit invitation
acceptance. Deletion retains the exact course for a 90-day copy grace period,
then purges it through a durable cleanup job. Each participant's bounded
course-memory record, including a compact evidence snapshot, is the only
permanent course-derived record. Public-to-restricted changes archive the old
public version and return a new restricted successor. Full decision:
`docs/decisions/005_course_sharing_archives_and_support_codes.md`.

## Second-model review fixes (2026-08-30)

Independent adversarial review of the same changeset found seven defects and
a set of consistency gaps; all were fixed in this pass. Migration 016 +
`lifecycle.toml` v2 implement the schema-level ones.

- **[bugfix] Redeeming a premium code while already subscribed was a 500.**
  `user_subscription_one_active` raised through `insert_subscription` with no
  ValueError mapping. Redeem now locks the user row, checks the active
  subscription first, and rejects with "already has an active subscription"
  (code stays unclaimed, transaction atomic). Support-code rotation also no
  longer grants premium by default — the entitlement is opt-in so a pure
  re-identification rotation cannot mint premium.
- **[bugfix] `assert` was request-path error handling.** `update_course` /
  `rotate_join_code` repo `None` returns (raced archival) became
  `AssertionError` 500s and vanish under `python -O`. Now explicit 404s.
- **[bugfix] Enrollment mutations didn't map policy-trigger failures.**
  invite/accept/decline/revoke/leave could 500 on a concurrent archive;
  `join_course` mislabeled the CheckViolation as "already enrolled" (409).
  All CheckViolations now map to 404 "course not available for enrollment".
- **[bugfix] Learner leave now declines pending invitations.** A learner
  refusing their own invitation was recorded as owner-revoked
  (`revoked_at` set); semantics now: learner-refused → `declined`,
  owner-rescinded → `revoked` (separate `withdraw_enrollment` query).
- **[schema] Public→restricted is enforced at the repo seam.**
  `courses_repo.update_course` now raises `RestrictedTransitionError` for
  public→restricted plain UPDATEs; only the versioned lifecycle path may
  perform it. Previously the 90-day-grace invariant lived in exactly one API
  caller, silently bypassable by any future script/endpoint.
- **[schema] `course_memories`/`citation_snapshots` user FKs now CASCADE**
  (migration 016). Account hard-delete previously landmined on any user with
  a memory bank — i.e. every course owner — and conftest quietly pre-deleted
  both tables to work around it. Deletion ceremony ownership stays with the
  account-deletion service; the FK just no longer contradicts it.
- **[schema] Cleanup jobs have a terminal `dead` state.** Attempt counts were
  tracked but never bounded: a wedged directory retried every 5 minutes
  forever. `cleanup_max_attempts` (5) + `retry_delay_seconds` (300) in
  `lifecycle.toml` `[cleanup]`; expired-lease reclaim and failure handling
  both dead-end at the cap; `claim_cleanup` no longer re-claims 'running'
  rows directly — `reclaim_expired_cleanup_leases` is the only re-entry.
- **[schema] `course_memories.updated_at` added** (migration 016); upsert no
  longer rewrites `created_at`, and the memory-bank listing orders by it.
- **[bugfix] Archive copy now refuses file-backed-only objects.** Courses
  with `content_uri`-only course objects (no jsonb `content`) previously
  copied them as silently-empty objects; copy now fails loudly with
  `UncopyableCourseError` (409) instead. Cross-course concept prereqs are
  dropped rather than NULLed during copy.
- **[infra] Storage orphan sweep added.** Upload's crash window between file
  write and DB commit (and any future rename/delete gap) left orphaned
  directories with no cleanup path; the maintenance loop now sweeps
  UUID-named directories with no `courses` row, ignoring non-UUID entries.
  *(Amended 2026-08-30, second review: the first version only swept
  directories whose course row was gone — an upload crash orphans a FILE
  inside a live course directory, which the directory sweep never touched,
  and it had no age guard, so it could race an in-flight copy. The sweep now
  also removes source files whose source row is absent, guarded by
  `cleanup.orphan_min_age_seconds` (3600) so in-flight uploads are never
  swept. The sweep is the fallback of last resort, not the primary cleanup.)*
- **[hygiene] Exception/request-model consistency.**
  `storage.StorageLimitExceededError` renamed
  `RawUploadLimitExceededError` (body-size 413) to stop colliding with
  `budget.StorageLimitExceededError` (quota 403). All mutating request models
  now `extra="forbid"` like `CourseCreate`. Register's UniqueViolation
  handler distinguishes the email index (409) from a code-table collision
  (503, retry-safe) instead of reporting "email already registered" for both.
- **[test-infra] Lifespan maintenance loop is now exercised** (was zero-
  tested; `TestClient` outside a `with` never started it).
- **Known cosmetic, deliberately not fixed:** migration 013's header comment
  says `013_storage_foundations.sql` but the file is
  `013_upload_foundations.sql`. The migration is applied; editing an applied
  file's comment is not worth breaking the append-only rule. Recorded here
  instead. Evidence-snapshot wording in decision 005 softened to
  "representative first-chunk excerpts of up to ten sources" to match the
  implementation honestly.

## Self-review of the fallback-audit fixes (2026-09-04)

- The 2026-09-03 fix pass itself got a second review. Findings:
- **[design] The dir-level sweep still had the race**: the mtime grace
  applied to file removals only; the directory-level branch rmtree'd any
  dir with no courses row regardless of file age, so an in-flight
  restrict/copy target dir (files written pre-commit) could still be
  deleted mid-transaction. The grace is now applied uniformly: a course
  dir is removed only when every file in it is older than the grace, and
  the sweep uses `all(...)` not `any(...)` over entries (the first draft
  of the rewrite inverted this; caught in self-review before commit).
- **[design] Staging debris was never swept**: crash mid-`_atomic_write`
  leaves `.{source_id}-{rand}.tmp` staging files; `course_source_files`
  skipped them (warning hourly, removing nothing) so they accumulated
  unboundedly. New `storage.course_staging_files()` + sweep branch removes
  aged staging files; fresh staging files (in-flight writes) are kept.
- **[test-infra] `api/auth.py` redeem-path assert replaced** with an
  explicit 401 (was planned 2026-09-03 but the session cut off before
  the edit). Request paths are now assert-free.
- **[design] RawUploadLimitExceededError message said "storage
  allowance"** - misleading: it is the per-request raw-body ceiling (413),
  not the stored-bytes quota (403). Message corrected.
- **[test-infra] New sweep tests**: fresh orphan dir survives the grace
  and is removed without it; interrupted staging file removed once aged;
  fresh staging file kept. Existing sweep tests age their files with
  `os.utime` since the grace now protects fresh artifacts by default.
- **Verified sound in the same pass** (business-logic review of the
  full uncommitted changeset): subscription double-start blocked by the
  partial unique index + user-row lock in redeem; archive copy-once via
  get_archive_access FOR UPDATE + mark_copied; upload quota serialization
  on the owner user-row lock; restrict/copy storage math (owner_size
  already includes the source course); enrollment trigger fires on INSERT
  OR UPDATE (011) so upsert re-activations are policy-checked; subtree
  deletion spares course_memories by design (no FK, survives course row).

## Canonical code format + API tightening (2026-09-05)

- **[design] One canonical shareable-code format.** Join codes (courses) and
  support/premium codes now share `common/codes.py`: 16 characters from a
  31-symbol alphabet (I/L/O/0/1 removed), display form XXXX-XXXX-XXXX-XXXX
  (20 chars with dashes). Previously join codes were 12 chars and premium
  codes 16 with a duplicated alphabet/generation implementation.
  Migration `017_canonical_code_format.sql` adds DB CHECKs (course code
  alphabet/length; premium hash is 64-hex) and regenerates existing course
  codes. Closed 2026-09-05.
- **[api] Format validation at the boundary.** `JoinCourseRequest.join_code`
  and `SupportCodeRequest.code` now normalize + validate via
  `codes.require_valid` (422 on garbage) before any lookup.
- **[api] Enum-typed API views.** `EnrollmentView.status`/
  `enrollment_source` and `MemberView.status` are now the `EnrollmentStatus`
  / `EnrollmentSource` enums instead of plain strings — identical JSON wire
  format, but self-documenting OpenAPI and typo-proof at the boundary.
- **[design][OPEN] MemberView exposes learner emails to the course owner.**
  `GET /courses/{id}/members` returns each learner's email (decision 003
  allows owner visibility of enrollment emails). Risk: emails are personal
  contact data; an owner seeing emails may enable off-platform contact or
  spam. Options if this matters later: return user_id + display name only,
  gate behind an owner-only setting, or drop emails entirely. Revisit if
  the member list ever grows beyond trusted/operator-run courses.

## The three course shapes pinned as a contract (2026-09-05)

- **[design] Foundational fact recorded.** Every course is exactly one of
  `public` / `invite_only` / `private`; that closed set is the standing
  contract for all current and future development. Existing permissions
  (owner-only canonical mutation, enrollment-grants-use, learner privacy)
  are unchanged in every shape. Decision:
  `docs/decisions/006_three_course_shapes.md`. Closed 2026-09-05.
- **[design] `permissions.py` drift caught and fixed.** The module was orphaned
  (no endpoint imported it; the API re-derived checks inline) and
  `can_self_enroll` required `enrollment is None`, which silently contradicted
  migration 011's revoked-learner re-enrollment path. Fixed: re-enroll allowed
  when the enrollment is not active; added `can_join_with_code` encoding the
  two-joinable-shapes rule (public, invite_only; never private). Tests added.
  Standing rule: policy changes must touch permissions.py AND the DB triggers
  together. Closed 2026-09-05.

## Docs resync to implementation (2026-09-05)

- **[docs] project.md + system.md updated to the current truth** (overwrite,
  per convention — notes stay append-only). Key additions:
  - Three course shapes recorded as the closed contract (decision 006) in
    both docs, including per-shape join-code exposure and the
    permissions.py + triggers change-together rule.
  - Canonical code format (16 chars, XXXX-XXXX-XXXX-XXXX display,
    `common/codes.py`, migration 017 CHECKs) in project.md principles +
    system.md cross-cutting.
  - project.md milestones: new Milestone 0.5 marked done (auth, course CRUD,
    shapes, enrollment, storage, tiers/spend, claim codes, two-phase
    archive); Milestone 1 reworded to retrieval only.
  - system.md §2.1 ER: courses gained lifecycle_status/archived_at/
    purge_after; enrollments gained responded_at; per-shape semantics
    spelled out. §2.2 SOURCES gained size_bytes + stored_encoding with the
    streaming-upload/conditional-gzip rules.
  - system.md §9: support-code redemption flow documented (transactional
    redeem, tier single-sourced).
  - superseded content removed: "sessions" (JWT), "private or public"
    two-shape wording, single-model inference framing, pre-017 code format.
- **[docs] Decisions ledger now:** 001 course access, 002 auth boundary +
  ingestion runs, 003 public enrollment + personal artifacts, 004 tiers +
  spend, 005 sharing/archives/support codes, 006 three course shapes.

## Self-enroll UX signal for invite-only courses (2026-09-05)

- **[api] `self_enroll` now differentiates the two non-public shapes:**
  `private` → 404 (course existence never revealed), `invite_only` → 409 with
  detail "course is not self-enrollable; invite-only courses require a join
  code". The 409 is the machine-readable hook for the frontend's
  "invite-only — enter a join code?" prompt. Pinned in
  `tests/test_courses_api.py::test_self_enroll_invite_only_course_signals_join_code`.
- **[design] Where the redirect UX lives — split:**
  - **Backend (done):** return a distinct, documented status + message per
    shape. The API stays a JSON API; it never "renders a page" or decides UI
    flow. 409-vs-404 carries the distinction without leaking course
    existence to strangers.
  - **Frontend (todo, no backend change needed):** on 409 from `/enroll`,
    render the join-code entry view (the `/courses/join` endpoint already
    exists). Private-course 404s and generic 404s render a plain
    not-found/no-access state.
  - **Convention for future endpoints:** distinguishable, user-actionable
    failures get a specific status + stable detail string; the frontend maps
    (status, detail) to UI states. If these grow, consider a typed error
    body (`error_code` field) instead of string matching — noted as a
    possible refactor once there are several such cases.

## Policy decisions from the business-logic review (2026-09-05)

Decisions made during the human review of business-logic-heavy files; all
implemented and pinned by tests this session.

- **Copy-any-time (was copy-once).** An archive participant may copy their
  archive as many times as they like during the 90-day grace period.
  Removed `ArchiveAlreadyCopiedError`, the `mark_copied` query, and the
  `copied_course_id` column (migration `018_copy_any_time.sql` drops it).
  Tier limits (courses/storage) remain the natural brake. Pinned by
  `test_archive_can_be_copied_repeatedly_during_grace`.
- **Nothing survives purge.** The memory bank is written at archive time as a
  distilled record for the grace window, but is destroyed at purge with
  everything else: `course_deletion.sql` now deletes `course_memories`.
  Golden rule 6 (distilled record) applies to the grace window, not beyond.
  Pinned by `test_purge_removes_distilled_memory_bank_entries`.
- **Re-enrollment openness confirmed.** Revoked/declined learners can always
  re-enroll in public courses (and re-join by code / re-accept invites on
  invite-only); declined-then-rejoin is deliberate misclick protection. No
  change.
- **Join-code visibility confirmed.** On invite_only courses only the owner
  sees the code; learners cannot share access. No change.
- **Members list no longer exposes learner emails.** `MemberView` dropped
  `email`; the owner gets ids + status only and identifies members
  out-of-band. Closes the OPEN item in the earlier API-tightening note.
- **90-day grace is a set knob** (`configs/lifecycle.toml`), not to be
  tuned casually. The restrict flow (public → restricted archives the
  original so learners keep copy access; owner gets a clean successor)
  stays as designed.
- **Hardening from the same review:** `sweep_storage_orphans` now *requires*
  `min_age` (keyword-only, no default) — the guard that protects in-flight
  transactions' files can no longer be silently disabled by a bare call.
  The cross-connection lock ordering in `premium_codes_repo.redeem` is
  documented as load-bearing (do not "optimize away" the unused
  `fetchone()` on the user row lock).

## Known-gaps closure from the audit (2026-09-05)

- **Per-course purge isolation.** `purge_expired_archives` now purges each
  due archive in its own transaction (`_purge_one`): one course's failure
  rolls back only that course and is logged + skipped; the rest of the queue
  proceeds. A failing course stays archived with `purge_after` in the past,
  so every sweep retries it — a persistently failing purge shows up as a
  repeated error log, which is the operator signal. The old all-or-nothing
  transaction is gone; `test_purge_rolls_back_archive_and_cleanup_job_on_failure`
  updated to the new contract (failed purge returns [] and leaves everything
  intact), and `test_purge_failure_is_isolated_per_course` pins isolation +
  retry.
- **Mechanical FK-coverage guard.**
  `test_purge_block_covers_every_fk_referencing_table` derives, from
  `pg_constraint`, every table that can reference the course subtree via a
  foreign key and asserts the purge block mentions it. A future migration
  adding a referencing table without a purge statement now fails in CI
  instead of wedging production purges. (course_memories,
  course_archive_access, storage_cleanup_jobs are the documented
  exclusions/indirect handles.)
- **Copy/restrict failure branches now tested.** Three new tests pin:
  mid-copy OSError → successor rolled back, partial directory removed,
  archive stays copyable (retry succeeds); mid-restrict OSError → original
  stays public/active, partial directory removed, retry succeeds;
  uncopyable-object guard fires before any mutation in restrict, leaving
  the course public and active.
- **Test hygiene learned:** `monkeypatch.undo()` reverts autouse fixtures
  too (breaks the storage sandbox); restore specific targets with
  `monkeypatch.setattr(..., original)` instead.

## Remaining audit fixes (2026-09-05)

- **Redeem's double-redeem check is now structurally same-connection.** New
  `spend_repo.active_subscription_on(conn, user_id)` runs on the caller's
  transaction; `premium_codes_repo.redeem` uses it. The old cross-connection
  read was correct only via an implicit lock-ordering invariant; the
  invariant is now expressed in the API surface (the docstring on the
  variant says money-path checks must use it). Pinned by
  `test_concurrent_double_redeem_admits_only_one` (8/8 runs: exactly one
  winner, one subscription).
- **`rotate_support_code` race closed.** Concurrent rotations could leave
  two open codes (READ COMMITTED lets the second revoke miss the first's
  inserted replacement). The user-row `FOR UPDATE` now serializes rotations.
- **017's data rewrite is regression-tested.**
  `test_017_rewrites_legacy_codes_and_check_rejects_old_format` applies the
  migration chain to a scratch schema, injects a 015-era 24-hex code after
  015, and verifies the 017 DO block rewrites it into the canonical alphabet
  and the `courses_join_code_known` CHECK rejects the legacy form by name.
