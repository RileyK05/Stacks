# Design Notes & Open Issues

Living log of design observations, schema concerns, and deferred fixes.
Each entry is dated and tagged so it can be revisited or closed out.
If a concern is a **schema** problem, it gets a `[schema]` tag; if it is a
**non-schema** design issue, it gets a `[design]` tag. Decisions that are
resolved get moved to `docs/decisions/`.

> Nothing here is ever deleted. Resolved items are moved to **Closed** with a
> date and outcome, keeping a full log of what we decided and why.

## Open

**Queued for operator review / deeper design conversation:**

- **[design, OPEN — needs architecture conversation] Storage accounting vs
  decompression.** Today a file's quota cost is its *compressed* size, and
  a highly compressible 100 MB text file may only count as ~100 KB of
  quota. Nothing reads files back yet, so this is harmless today. But it
  points at a deeper question the operator wants to discuss: how storage
  should be accounted and read at the architectural level. For Milestone 1
  the hard rule is: any code that opens a stored file must unzip it
  streaming, with a cap on the unzipped size — never all at once (the
  current `read_stored` does a whole-buffer decompress and is the seam to
  replace). Broader accounting redesign (logical-vs-stored quotas, raw
  caps per file) is deferred to that conversation.
- **[design, OPEN] IP/registration throttling.** Email verification now
  gates resource creation (fixed 2026-09-10, below), but nothing limits how
  many accounts one IP can register. Operator ruling: email verification
  yes; whether IP-based limiting is feasible/desirable is unresolved —
  revisit before public launch.
- **[design, OPEN — needs architecture conversation] The learner side of
  the two-way memory model.** Ruling: course memory (the distilled
  per-course record in `course_memories`) is OWNER-ONLY — the owner's
  instrument for their course. Learners get the *generic* memory and
  harness, not the course's distilled record. What "generic memory" for a
  non-owner concretely means (what accumulates per learner across courses,
  where it lives, what the harness reads) is an open design question for
  the Milestone 2 memory subsystem — the owner-only fix below removed the
  wrong learner writes; it did not yet build the learner side.

## Closed

**Closed by the 2026-09-10 operator rulings (from the adversarial
edge-case pass):**

- **[bugfix, ruled a bug] Course memory was being written for learners.**
  The memory bank fanned out to every participant on archive, enrollment,
  and canonical mutations — contradicting the two-way memory model (owner
  gets course memory; non-owners get the generic memory/harness). Fixed:
  `course_memories` writes are owner-only everywhere (archive writes the
  owner's record; enrollment writes none; upload/rename refresh the
  owner's only; archive-copy writes the copier-as-new-owner's). Learners
  keep their private per-user data (attempts, conversations, mastery) —
  that is a different subsystem, untouched. The learner-side generic
  memory remains Open (above).
- **[fixed] Email verification + password reset** (was the "no email check,
  no password reset" item). Migration 021: `users.email_verified_at`,
  `email_outbox` (operator/worker seam — no in-process delivery), and
  `email_tokens` (SHA-256 hashes at rest, single-use, 60-minute expiry,
  one open token per kind per user). API: verification request/confirm
  (token bound to the authenticated caller), password-reset request
  (anti-enumeration: always 202, unknown emails queue nothing) and
  confirm (rejects pending-deletion accounts; success marks the email
  verified — mailbox control proves the address). Verification gates
  course creation and uploads (403 with remediation); login stays open
  to unverified accounts so existing accounts are never locked out.
  Tests: `tests/test_email_verification.py` (flows, replay, cross-account
  binding, expiry, anti-enumeration, gating).
- **[fixed] Archive-copy naming.** Default copy names now respect the
  200-char create bound (suffix survives trimming) and disambiguate:
  "name (copy)", "name (copy 2)", "name (copy 3)"... Pinned by
  `test_copy_names_are_bounded_and_disambiguated`.

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

## Memory as a user-owned subsystem (2026-09-05)

- **Decision: memory is the user's, not the course's.** The memory bank is a
  first-class subsystem, not a deletion byproduct. Course deletion (and its
  90-day archive) destroys the course's materials and archive; the user's
  distilled memory of the course persists past purge. This supersedes the
  earlier "nothing survives purge" decision for course_memories only —
  citation_snapshots and everything else still dies at purge. Golden rule 6
  is intact: the distilled record IS the retention, it just lives forever in
  the user's bank instead of expiring with the archive.
- **Implementation state:** course_memories was already FK-less by design
  (migration 002: "course_id is stored without a hard FK so the memory
  outlives the course") — the purge deletion added earlier is now removed;
  course_deletion.sql no longer touches course_memories. The
  FK-coverage guard test excludes it explicitly with this decision as the
  documented reason. The read path stays user-scoped (list_memories).
- **Next:** build the memory subsystem out — accumulation during course life
  (M2 extraction pipeline), not just archive-time snapshots. The
  archive-time write remains as the final snapshot before materials vanish.

## Edge-case review fixes (2026-09-10)

Adversarial "how do users break this" pass over lifecycle/storage/auth.
Five intentional design choices were moved to Open (above) rather than
"fixed"; eight real logic gaps were fixed and pinned:

- **[bugfix] Public→restricted PATCH 500.** `update_course` in
  `api/courses.py` didn't map `UncopyableCourseError` (the archive-copy
  endpoint did); a public course with file-backed non-source objects
  returned 500. Now 409, same as the copy path.
- **[bugfix] Memory-bank evidence could be truncated away.** The old
  assembler appended evidence last and prefix-truncated, so verbose
  concepts could remove every grounding line — violating the ratified
  "permanent memory must remain inspectably grounded" rule. `memory_bank`
  rewritten: evidence index reserved first (compact filename+locator+hash
  lines; excerpts only when budget allows), semantic content fills the
  remainder, `key_concepts` bounded so the whole retained record fits the
  budget, material assembled once per tier per refresh. Pinned by
  `test_memory_summary_keeps_evidence_within_tight_budget` (40 long
  concepts, 3 sources, free tier: summary within budget, ≥1 evidence
  entry with uncut sha256, concepts survive).
- **[bugfix] Copy was an inconsistent half-copy.** It copied derived
  concepts/dependencies without their evidence graph (ungrounded derived
  memory) and queued no ingestion. Now: raw sources, study periods, and
  owner-authored objects copy; derived memory does not (ingestion
  re-derives it); every copied source enqueues in new `pending_ingestion`
  (migration 019, with backfill of existing copied sources +
  `ingestion_history` audit table). The purge block and FK-coverage guard
  updated. Pinned by `test_copy_requeues_ingestion_and_skips_derived_memory`.
- **[bugfix] Dead cleanup jobs were silent + double reclaim.** Terminal
  `dead` transitions now emit an ERROR log with job_id, course_id, attempt
  count, and final error (both the failure path and lease-reclaim path);
  `cleanup_failed` returns the updated row. Lease reclamation has a single
  owner: `run_once()` — `process_cleanup_jobs()` no longer reclaims
  (double reclaim in one pass could dead-end a job on stale counts).
  Pinned by `test_dead_cleanup_job_logs_operator_signal` and the updated
  reclaim test.
- **[bugfix] Accept-invitation could race archival.** The policy trigger
  read the courses row with a plain SELECT; archival could commit between
  the trigger's read and the enrollment's commit, leaving an 'active'
  learner on an archived course with no archive access. Migration 020
  takes `FOR SHARE` on the courses row in the trigger — it conflicts with
  `delete_course`'s `FOR UPDATE`, making check and transition atomic.
  Pinned by `test_accept_invitation_cannot_race_course_archival`
  (two-connection: NOWAIT proves the lock conflict; complementary case
  proves post-archival accept fails the policy check).
- **[bugfix] Purge claim was decorative.** `due_archives` took
  `FOR UPDATE SKIP LOCKED` and then closed the connection before purging,
  releasing every lock — two maintenance workers could both "claim" the
  same archive. The claim moved inside `_purge_one`'s transaction
  (`claim_due_archive`); the listing is lock-free. Idempotent deletes +
  the cleanup-job unique index remain the backstop.
- **[bugfix] FK-coverage guard was vacuous.** Its `regclass::text LIKE
  'public.%'` filter matched 0 of 68 FKs (search-path tables render bare
  names) — the test had never guarded anything, which is how migration
  019's `ingestion_history` initially slipped past the purge block.
  Rewritten: transitive FK closure from `courses` restricted to
  NO ACTION/RESTRICT edges (the ones that wedge purges), excluding
  cascade/set-null edges and documented exclusions.
- **[bugfix] Empty-dir sweep bypassed the grace.** `all()` over zero files
  is vacuously true, so a freshly mkdir'd in-flight copy target could be
  rmtree'd immediately. The directory's own mtime must now be past grace.
- **[test-infra] conftest hygiene.** `DELETE FROM storage_cleanup_jobs` was
  unconditional — a test run against a shared environment destroyed pending
  (real) purge jobs. Now scoped to test-owned courses plus orphaned
  course rows, and the suite refuses to run against a database whose name
  doesn't contain "test" unless `PYTEST_ALLOW_ANY_DB=1` is set
  (deliberate opt-in; set in the local dev `.env`).
- Verified-clean in the same pass (no action): path traversal, zip-bomb
  storage streaming, upload quota serialization, join-code brute force,
  redeem double-spend, login enumeration, JWT/bcrypt bounds, support-code
  plaintext handling.
- Gate: full pytest suite green, ruff clean, mypy clean.

## Memory model ratified + vocabulary pinned (2026-09-10)

The repeated "agents keep building the memory layer wrong" problem was
diagnosed: the docs used "memory" for four different things
(course-memory node, course knowledge/TOC, student data, chat history),
the deletion diagram literally commanded "write each participant's
course memory," and the table storing the per-user node is named
`course_memories` while the course-knowledge models live in
`schemas/memory.py` — so every session re-derived its own interpretation.

Operator ratification (decision `docs/decisions/007_memory_model.md`):

- **User memory (root)** — per-user, lifelong, behavioral ("teach THIS
  person with visuals/analogies") + cross-course history; the only layer
  that may change model behavior; cross-course emphasis (Calc 1 integrals
  struggle → Calc 2 emphasis) happens at the root at prompt time.
- **Course memory (child)** — per-user per-course FOCUS node ("what THIS
  person struggles with in THIS course"); facts about understanding,
  never behavior instructions, never shared. **Stored ONLY for the main
  user of the course (its owner)** — per-learner nodes were rejected as
  too complex; learners get the harness plus their own raw private
  student data.
- **Course knowledge / TOC** — what the course SAYS and the index for
  FINDING it; shared per-course state; explicitly not memory.

Implemented this session:

- Decision doc 007 written; `AGENTS.md` gained a mandatory vocabulary
  block ("read before touching anything named memory") that maps each
  term to code homes and names the single write seam.
- `common/memory_bank.py` → `common/course_memory.py` (git mv, history
  kept). `upsert_for_users` folded into a private `_write_node`;
  `refresh_for_owner(cur, course_id)` is now the ONLY public write seam —
  it derives the owner from the course row, so no caller can ever pass
  another user's id. All five call sites (archive, restrict-successor,
  archive copy, course create, upload/rename) route through it.
- API route `GET /memory-bank` → `GET /course-memories` (read-only).
- Doc scrub: system.md §0 TL;DR, §2.3 heading ("Course knowledge"),
  §2.7 deletion diagram + COURSE_MEMORIES bullet now owner-only; the
  "each participant's" line that taught the prior bug is gone.
  project.md one-liner, principles, deletion, Milestone 2 (now "User +
  course memory" per the tree model), pipeline stage name
  (course-knowledge extraction).
- `schemas/memory.py` and `src/backend/memory/__init__.py` now carry
  docstrings flagging their names as legacy misnomers pointing at
  decision 007. `MemoryObject`'s docstring: a course-knowledge note, not
  memory.
- Tests renamed accordingly (`memory_bank` → `course_memory` imports,
  `/memory-bank` → `/course-memories` calls). No behavior change: the
  owner-only semantics were fixed in the previous pass; this pass makes
  the vocabulary and seams unable to teach the wrong thing.

## Whole-repo remnant sweep after the memory-model ratification (2026-09-10)

Second pass over every file for stale remnants the rename missed. Fixed:

- `courses_lifecycle.delete_course` docstring (still said "every current
  participant's memory bank") → owner's course-memory node.
- Decision 003 (learner artifact retention exception) and 005 ("every
  current participant receives a user-owned course-memory record" + the
  stale copy-once wording) amended to the decision-007 model: owner-only
  node, copy-any-time, learners get archive access not memory.
- Generation-task vocabulary renamed end to end — before Milestone 1
  wires real model calls, so no persisted ledger rows carry the old
  string: `EXTRACT_MEMORY` → `EXTRACT_KNOWLEDGE` (stage enum),
  `extract_memory` → `extract_knowledge` (ingestion.toml stage),
  `memory_extraction` → `course_knowledge_extraction`
  (KNOWN_GENERATION_TASKS + tiers.toml v6 routing keys; loader enforces
  task coverage so the rename is validated at load time). system.md §3
  pipeline text, §6a task list/charging, and decisions 002/004 updated.
- system.md analogies/diagrams: "memory store" → knowledge store,
  "Course memory — study guide" → course knowledge, tutor-analogy wording,
  data-flow line now names the memory tree explicitly (root + course node
  + knowledge + student model).
- §7 tutor-presentation section reframed: presentation is a user-memory
  (root) concern; behavior instructions live only in the root, never in
  course memory or knowledge (decision 007 invariant 2). project.md
  matching paragraph updated.
- Legacy-naming notes added where applied tables keep old names:
  system.md §2.3 bullet for `memory_objects`/`memory_id`/
  `MEMORY_OBJECT_EVIDENCE` (course-knowledge objects), and schema
  docstrings in evidence.py (Citation, MemoryObjectEvidence).
- enrollments.py router docstring: email-visibility line superseded by
  the members-list ruling; memory-content note added.
- Test names/docstrings renamed (`test_memory_bank_*` →
  `test_course_memory_*`); notes.md history untouched (append-only).
- Applied-migration comments still contain old wording (015/016/018) —
  uneditable by the append-only rule; cosmetic only, mapped by decision
  007. Same class as the recorded 013/018 cosmetic notes.
Gate: 193 tests, ruff, mypy, git diff --check all green.

## Storage accounting + ingestion spend ratified and implemented (2026-09-11)

Operator decisions from the storage conversation, now in code:

1. **Quota = stored bytes, ratified.** A file's quota cost is its
   compressed stored size (post-gzip). "Fairness" across compressibility
   was explicitly deprioritized in favor of a consistent, inspectable
   allocation number per user. No change to size_bytes semantics; no
   migration for existing rows.
2. **Decompression is a read-time safety cap, not a quota.** New
   `configs/lifecycle.toml` `[decompression] max_decompressed_bytes`
   (200 MB; config version 3). `storage.read_stored` now streams gzip in
   chunks and raises `DecompressionLimitExceededError` when expansion
   exceeds the cap — it no longer decompresses whole-buffer into memory.
   Identity files are size-checked against the cap before read. The
   mandatory keyword-only cap parameter makes the unbounded read
   impossible to reintroduce by accident. Note: our own gzip cannot
   expand past the raw-body ceiling (we compressed what the ceiling
   already capped); the cap exists for stored files whose *content* is a
   compressed container and for defense in depth.
3. **Ingestion gets its own weekly token pool.** `generation_ledger`
   gained `spend_kind` ('generation' | 'ingestion', migration 022,
   historical rows default to generation). `spend_repo.weekly_spend` and
   `budget.check_budget` take the pool; `TierPolicy.ingestion_token_budget`
   added (tiers.toml v7, equal to the generation budget for now — the
   pool is a guardrail, not a ration). An upload's model calls can never
   drain the budget a user needs for interactive answers.
4. **Ingestion tasks route to the cheap model.** tiers.toml now routes
   `course_knowledge_extraction` to `small-stable-toc` alongside
   `toc_update` (both tiers). Reasoning-off for ingestion is a provider
   call-parameter concern, deferred to Milestone 1 wiring when a real
   provider client exists; the routing seam is in place. Extraction
   quality is still gated by the eval-set rule: cheap is the default,
   upgrade only on a documented baseline failure.
5. **Free-tier provider check still open.** Any cheap/free ingestion
   provider must pass the same no-retention verification as the main
   provider before use (golden rule 4). Blocked on picking the provider.

Gate: 198 tests, ruff, mypy, git diff --check all green.

## Review fixes on the storage/spend first pass (2026-09-11, same day)

Operator-ratified review found real issues; all fixed before commit:

- **Cap raised to cover the paid raw ceiling (1 GB).** The first-pass
  200 MB cap would have made large legitimate paid uploads unreadable
  (quota passes at stored bytes, read raises). New invariant, pinned by
  test: `max_decompressed_bytes >= max(max_raw_upload_bytes)` across
  tiers. Config comment documents the derivation.
- **No false fallback on spend_kind.** `check_budget`, `weekly_spend`,
  `record_generation` now take `spend_kind` as a required keyword — no
  production callers exist, so the cheapest moment to make the wrong-pool
  mistake unrepresentable is now. `record_generation` rejects raw strings
  with a clean ValueError instead of a psycopg CheckViolation;
  `GenerationLedgerEntry.spend_kind` validates as the SpendKind enum.
- **Loader strictness.** `lifecycle_config` reads
  `[decompression] max_decompressed_bytes` via required keys (fails
  loudly), dropping the silent hardcoded default; test pins it.
- **Error mapping.** gzip branch maps only EOFError/BadGzipFile to
  "corrupt stream"; FileNotFoundError/permissions propagate as-is,
  matching the identity branch.
- **Tests resolve the cap via load_lifecycle_policy** instead of
  hardcoding, exercising the config→caller resolution path the seam
  mandates.
- Not adopted (deliberate): whole-file buffering in read_stored stays for
  now (cap-bounded, fine at current scale); the Milestone 1 parser seam
  should take a stream. DB CHECK on spend_kind accepted (mild tension
  with free-string convention — spend kinds are billing semantics, not
  extensible content types).

Gate: 201 tests, ruff, mypy, git diff --check all green.

## Milestone 1 phase 1: ingestion pipeline wired end to end (2026-09-11)

The M1 ingestion skeleton is now real code against the real DB:

- **New modules** (`src/backend/ingest/`): `extract.py` (text + locators:
  PDF pages via pypdf, markdown sections, plain-text line ranges),
  `chunking.py` (token-bounded chunks, ~4 chars/token, paragraph→
  sentence→whitespace→hard-cut boundaries, chunks map to overlapping
  locators), `runs.py` (DB run ledger: run + stage rows, claims via
  FOR UPDATE SKIP LOCKED), `orchestrator.py` (binds executor + handlers
  + ledger into `run_ingestion`).
- **Provider seam** (`common/provider.py`): the single model-call
  function (task+prompt in, result out). Routing, billing-pool checks
  (ingestion tasks must bill the ingestion pool), and ledger recording
  are wired; the HTTP call is a deliberate `ProviderUnavailableError`
  until the operator picks a provider and verifies no-retention. Only
  this file changes when a real client lands.
- **Migration 023**: `sources.extracted_text` (retrieval reads text, not
  binaries; raw files stay untouched on disk).
- **Commit discipline** (the interesting design outcome): the run row
  commits at creation, each succeeded stage transition commits with its
  output, and a failed run commits its audit trail in a fresh
  transaction after rollback. Consequence: completed stage output
  survives a later stage's failure — a retry does not redo committed
  stages; partial derived rows from the failing stage roll back.
  Inspectability is preserved: run/stage/error messages are always
  queryable, including the provider error inside the failed stage row.
- **Queue**: `queue_upload` hands uploaded sources to
  `pending_ingestion`; `claim_pending_sources` is the SKIP LOCKED worker
  seam (no worker loop yet — that is the next M1 step, with the API
  handoff).
- **Model stages** (`update_toc`, `extract_knowledge`): prompts built,
  routed through the provider seam, billed to the ingestion pool. They
  currently fail runs (no provider), which the tests assert as the
  honest current state; swapping in a real provider turns the same
  pipeline fully green without touching orchestrator code.
- pypdf added as a dependency (PDF page extraction); `pyproject.toml`
  updated.

Gate: 222 tests (21 new), ruff, mypy, git diff --check all green.
Not committed yet — review first.

## M1 ingestion review: 21 findings, all fixed before commit (2026-09-11)

External review of the ingestion batch found 21 issues (3 correctness,
several convention violations, several smaller). All fixed:

- **Citation alignment (golden rule 1)**: PDF locators were built without
  the join separator, so every page after the first drifted N-1 chars —
  page 50 cited 49 chars early. Locators and text now share one join
  (`_join_pages`/`_pdf_locators` built from the same page_texts), with a
  regression test asserting each page span slices out exactly its own
  page. Markdown heading scan now masks code fences with equal-length
  spaces (offsets preserved, in-fence `#` no longer a heading).
- **Money wiring was dead**: nothing called check_budget or recorded
  spend; generate took caller-supplied token counts (inverted). The
  provider seam now gates (check_budget), calls, and records inside one
  function; token counts come from `_call_provider`'s return, never the
  caller. Tier is resolved+verified inside the seam (no caller-supplied
  policy). Pool routing is symmetric and lives in schemas/base.py
  (INGESTION_TASKS) — the single source of truth. A stubbed-provider test
  proves a full pipeline run goes green AND writes ingestion-pool ledger
  rows with nonzero tokens; a drained-pool test proves the gate blocks
  before any provider call.
- **Failed sources were a dead end**: mark_source_failed filtered on
  status='uploaded' and nothing cleared queue rows — failures were
  permanently unretryable with zombie queue rows. Failure now clears the
  queue row; `requeue_failed_source` is the deliberate failed→uploaded
  retry path; claims require status='uploaded' AND claimed_at IS NULL.
- **The SKIP LOCKED claim couldn't work**: run_ingestion's first commit
  released the row lock mid-claim, letting a second worker double-claim.
  Claims are now a persistent state transition (claimed_at + claimed_runs,
  migration 024), not a lock. The IN-subquery silently dropped both LIMIT
  and SKIP LOCKED; rewritten as CTE.
- **False-success guard**: model stages fail on empty provider output
  (EmptyModelError) — a provider landing cannot silently produce
  SUCCEEDED runs with an empty knowledge base. The stub still doesn't
  write TOC/knowledge rows; that lands with the real provider output
  format (honest state, tests assert it).
- **Dispatch trapdoor closed**: unsupported mimes (zip/png/mp4) raise
  UnsupportedSourceTypeError at dispatch instead of raw
  UnicodeDecodeError after prior stages committed. Whitelist: PDF, plain
  text, markdown, csv, json, xml, yaml. Scanned/image-only PDFs raise
  EmptyExtractionError instead of "succeeding" with nothing retrievable.
- **BOM + cp1252**: utf-8-sig decode (Windows BOM no longer breaks the
  first heading), cp1252 fallback for legacy lecture notes.
- **extracted_text column dropped** (migration 024): it duplicated
  chunks in a Postgres row value approaching the 1 GB ceiling. Text
  lives in chunks only; raw stays on disk.
- **Honest docs**: orchestrator docstring now says retries re-execute
  from the top (safe, not free); the earlier notes.md claim "billed to
  the ingestion pool" was false at the time and is now true; "only this
  file changes when a provider lands" corrected — `_call_provider` +
  `_parse_usage` plus the row-writing of real output change.
- **Tunables in config** (ingestion.toml v2): chunk_max_tokens=512,
  prompt_window_chars=8000 (placeholder window acknowledged — TOC stage
  is structurally blind past it until the provider formats real output).
- **Convention sweep**: all raw SQL moved to queries/ingestion.sql
  (source_row, deletes, requeue_row, enqueue_pending); queue_upload's
  query no longer lives in course_archives.sql; failure audit typed
  against IngestionPipelineError (was duck-typed Any); source facts
  fetched once via fetch_source_row and passed through the constructor
  (no lazy DB reads, no private reach-ins, no -O-silenced asserts).
- Prompt-injection acknowledged in the orchestrator docstring: uploaded
  text is inlined into shared-course prompts unescaped; input marking is
  a provider-landing requirement, part of the go-live gate.

Design decision for the worker (not built yet): claims are persistent
(claimed_at), so the future worker marks claimed_at and requeues stale
claims (claimed_runs counter is the watchdog input). This was the design
space the review's #4 demanded — it now exists.

Gate: 233 tests, ruff, mypy, git diff --check all green.

## Open: retrieval + generation design — flagged for dedicated conversations (2026-09-11)

Generation and retrieval are the highest-ambiguity areas of the project
(structure, scope, and product behavior all genuinely open). Operator
wants to break each down properly in its own conversation rather than
decide inline. Each item below gets its own revisit; nothing here is
final.

**Fork A — retrieval mechanism.** History: the original plan was
embeddings + vector DB; operator rejected it on two grounds — (1) with
lots of similar course text, embedding search returns many near-duplicate
hits (precision worry at the top of the ranking); (2) the cascading-TOC
idea fit the domain better. Current ratified context (do not re-litigate
in the revisit): NO embeddings in the baseline (decision 001-era rule:
retrieval replaces embedding similarity; models earn their role on a
documented baseline failure). Candidate order when revisited:
tsvector keyword baseline first, then TOC-guided routing as a measured
upgrade that must beat the baseline on the eval set before becoming
default.

**Fork B — behavior when retrieval finds nothing relevant.** Options on
the table: strict refusal ("this isn't in your materials"), ungrounded
answer clearly flagged, or an explicit opt-in toggle. Operator's product
philosophy call; default lean recorded so far is strict refusal. Not
final — this is a trust/product-positioning decision.

**Fork C — answer shape and citation contract.** Working direction: every
factual claim carries an inline locator citation; the retrieval trace
(chunks, scores, prompt) stored on every answer. Detail level of
citation rendering, per-claim vs per-answer granularity, and how
"unsupported claim" is rendered are open.

**Fork D — first-ship scope.** Working direction: single-turn grounded
Q&A first; conversation threads and follow-up memory not load-bearing
until the basics are solid. Open.

**Fork E — TOC's role at query time.** TOC is written at ingestion
(update_toc stage) but is not load-bearing for retrieval until the
TOC-guided routing beats the keyword baseline on the eval set (golden
rule 5). The comparison is the deliverable; "smarter" is not a
justification by itself.

**Also open, related**: eval question set for retrieval+answer quality
(hand-written from real uploads, committed to data/eval/); the "did the
chunk actually support the claim" audit loop; conversation storage scope
(schema exists, not load-bearing).

Context for the revisit: the ingestion side is built and aligned
(233 tests green, locators are citation-grade after the drift fix);
retrieval reads chunks+locators directly, so nothing blocks Fork A work
except the conversation itself.

## Ratified: Fork A — hybrid three-layer retrieval (2026-09-12)

Operator decision after the Fork A conversation. Supersedes the "TOC alone,
embeddings only on failure" posture; the near-duplicate-precision objection
to embeddings is answered by the fusion layer (candidate merging + ranking
caps), not by excluding embeddings.

**All three layers run; every layer is a candidate generator, not an
authority:**

1. **TOC routing** — question → TOC entries (titles, descriptions, concept
   refs) → chunks under those entries. Coarse, canonical location. Query-time
   mechanism (static match vs model-routed) is still open — see below.
2. **Keyword (tsvector)** — term overlap over chunks. Catches scattered
   mentions the TOC misses ("when did we USE linearity" → chapters 5–6, not
   just the chapter 2 definition).
3. **Embeddings (semantic)** — vector similarity over chunks for paraphrase
   cases. Stored at ingestion by a separate embedding model; query time is
   vector-only.

**Fusion + citation contract = the harness:** all three layers emit chunk
candidates; fusion merges and ranks; every surviving chunk carries its
locator. Citations are layer-agnostic — the same contract regardless of
which layer surfaced the chunk. Retrieval strategy is an internal, swappable
detail; trust lives at the citation boundary. The operator's near-duplicate
concern (many similar hits from similar course text) is handled as a ranking
problem at fusion (per-source/per-chapter candidate caps), not by excluding
embeddings.

**Consequences:**
- Decision record needed (docs/decisions/008) amending the no-embeddings
  rule: embeddings are now an always-on third signal in a fusion, not a
  fallback-for-TOC-failure. Cross-model alignment concern is superseded by
  the fusion design; a separate embedding model is still subject to the
  no-retention provider check.
- Eval set is now load-bearing: recall@k per layer AND fused; fusion must
  beat the best single layer on the eval or it loses (golden rule 5 applies
  to combinations). Eval questions + marked answer chunks go to data/eval/.
- Build order implication: TOC + keyword are buildable now (no model call at
  query time, no new provider); embeddings wait for the provider pick +
  migration (embedding column/vector index). Ship order: keyword → TOC
  static → fusion → model-routed → embeddings, each measured against the
  previous.

**Still open within Fork A:**
- Query-time TOC matching: static (entries + synonyms, no model call) vs
  model-routed per query. Leaning static-first, model upgrade measured.
- Embedding model choice + storage (pgvector) — gated on provider pick.
- Fusion ranking policy (weights, caps, dedup) — tunables in configs/, not
  hardcoded.

## Fork A implemented: the retrieval funnel is real code (2026-09-13)

Decision 008 revised after the design conversation (fusion = mixing not
scoring; seams are built up front and activate as their data arrives —
"build the seam whenever, turn it on when the data's real"). Then
implemented:

- **`src/backend/retrieval/`**: `funnel.py` (four seams + fusion),
  `config.py` + `configs/retrieval.toml` v1 (all funnel tunables:
  per-seam limits, final_k, per-source cap, embedding-only quota),
  `trace.py` (per-query trace with layer attribution), `evals.py`
  (recall@k eval runner; cases in `data/eval/retrieval/cases.json`,
  matched by locator label so cases survive re-ingestion).
- **Migration 025**: `chunk_embeddings` (float8[] now, pgvector swap is a
  later migration) + `chunks.search_vector` generated tsvector with GIN
  index.
- **Fusion is mixing, not scoring** — exactly as ratified: keyword/TOC/
  dependency/embedding candidates union with layer attribution
  (multi-layer hits merge layers, max rank), ordering is embedding rank
  when present else keyword rank, per-source cap bounds the near-duplicate
  flood, embedding-only candidates enter through an explicit quota, final
  cut to final_k. No weighted score arithmetic anywhere.
- **Dormant seams verified by tests**: no TOC entries / no dependency
  edges / no embeddings → empty candidates, no errors, no contribution.
- **Trace**: `retrieval_traces.retrieved_chunk_ids` jsonb now carries the
  full audit payload (ordered chunk ids + layer_contribution +
  matched_concept_ids).

Bugs caught by my own tests during the build (for the reviewer's
attention): (1) tsvector AND semantics missed partial-query chunks — the
keyword seam uses OR now; (2) Postgres has no float8[]*float8[] operator —
dot products computed via unnest-zip SUM; (3) the fusion merge loop
originally omitted the embeddings dict — embedding-only candidates could
never enter (the quota was dead code); caught by the quota test; (4) the
embedding seam read a `rank` column that the query named `dot` — ranks
were silently re-derived from row order; (5) psycopg's client-side parser
trips on literal `%` inside SQL comments — wildcard comments removed.

Gate: 246 tests (13 retrieval), ruff, mypy green.

## Retrieval-batch review: 16 findings, all fixed (2026-09-13)

External review (with live DB probes) of the funnel batch. All findings
fixed before commit:

- **Keyword crash on math syntax (high)**: to_tsquery treats ( ) < > !
  & | : * as operators; "f(x) = x^2" killed retrieve() with a SyntaxError.
  The seam now tokenizes with a strict [a-z0-9]+ regex BEFORE any SQL —
  operator characters cannot reach the parser. Single-char tokens dropped.
  Regression tests: math queries and a hostile-query battery (unbalanced
  parens, <-> operators, empty strings).
- **Eval harness false-pass modes (high)**: substring label matching made
  "page 1" hit "page 12"; any() contradicted the docstring's all-expected
  rule; the decision-008 kill-switch metric (recall per seam AND fused)
  was not computed; unresolved course tags silently passed. The runner is
  rewritten: exact label set membership, ALL expected labels required,
  per-seam recall AND fused recall computed, unresolved cases reported
  and excluded (never a pass), and an EvalSummary that answers the
  decision rule directly ("fusion beats best single: yes/no"). Two
  eval-runner tests pin the exact-label and unresolved semantics.
- **Embedding dimension mismatch (high)**: unnest zips unequal arrays by
  silent truncation — a model swap would rank garbage without error.
  cardinality() equality guard added in SQL; test pins it.
- **Trace lost the WHY (high)**: per-chunk layer attribution was dropped
  at record_trace despite Candidate.layers holding it; toc_entry_ids was
  dead (never populated). Traces now store per_chunk_layers (each cited
  chunk with the seams that surfaced it); toc_seam returns matched entry
  ids and retrieve() passes them through to the trace. Test asserts the
  payload shape.
- **TOC seam raw-substring ILIKE (medium)**: %word% with no boundaries
  matched "we" → "Week"/"power"/"answer"; user wildcards unescaped. The
  seam now full-text matches (to_tsvector on title+description, stemmed,
  stopword-filtered — consistent with the keyword seam); locator_id IS
  NULL entries excluded explicitly (they have no chunks).
- **Single-letter concept matches (medium)**: position() substring match
  made concepts named f/R/T match nearly every query. Word-boundary
  regex matching + 2-char minimum (enforced in SQL and conceptually in
  the tokenizer). Test pins "rat" not matching "iteration".
- **Dependency seam precision + nondeterminism (medium)**: OR-join
  defeated both indexes and SELECT DISTINCT...LIMIT without ORDER BY made
  runs irreproducible. Rewritten as UNION (index-friendly per branch) +
  deterministic ORDER BY. KNOWN GAP documented in SQL: memory_objects
  links concepts to sources not locators, so the seam is coarse until a
  locator link migration exists — flagged as a schema TODO, not hidden.
- **course_by_tag nondeterminism (medium)**: exact-match-first + stable
  secondary ordering. (Also discovered the hard way: psycopg named-param
  mode requires literal % escaped as %% inside query text, and courses has
  no created_at column.)
- **Smaller**: eval embedding model name now a parameter (real model name
  from config when a provider exists); migration 025 comment corrected
  (absence = no row, never NULL); rank unit-mixing documented on
  Candidate (seam-local, never compared cross-seam); prereq_id index
  (migration 026 — 025 was already applied, so it got its own file);
  trailing newlines restored; system.md §7 glued sentence reattached to
  the TOC bullet correctly; per-source-cap test's inline SQL shared via
  fixture helper where practical.

Two psycopg client-side parser gotchas worth remembering (recorded here
so the next batch doesn't rediscover them): literal % must be %% in
named-param SQL INCLUDING comments adjacent to placeholders, and jsonb
columns return parsed dicts, not strings.

Gate: 255 tests (22 retrieval, +9 review regressions), ruff, mypy green.

## M1 close-out: ingestion worker + upload handoff (2026-09-13)

The ingestion loop is now closed end to end: upload → queue → worker →
pipeline → terminal state, all inspectable.

- **Worker** (`src/backend/ingest/worker.py`): `process_batch` claims
  bounded batches via the persistent-claim seam, resolves the course
  owner + account (tier verified inside the provider seam at call time),
  runs `run_ingestion` per source. Pipeline failures are already recorded
  by the run ledger; unexpected errors get a claim-cleanup path so no row
  is stranded. `run_forever` mirrors archive_maintenance's loop shape and
  is wired into the app lifespan (main.py) alongside it.
- **Stale-claim recovery**: rows claimed by a crashed worker become
  re-claimable after STALE_CLAIM_AFTER (30 min, module constant); the
  claimed_runs counter keeps the event visible. Test pins
  claim → age-out → reclaim.
- **Upload handoff**: `sources_repo.upload_source` now enqueues the
  source into pending_ingestion in the SAME transaction as the insert
  (reason: uploaded_new_source) — no window where a source exists but is
  unqueued. The copy seam's enqueue (copied_from_archive:*) was already
  in place.
- **Tests (5)**: upload enqueues; worker batch records failure state
  honestly (provider-less = failed run, no zombie queue row); stubbed
  provider end-to-end goes indexed + queue cleared; requeue-after-failure
  produces a second run; stale claims release.

Honest gap kept visible: the worker runs in-process with the API (small
user base); a separate worker process is the scaling seam — the loop is
already a to_thread pattern so lifting it out is mechanical. Model
stages still fail closed (no provider); the stubbed-provider test proves
the success path works the moment a real client lands.

Gate: 260 tests, ruff, mypy green.

## Review pass on the retrieval + worker batch: small fixes applied (2026-09-16)

End-to-end review of `3eea6d6`. Everything below is fixed; two findings are
left open because they are design calls, not bugs (see the end).

- **Concept-name regex injection (high, was a live crash)**: the dependency
  seam's matcher interpolated model-extracted concept names straight into a
  POSIX regex. Verified against the DB: a name like `f(x`, `a**b` or `x{2,`
  raises InvalidRegularExpression, and because `concept_matches` runs first
  in `retrieve()`, ONE bad extracted name broke every question on that
  course — keyword seam and all. Unescaped metacharacters also matched
  wrongly in both directions: `a+b` matched "aaab", `O(n)` and `f(x)` (the
  common case in a maths/CS course) never matched themselves. Names and
  synonyms now go through `regexp_replace` before they reach the engine.
  Note for next time: Postgres uses `\1` backreferences in the replacement,
  NOT sed/Oracle's `&` — `'\&'` silently substitutes a literal `&` and
  looks like it works. Three regression tests, each confirmed to fail
  against the old SQL.
- **Eval compared seams at k=20 against fusion at k=10 (high)**: per-seam
  recall used each seam's full candidate dict (`keyword_limit` etc.) while
  fused recall used the post-`final_k`, post-cap set. So
  `fusion_beats_best_single` — decision 008's kill switch — was measuring
  the k gap, with fusion handicapped 2:1. Seams are now truncated to
  `final_k` via `_top()` before scoring. Worth remembering: the eval was
  wrong in the direction that would have made us delete a working design.
- **Eval did double the DB work**: `run_eval` computed all four seams and
  then called `funnel.retrieve()`, which re-ran all four plus the concept
  match. It now fuses the seams it already has.
- **Worker blocked shutdown**: `process_batch`'s `while True` drained the
  WHOLE queue, inside `asyncio.to_thread`. Threads are not cancellable, so
  lifespan shutdown returned instantly while the thread kept ingesting —
  unbounded hang on a big backlog. Takes a `should_stop` callback now,
  checked between rounds and between sources; `run_forever` passes
  `stop.is_set`.
- **`claimed_runs` was incrementing into the dark**: both worker docstrings
  called it "the inspectable signal," but nothing read it. Stale-claim
  releases now log a warning with the row count.
- **Smaller**: dead `chunks_by_ids` and `queued_at_for` queries removed
  (added last batch, never called); redundant `locators` join dropped from
  `toc_candidates` (the chunks join already excludes NULL locators);
  `dependency_expansion` branches no longer select `via_concept_id` (it was
  unused, and it defeated the UNION dedupe — a chunk reachable both as
  prereq and dependent burned two LIMIT slots then collapsed to one in
  Python, so the seam returned fewer distinct chunks than its limit);
  migration 027 indexes `chunk_embeddings(model)`, which the embedding seam
  filters on every query; system.md and decision 008's title said
  "three-layer" while the code has four seams.

Left open — design calls, not bugs:

1. **`per_source_cap` punishes the single-source course.** The cap is keyed
   on `source_id` at 4, so a course with one uploaded PDF can never return
   more than 4 chunks no matter what `final_k` says — and one PDF is the
   likely first-user shape. Every fusion test gives each chunk its own
   source, so nothing catches it. Decision 008 says "per-source/per-chapter";
   only per-source exists. Options: scale with source count, floor it at
   `final_k` when the course has one source, or key it on chapter/locator.
2. **Fusion does compare ranks across seams**, despite `Candidate`'s
   docstring promising it never does. `sort_key` has two buckets, and bucket
   1 sorts keyword (`ts_rank`, ~0.06), TOC (hardcoded 0.0) and dependency
   (`-position`) together — so the order is always keyword > TOC >
   dependency, as an accident of unit choice rather than a decision, and the
   config cannot tune it. That also inverts 008's framing, where TOC is the
   scope-giver and keyword the precision net. Related: embeddings only rank
   chunks the embedding seam itself returned, so a keyword hit outside the
   vector top-k sorts below every embedding hit — embeddings are a fifth
   candidate generator that wins ties, not "the relevance ordering over the
   merged set" as 008 describes. Reconcile doc and code before turning
   embeddings on, or the measurement gets read through the wrong claim.

Also still true and worth not forgetting: `retrieve()` and `record_trace()`
have no callers outside `evals.py`, and `retrieve()` takes a `course_id` it
trusts completely — no enrollment check. The seams all filter by course so
retrieval cannot cross courses, but nothing verifies the CALLER may read
that course. That check needs to land with the tutor-flow wiring.

Gate: 263 tests (28 retrieval, +3 regex regressions), ruff, mypy green.

## Full-codebase edge-case sweep (2026-09-16)

Swept all ~5,800 lines of backend source, not just the retrieval batch.
Findings below were probed against the live DB, not reasoned about. Fixed
in this pass unless marked open.

- **Markdown with no headings failed ingestion outright (high)**. Section
  locators came only from `#` headings, so a plain .md of notes produced
  ZERO locators, every chunk mapped to none, and build_chunks' "citation
  grounding is mandatory" check failed the whole source. Plain notes are
  ordinary input. The same gap had a second, quieter half: text before the
  first heading was uncovered, so a long preamble orphaned its chunks, and
  a short preamble sharing a chunk with the first heading was CITED AS
  that heading — a wrong citation, which is worse than a missing one and a
  direct golden-rule-1 problem. Uncovered regions now fall back to the same
  line-range locators plain text uses. Two tests, both confirmed failing
  against the old code.
- **`read_stored` let `zlib.error` escape (medium)**. It caught
  BadGzipFile and EOFError, but a valid gzip header with a corrupt deflate
  body — the likeliest real corruption — raises `zlib.error` and bypassed
  the documented `ValueError("stored gzip stream is corrupt")`. Caught now.
- **NUL bytes survived `sanitize_display_name` (medium)**. Postgres text
  columns reject NUL outright (verified), so an upload whose filename
  carried one became a 500 from inside the insert. The orphan-cleanup path
  did hold — no stranded file — but the upload was wasted and the error was
  wrong. Control characters are stripped now.
- **`consume_token` turned a lost race into a 500 (medium)**. Its
  `assert used is not None` fires when a concurrent request claims the
  token between this transaction's SELECT and its guarded UPDATE.
  Reproduced with two connections: the loser got AssertionError, not
  TokenRejectedError. Double-clicked reset links and mail scanners that
  prefetch URLs make this a routine event, not a rare one. Note this is
  the same class already logged at notes.md ~line 733 ("AssertionError
  500s and vanish under python -O") — one surviving instance, and the only
  one: every other assert in the codebase sits on an INSERT/aggregate
  RETURNING that cannot return no row (`rotate_join_code`, the other
  conditional update, already handles None correctly).
- **Email had no length bound (medium)**. Register/login/reset accepted
  unbounded email strings: 100k chars stored fine, 1M chars produced a raw
  `ProgramLimitExceeded` 500 from the btree index. Bounded to 254.
- **`archive_maintenance.run_once` blocked shutdown** the same way the
  ingestion worker did (non-cancellable `to_thread`). Same `should_stop`
  treatment, checked between phases.
- **`codes._CODE_RE` hardcoded 16** instead of using `CODE_LENGTH`, so
  changing the constant would silently desync the validator. Uses it now.

Open — needs a decision, not a fix:

1. **A password reset does not invalidate existing sessions.** Verified: a
   JWT minted before `update_password` still decodes afterwards, and
   `jwt_expire_minutes` defaults to 7 days. If the reset was prompted by a
   compromise, the attacker keeps access for a week. There is no
   `token_version` / `password_changed_at` to check `iat` against, so this
   needs a column + a check in `current_user`.
2. **`free_tier_overhead()` is never called.** budget.py defines it,
   tiers.toml carries `free_tier_overhead_percent`, `record_generation`
   takes `overhead_tokens`, and test_spend.py tests the function — but
   `provider.generate`, the only place generation spend is recorded, never
   passes it. Free-tier overhead is configured, tested, and inert. Wiring
   it starts charging free users more, so it is a product call.
3. **PDFs never pass through the capped read seam.** PDFs are in
   `_INCOMPRESSIBLE_EXACT`, so they always store as identity, and
   `_pdf_page_texts`' identity branch calls `path.read_bytes()` directly
   instead of `read_stored`. The one file type that always takes that path
   is the one type that skips the decompression ceiling. Upload-time raw
   ceiling still bounds it, so this is a bypassed defense-in-depth seam
   rather than an unbounded read.
4. **`migrate.py` silently skips malformed filenames.** `^(\d{3})_.+\.sql$`
   means `27_x.sql` or `027-x.sql` is ignored with no error, and two files
   sharing a version number mean the second never runs. Both fail silent.

Also noted, not acted on: `get_settings()` re-reads .env from disk on every
call (including once per request through `decode_access_token`), and
`CHARS_PER_TOKEN = 4` under-counts badly for CJK text — both already
documented as approximations.

Gate: 268 tests (+5 this pass), ruff, mypy green.

## Review of the edge-case sweep (2026-09-16)

Reviewed the other model's sweep pass. Verified against the live DB, not
just read: the regex-escape fix works (unescaped `f(x` really raises
InvalidRegularExpression; the shipped `regexp_replace` escapes correctly
and matches `f(x`/`o(n)` in the real `concept_matches` path), and the
full gate reproduces (270 tests, ruff, mypy green). The sweep's own
"Open" list got pruned against decisions already on file:

- **Two "open" items were not decisions — fixed now.**
  1. **PDFs bypassing the capped read seam**: `read_stored`'s identity
     branch already applies `max_decompressed_bytes` to identity files,
     so routing `_pdf_page_texts`'s identity branch through it is a
     one-line fix, not a design call. Done; a test pins that an
     identity-encoded PDF over the cap raises
     DecompressionLimitExceededError (via a patched read_stored with a
     lowered cap — the real 1 GB policy value is not testable directly).
  2. **`free_tier_overhead` never wired**: decision 004 already ratified
     this (5% of input+output, applied at record time, never gating).
     `provider.generate` now passes
     `overhead_tokens=free_tier_overhead(policy, input+output)`. The two
     provider-seam assertions that pinned exact spend picked up the +5%
     (120→126, 60→63); a paid-tier test pins 0%.
- **Genuinely open — kept as decisions, not silently deferred:**
  password reset not invalidating old JWTs (needs a
  token_version/password_changed_at column + a check in current_user —
  a real schema change); `per_source_cap` vs the single-source course
  (decision 008 says "per-source/per-chapter"; needs a ratification
  call); fusion's rank-bucket ordering contradicting `Candidate`'s
  docstring and 008's framing (must reconcile before embeddings turn
  on); `migrate.py` silently skipping malformed filenames; the
  enrollment check for `retrieve()` (lands with tutor-flow wiring);
  free-tier CJK token under-count (documented approximation).
- Sweep findings themselves re-checked and all confirmed real: the
  markdown no-heading/preamble locator fix, zlib.error catch, NUL-byte
  filename sanitize, email length bounds, worker/maintenance shutdown
  cooperation, lost-race token consume, migration index 027, dead-query
  removal, UNION dedupe fix.

Gate: 270 tests (+2), ruff, mypy green.

## Password reset invalidates sessions + password length policy (2026-09-16)

User-directed fixes, scoped to exactly two changes.

- **Reset kills pre-reset sessions.** New `users.password_changed_at`
  column (migration 028, backfilled with now() for existing password
  rows so no live session broke). Every token carries a `stamp` claim =
  the stamp at mint time; `current_user` rejects tokens whose stamp
  predates the live one. Stamp is **microseconds**, not seconds — the
  same-second collision is real (create at .011s, reset at .321s in one
  probe run would have compared equal at second precision and left the
  attacker's session alive). Shared helper `auth.password_stamp`;
  None -> 0 so the claim is always comparable. End-to-end test: register
  -> me works -> reset -> same token now 401 -> new login works.
- **Password policy: 12-24 characters.** `MAX_PASSWORD_LENGTH = 24`
  added to `validate_password` (the 72-byte bcrypt guard stays, it
  prevents silent truncation, not a policy bound). Register and
  password-reset-confirm both funnel through validate_password, so both
  enforce it. Login intentionally does NOT pre-reject over-long
  passwords: verification just fails into the same 401 as a wrong
  password (anti-enumeration unchanged). One test fixture (25 chars)
  shortened.

Gate: 273 tests (+4: stamp roundtrip, stamp-0, invalidation flow,
24/25-char boundary), ruff, mypy, migrations clean.

## per_source_cap no longer starves single-source courses (2026-09-16)

User-ratified fix of sweep open-item #3. The cap is flood control, not a
result ceiling: with one contributing source (the likely first-user shape)
it used to bound the final set at per_source_cap (4) no matter what
final_k said.

Rule: effective_cap = max(per_source_cap, ceil(final_k / contributing
sources)). With >= 3 contributing sources this is just per_source_cap
(4); with 1 it stops binding entirely. Config value unchanged — the
behavior now matches decision 008's "per-source/per-chapter" intent.

Tests: single-source course now surfaces all 5 chunks (was exactly 2);
3-source course with final_k=6 still floods-caps at 2+2+2.

Gate: 274 tests, ruff, mypy green.

## Fusion rebuilt: normalize + allocate (retrieval.toml v2) (2026-09-16)

User-ratified redesign replacing the per-source cap, resolving sweep open
items #3 and #4 as one pipeline (user's framing: "softmax per source" and
"order AND normalization").

- **Normalize first.** Each seam's ranks min-max into 0..1 within the
  seam (embedding dots keep direction; arrival-ordered seams flip sign;
  all-equal seams normalize to 0.5). This is what makes cross-seam
  comparison legal — the raw units (ts_rank ~0.06 vs position 7,8,9)
  were the "ordering is an accident" problem. Caught my own bug here:
  the layers-membership check intersected a set of STRINGS with a set
  of FROZENSETS (always empty), silently sign-flipping embeddings;
  fixed by passing the seam's layer name explicitly.
- **Allocate second.** Source relevance = its best chunk's normalized
  rank from any seam (best-chunk, NOT chunk count — volume must not
  reward rambling lectures). final_k slots split proportionally with
  largest remainder (Hare quota, deterministic). Guardrails: one-slot
  floor per contributing source; availability clamping with reflow;
  backfill so final_k is met when candidates exist.
- **Embedding-only quota semantics fixed along the way:** the quota
  exists to keep semantic expansion from displacing grounded hits; when
  no grounded seam matched, embeddings ARE the evidence and the quota
  does not apply (was silently capping an embeddings-only course at 3).
- Config retrieval.toml v2: `per_source_cap` REMOVED (allocation
  replaces it). RetrievalPolicy field dropped.
- Tests: 4 new (proportional split 2/1/1 by relevance; floor + 
  availability 7/1; single source fills naturally; cross-seam max merge
  admits both) + 2 rewritten (equal relevance splits evenly 2/2/2;
  single source never starved). 30 retrieval total.
- Docs kept honest: decision 008 revision section, system.md §4,
  funnel/Candidate docstrings — the #4 lesson was doc-code drift.

Known tradeoff stated on purpose: relevance-by-best-chunk rewards
"explains it best" only as far as the scoring layer can tell; the eval
set judges, embeddings improve the allocation when they land.

Gate: 278 tests, ruff, mypy green.

## system.md: embedding architecture documented (§4a) (2026-09-16)

User-requested. New §4a captures the full embedding subsystem in one
place: storage (chunk_embeddings, model-keyed rows, indexed model column —
migrations 025/027), the ingestion-time embedding stage (provider-gated;
model-name rows make swaps safe without mass rewrites), the query-time
seam (native float8[] dot products, cardinality dimension guard, stable
ordering, pgvector swap as mechanical later step), normalization
direction (dots keep "higher = closer"; other seams flip), quota
semantics (expansion quota vs the no-grounded-evidence case), and the
eval kill switch. Stale spots synced: chunk-planning paragraph (§2.2,
embeddings live not "planned"), status header (retrieval implemented,
tutor planned), model table row, open-decisions entry, config-version
mention. No code changes; docs-only commit pending.

## Tutor answer endpoint (M1 close-out) (2026-09-16)

POST /courses/{course_id}/ask — the last big M1 piece. Retrieval, trace,
and the billed provider call share ONE transaction: a failed generation
rolls the trace back (an answer that never happened leaves no
evidence-shaped noise; test pins this).

- **Enrollment check** (the review's open item, resolved here): owner OR
  active enrollment; strangers get 404 (existence not disclosed). Test
  covers stranger, owner, and self-enrolled learner.
- **Fork B lean enforced**: empty retrieval = 404 "nothing in the course
  materials matches this question" — never an ungrounded answer.
- **Honest failure**: provider-unavailable = 503 with the real reason
  (the provider seam fails closed until the pick); budget exhausted =
  403. The endpoint never pretends to answer.
- **Fork C working direction in the prompt**: numbered chunks, "use ONLY
  the numbered material, cite as [n], say so plainly if not here."
- Answer, chunk_ids, and trace_id returned; the trace's stored
  retrieved_chunk_ids must equal the answer's citations (pinned).

Open remaining: citation rendering detail (per-claim granularity —
Fork C's open half), conversation threads (Fork D explicitly not
load-bearing), query-embedding plumbing when the provider lands (the
endpoint's embedding params exist and pass None until then).

Gate: 284 tests (+6 tutor), ruff, mypy green.

## Review of worker/retrieval batch #2: critical + high fixed (2026-09-18)

External review, 16 findings. Triage: 11 fixed now, 5 deferred as design
calls (listed at the end). All 290 tests, ruff, mypy green.

FIXED:
1. **Failed sources were citable (critical, golden rule 1)**: no seam
   filtered source.status — a source that died at update_toc kept its
   committed locators+chunks (deliberate, ledger-pinned) and retrieval
   surfaced them. All four seams now require status='indexed'. Explicit
   ruling: mid-run chunks are invisible; 'indexed' is the only citable
   state. Two tests (failed + uploaded states).
2. **ingestion_history had no caller (doc-code drift)**: wired into both
   terminal paths, queued_at captured before the queue row is deleted;
   helper _make_source now enqueues (mirroring the upload contract); a
   test pins the history row carrying the ORIGINAL queued_at.
3. **DB-level stage failure poisoned the ledger (critical)**: a psycopg
   error aborted the transaction, the observer's FAILED write raised
   InFailedSqlTransaction (uncatchable by the orchestrator's
   IngestionPipelineError handler), run stayed 'running' forever. Fixed
   with per-attempt SAVEPOINTs (savepoint/rollback/release around every
   handler call; pipeline takes conn). Test pins fence+rollback.
4. **NUL bytes in chunk text (the #3 trigger)**: binary-as-text/plain
   decoded via cp1252 fallback carrying \x00 → chunk insert 500.
   Stripped at read_decoded's choke point. Test.
12. **Un-ingestable mime stored + charged then failed (quota ratchet)**:
   upload boundary rejects against INGESTABLE_MIME_TYPES (415) BEFORE
   storage+quota. Test pins 415 + zero rows.
13. **mark_source_indexed silent no-op**: guarded UPDATE now raises when
   it matches nothing — a run must not report SUCCEEDED over an
   unindexed source (the #5 double-claim symptom).
14. **Dead branch**: _pdf_page_texts' gzip/else branches were identical;
   collapsed (every read via the capped seam).
16. **Inline FOR UPDATE SQL**: moved to named block lock_user_for_quota
   (AGENTS.md queries rule; last inline holdout in upload_source).
5. **Claim safety backstops** (migration 029): UNIQUE
   (source_id, locator_id, chunk_index) on chunks (double-claim
   delete-then-insert races now fail loudly); claimed_runs_max=5 — the
   claim query refuses over-cap rows (dead-letter by omission: the
   source stays 'uploaded', visible in source stats; requeue is the
   path back after inspection).
7. **Worker poll latency**: ingestion.toml v2 gains its own
   poll_interval_seconds=5 (was sharing lifecycle's 3600s); upload path
   calls worker.wakeup() — an asyncio Event the loop waits on alongside
   stop — so upload-to-ingestion is seconds, not an hour.
8. **Standalone worker entrypoint**: `python -m src.backend.ingest.worker`
   (process_batch already standalone; lifting out before replica > 1).

DEFERRED — design calls, recorded for ratification:
- **#6's read/delete surface**: list/status/requeue endpoints are
  mechanical, but per-source delete needs the citation-snapshot shape
  (golden rule 6) ratified first. Requeue endpoint rides along with it.
- **#9 lock-scope refactor**: file write after commit + memory refresh
  off the upload path — needs the orphan-sweep window reasoned through
  against concurrent uploads (the sweep exists; the invariant check is
  the work).
- **#10 chunk/locator dedupe (chunk_locators join table)**: agreed the
  right shape, MUST land before embeddings populate (else triple-stored
  vectors); scheduled as its own migration task now.
- **#11 uri second source of truth**: confirmed mechanical once #10's
  migration is open (same batch).
- **#5's heartbeat**: claimed_runs_max dead-letters the pathological
  case; a claim heartbeat + liveness check is the scaling follow-up
  when replica count > 1 (with #8's entrypoint split).

Gate: 290 tests (+6: failed/pending citability ×2, history queued_at,
savepoint fence, NUL strip, 415-no-store), ruff, mypy green.
