# Execution plan: course lifecycle, sharing, support codes, and storage

## How to use this file

This is the implementation handoff for a smaller coding model. Do not restart
the feature from scratch: a substantial candidate implementation already exists
in the dirty worktree. Inspect it, preserve unrelated/user-owned changes, finish
the unresolved items below, and verify the whole repository.

Going forward, the expensive review model should normally update this file and
review results rather than directly implementing the plan. Do not commit unless
the user explicitly asks.

## Ratified product rules

These are decisions, not questions for the implementer:

1. Normal account access and premium status should eventually come from the
   ordinary login and billing path (for example Stripe). Support codes are an
   exceptional customer-support entitlement path, not the core auth flow.
2. Every account receives a support-code record atomically at registration.
   Only the hash is stored. No user-facing API may return its plaintext or code
   metadata. Support can internally rotate a code, receive its plaintext once,
   and deliver it out of band.
3. Submitting a support code requires an already authenticated account. A code
   may grant a subscription/entitlement, but it never authenticates identity.
4. Account support codes and course join codes are completely separate.
5. Course display names are user chosen. Course join codes are random,
   server-generated identifiers; users never choose them.
6. Course visibility modes are `private`, `invite_only`, and `public`.
   - Private: no join-code exposure.
   - Invite-only: join code visible only to the owner.
   - Public: join code visible in the public course representation.
7. Owner invitations are pending until the learner explicitly accepts. An
   invitation alone must not enroll the learner or grant course access.
8. Active owned-course counts must be enforced under concurrency.
9. Uploads have a separate raw-body ceiling. Storage quotas charge the bytes
   actually stored after optional compression. Concurrent uploads must not race
   past per-course or per-owner caps.
10. Deleting a course immediately removes normal access but retains the exact
    course for 90 days. Current participants may make one private copy during
    that grace period, subject to their own course/storage limits.
11. Restricting a public course creates a version boundary: preserve the old
    public version as the 90-day archive and give the owner a new restricted
    successor. Existing learners are not auto-enrolled in the successor.
12. At day 90, purge all course-derived data except each account's permanent
    course-memory-bank record. This includes old citation snapshots and learner
    artifacts tied to that course. Account deletion still removes the account's
    memory bank.
13. The memory bank is an ongoing account feature, not something created only
    during deletion. Refresh it for active participants as course memory changes.
14. Memory summaries scale sublinearly with source count, currently using a
    square-root baseline. Approximate caps are 1,000 tokens for free accounts and
    5,000 for paid accounts.
15. Permanent memory must remain inspectably grounded after source rows are
    purged. Preserve a compact evidence index inside the memory record (source
    name, hash, locator/excerpt when available).
16. Database purge and physical-file deletion must be crash tolerant. Cleanup
    jobs need leases, bounded retries, and observable terminal failure.

## Current worktree state

The worktree contains a broad candidate implementation. Important new areas:

- APIs:
  - `src/backend/api/courses.py`
  - `src/backend/api/enrollments.py`
  - `src/backend/api/archives.py`
  - `src/backend/api/sources.py`
  - support redemption in `src/backend/api/auth.py`
- Repositories/services:
  - `courses_repo.py`, `enrollments_repo.py`, `sources_repo.py`
  - `courses_lifecycle.py`, `course_archives_repo.py`
  - `memory_bank.py`, `storage.py`, `archive_maintenance.py`
- Queries:
  - `courses.sql`, `enrollments.sql`, `sources.sql`
  - `course_archives.sql`, `course_deletion.sql`, `premium_codes.sql`
- Migrations:
  - `013_upload_foundations.sql`
  - `014_sharing_enum_values.sql`
  - `015_course_archives_and_memory_banks.sql`
  - `016_review_followups.sql`
- Config:
  - `configs/tiers.toml` version 6
  - `configs/lifecycle.toml` version 2
- Tests:
  - `test_courses_api.py`, `test_courses_lifecycle.py`
  - `test_sources_api.py`, `test_storage.py`
  - `test_archive_maintenance.py`
- Design record:
  - `docs/decisions/005_course_sharing_archives_and_support_codes.md`

Known database history from the prior session: migrations 014 and 015 were
applied after 013. Migration 016 appeared later and must be treated as unapplied
until the database says otherwise. Never edit an already-applied migration.

`src/backend/common/migrations/012_premium_claim_codes.sql` appears modified in
`git status`, but previously had no textual diff. Verify that before touching it;
do not normalize or rewrite an applied migration merely to clear status noise.

Verification history is partial:

- A full suite passed at 143 tests before the latest upload, ongoing-memory,
  maintenance, migration-016, and follow-up test changes.
- Several focused suites passed afterward.
- There is no trustworthy final full-suite result for the current worktree.
- `git diff --check` was clean when this plan was written.

## Non-negotiable engineering constraints

- Read `AGENTS.md`, `project.md`, and `system.md` before changing structure.
- Preserve unrelated dirty-worktree changes.
- Use `apply_patch` for hand edits.
- Raw SQL belongs in `src/backend/common/queries/*.sql`.
- Schema changes must be new append-only migrations.
- Keep support-code plaintext out of logging, responses, and persisted storage.
- Do not weaken source-grounding or evidence retention inside permanent memory.
- Do not commit.

## Phase 0: establish the real baseline

- [ ] Run `git status --short`, `git diff --check`, and inspect the complete diff.
- [ ] Determine which migrations are recorded in `schema_migrations`.
- [ ] Review migration 016 before applying it. Confirm its constraint names work
      both against the current database and a fresh empty schema.
- [ ] Run the fresh-schema migration test before modifying migrations.
- [ ] Apply only unapplied migrations with:
      `.venv/Scripts/python -m src.backend.common.migrate`.
- [ ] Run the full quality gate once to capture actual failures before fixes:
      pytest, Ruff, and mypy.
- [ ] Record baseline failures in a short checklist at the bottom of this file
      rather than making speculative rewrites.

## Phase 1: fix the remaining high-risk lifecycle issues

### 1.1 Remove the unsafe automatic orphan sweep

`archive_maintenance.run_once()` currently calls
`courses_lifecycle.sweep_storage_orphans()`. The sweep deletes any UUID-named
storage directory whose course row is not visible in another database
connection. This races with archive copying/public-to-private copying: the new
course row can be uncommitted while its canonical directory already exists, so
maintenance may delete a valid in-progress copy.

Preferred correction:

- [ ] Remove the generic orphan sweep from automatic lifespan maintenance.
- [ ] Treat `storage_cleanup_jobs` as the authority for automatic deletion.
- [ ] Keep synchronous rollback cleanup in upload/copy failure paths.
- [ ] If an orphan-repair tool is retained, make it an explicit operator command
      with a conservative minimum age, a second database existence check just
      before deletion, and a dry-run mode. Do not run it hourly.
- [ ] Replace the current lifespan test that expects an arbitrary orphan to be
      deleted immediately.

Do not “fix” this only with a short mtime delay and leave it automatic unless the
race is explicitly documented and accepted. A staging-directory/finalization
outbox is the robust future design.

### 1.2 Make cleanup leases, retries, and terminal failure deterministic

Candidate code now includes expired-lease reclamation, a configurable maximum
attempt count, and terminal `dead` jobs in migration 016.

- [ ] Verify an expired `running` job below the max becomes retryable.
- [ ] Verify an expired `running` job at the max becomes `dead` and is never
      claimed again.
- [ ] Verify an `OSError` on the last permitted attempt becomes `dead`.
- [ ] Emit an error log containing `job_id`, `course_id`, attempt count, and the
      final error when a job becomes dead. Never silently abandon data.
- [ ] Avoid reclaiming twice in one maintenance pass. At present `run_once()`
      reclaims and `process_cleanup_jobs()` also reclaims; pick one owner.
- [ ] Ensure multiple app workers remain safe through `FOR UPDATE SKIP LOCKED`.
- [ ] Make the lifespan test deterministic. It should not launch the background
      loop and simultaneously call `run_once()` against the same rows.

### 1.3 Reconcile copy semantics with re-ingestion

The accepted design says copied raw sources are marked `uploaded` and pass
through ingestion again. The candidate copy helper also copies concepts and
dependencies but does not copy their complete locator/chunk/evidence graph.
That creates partially stale, potentially ungrounded derived memory.

- [ ] Choose one internally consistent strategy:
  - Recommended: copy raw source files, study periods, and clearly canonical
    owner-authored objects; do not copy derived concepts/dependencies/memory
    objects. Queue fresh ingestion for every copied source.
  - Alternative: copy the entire derived graph, including locators, chunks,
    TOC, memory objects, and evidence mappings, with complete ID remapping.
- [ ] Do not leave the present half-copy state.
- [ ] Confirm user-specific attempts, conversations, mastery, recommendations,
      and artifacts are never cloned into another user's course.
- [ ] Confirm the archived original remains exact and readable/copyable for the
      full grace period even though the successor is re-ingested.

If ingestion scheduling is not yet implemented, add an explicit pending
ingestion seam or clearly record that as a blocking follow-up. Do not falsely
mark copied sources indexed.

### 1.4 Guarantee grounded memory within the configured cap

The current summary concatenates semantic memory and evidence, then truncates at
roughly four characters per token. With many verbose concepts, truncation can
remove every evidence line, violating the source-grounding rule.

- [ ] Refactor summary construction so evidence has a reserved budget.
- [ ] Always retain at least a compact evidence index for courses with sources:
      filename + source hash, plus locator label when available.
- [ ] Use excerpts only with remaining budget; hashes and locators matter more
      than long prose.
- [ ] Preserve useful concept names/definitions and course-memory objects within
      the remaining budget.
- [ ] Keep the square-root scaling and free/paid caps configurable.
- [ ] Add a regression test with many long concepts and multiple sources proving:
  - the summary stays within its approximate character/token limit;
  - at least one evidence entry survives;
  - key concept information survives;
  - no hash or structural marker is cut in half.
- [ ] Document that four characters per token is an approximation. If exact
      model tokenization becomes necessary, route it through a versioned
      tokenizer rather than hardcoding another estimate.

## Phase 2: audit the ongoing memory-bank hooks

The candidate code refreshes memory on course creation, accepted join/enrollment,
upload, rename/update, copying, and archival.

- [ ] Verify every active owner gets a memory row in the same transaction as
      course creation.
- [ ] Verify a pending invitation creates no learner memory and grants no access.
- [ ] Verify acceptance or join-code enrollment creates the learner's memory.
- [ ] Verify revocation does not delete the learner's permanent memory.
- [ ] Verify upload and course rename update `updated_at` without rewriting
      `created_at` (migration 016).
- [ ] Identify future mutation hooks explicitly: ingestion completion, concept
      extraction/update, source replacement/deletion, and memory-object edits
      must call the same refresh seam.
- [ ] Avoid doing unbounded participant-by-participant summarization while
      holding quota locks. The current small-user deployment may tolerate it,
      but measure/query-count it and leave a clear queue boundary for growth.
- [ ] Verify account hard deletion cascades memory rows and citation snapshots;
      course deletion must not.

## Phase 3: audit quota and transaction correctness

### 3.1 Course counts

- [ ] Add a real concurrent test for the free active-course limit. Two competing
      creates at the boundary must produce exactly one success.
- [ ] Confirm archived courses do not consume active-course slots.
- [ ] Confirm a public-to-restricted transition is net-neutral in active owned
      course count.
- [ ] Confirm an archive copy consumes a new active slot.

### 3.2 Upload storage

- [ ] Confirm raw request streaming stops at `max_raw_upload_bytes` without
      reading the full body into memory.
- [ ] Confirm compression occurs before quota accounting.
- [ ] Confirm `sources.size_bytes` records stored bytes, not raw bytes.
- [ ] Confirm per-course and aggregate totals include retained archives so
      create/delete loops cannot evade storage caps during the 90-day window.
- [ ] Add a concurrent near-cap upload test. User-row locking must allow only
      one upload to commit when both would exceed the aggregate cap.
- [ ] Verify the losing upload leaves no source row, course object, temp file, or
      canonical stored file.
- [ ] Audit lock order across upload, public restriction, archive copy, course
      creation, and deletion. Standardize on user/account lock before active
      course lock wherever both are required; document why archived-copy access
      locks are safe.

### 3.3 File/database atomicity

- [ ] Exercise failure after file write but before DB commit and prove the file
      is removed.
- [ ] Exercise failure after copying several archive files and prove the target
      directory is removed.
- [ ] Ensure cleanup exceptions do not mask the original transaction failure.
- [ ] Document the remaining ambiguous-commit edge case. A future file-finalize
      outbox may be needed for absolute durability.

## Phase 4: security and API contract audit

### 4.1 Support codes

- [ ] Search all API schemas and handlers for `support_code`, `premium_code`,
      `code_hash`, and `PremiumCode`. No read response may expose them.
- [ ] Registration must issue the hash record atomically and return only public
      `User` fields.
- [ ] Support rotation remains an internal/operator function with one-time
      plaintext return; it must not be added to the public router.
- [ ] Redemption requires a valid bearer token, rejects codes bound to another
      account, is single-use, and starts entitlement state atomically.
- [ ] No code plaintext or hash may enter logs.

### 4.2 Course sharing

- [ ] Reject client-supplied course codes (`extra="forbid"` on create payload).
- [ ] Verify generated join-code uniqueness and normalization.
- [ ] Private owner/course/learner views expose no join code.
- [ ] Invite-only owner sees it; invite-only learner does not.
- [ ] Public catalog exposes it.
- [ ] Rotation invalidates the prior join code immediately.
- [ ] Pending/declined/revoked enrollment states cannot use course sources.

### 4.3 Archive access and copying

- [ ] Normal course endpoints return 404 for archived courses.
- [ ] Only users granted archive access can list/copy an archive.
- [ ] Access expires exactly at `expires_at`.
- [ ] Each access record permits one successful copy; concurrent double-copy
      attempts must not create two courses.
- [ ] Public-to-private/invite-only PATCH returns the new successor `course_id`.
- [ ] Existing learners receive archive access to the old version and no
      enrollment in the successor.

## Phase 5: deletion and retention tests

Build one realistic fixture containing all relevant dependency branches:

- owner plus active learner and pending invite;
- source object, raw stored file, locator, chunk, TOC entry;
- concepts, dependencies, memory objects/evidence, mastery;
- assessment items and attempts;
- conversation, retrieval trace, response, claim, citation;
- user artifact and citation snapshot;
- generation ledger entry with course label.

Then prove:

- [ ] Archive action leaves the exact course tree and files intact for 90 days.
- [ ] Owner and active learner receive archive access and permanent memory.
- [ ] Pending invite receives neither.
- [ ] Normal use is denied while archived.
- [ ] Archive copying works before expiry.
- [ ] Purge succeeds with grounded responses and mastery rows (the original FK
      bug must stay fixed).
- [ ] At expiry, sources, derived content, chat/history, mastery, user artifacts,
      and course citation snapshots are gone.
- [ ] Permanent per-user memory remains.
- [ ] Generation ledger policy remains intentional: retain only non-content
      billing/audit metadata such as the course-label snapshot.
- [ ] A cleanup job is committed atomically with DB purge.
- [ ] Physical files disappear after cleanup succeeds.
- [ ] Purge rollback leaves both archive DB state and files intact if any
      subtree statement fails.

## Phase 6: migrations and documentation

- [ ] Keep migrations 001–016 append-only once applied.
- [ ] Confirm migration 014 remains separate from 015 because PostgreSQL enum
      additions need their own committed migration before safe use.
- [ ] Confirm migration 016 applies to both an upgraded database and an empty
      schema migration run.
- [ ] Confirm all new foreign-key actions match retention rules:
  - course memory survives course deletion;
  - account deletion cascades its memory;
  - archive access cascades with course/account;
  - copied-course references become null safely.
- [ ] Update `project.md`, `system.md`, decision 005, and append-only
      `docs/notes.md` only after behavior is final.
- [ ] Remove or explicitly supersede stale language claiming support codes are
      displayed at registration, used for auth recovery, or that learner
      artifacts survive forever after course deletion.
- [ ] Document the maintenance deployment expectation (FastAPI lifespan,
      multi-worker behavior, interval, dead-job alerting, and operator recovery).

## Phase 7: final quality gate

Run from the repository root:

```powershell
.venv\Scripts\python -m src.backend.common.migrate
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy src
git diff --check
git status --short
```

Final acceptance requires:

- [ ] All migrations apply to the current DB and a fresh schema.
- [ ] Full pytest suite passes; do not report only focused suites.
- [ ] Ruff passes.
- [ ] mypy passes.
- [ ] `git diff --check` passes.
- [ ] No test writes course files into the real `data/raw` directory; patch
      `src.backend.common.storage.get_settings` to a temp root correctly.
- [ ] No background maintenance thread/task leaks after tests.
- [ ] No support-code material appears in API snapshots or logs.
- [ ] No unrelated user changes are overwritten.
- [ ] No commit is created.

## Expected implementation report

When the smaller model finishes, it should report:

1. Files changed, grouped by lifecycle, auth/sharing, storage, tests, and docs.
2. Migrations applied and their exact versions.
3. Full test/Ruff/mypy results with counts.
4. Any deliberately deferred item, especially ingestion scheduling or the
   file-finalization outbox.
5. Any remaining business tradeoff that needs user approval, rather than
   silently choosing a new policy.

## Baseline failures discovered during execution

Review performed 2026-08-31 after the smaller-model pass:

- Quality gate is mechanically clean: 164 tests passed, Ruff passed, mypy
  passed, and `git diff --check` reported no whitespace errors (only the
  existing LF/CRLF warnings).
- Database `schema_migrations` contains every version through 016. Migrations
  013-016 are still untracked files in the working tree. They are applied
  history now: do not edit them, and do not omit them from the eventual commit.
- **P1: automatic orphan sweeping is still unsafe.**
  `archive_maintenance.run_once()` still invokes `sweep_storage_orphans()`.
  An archive/public-transition copy writes the new UUID directory before its
  course transaction commits; another connection cannot see that course row
  and can delete the valid directory. Remove this from automatic maintenance as
  specified in phase 1.1. The shared `client` fixture also starts this loop
  without universally overriding `STORAGE_ROOT`, so tests can inspect/delete
  UUID directories in the configured development storage root.
- **P1: one malformed archive can block every later retention purge.**
  `purge_expired_archives()` processes up to 100 archives in a single
  transaction and commits only after the loop. Any failure rolls back the
  cleanup jobs and successful subtree deletes for the entire batch; because
  the same oldest archive is selected again next pass, it can indefinitely
  retain all later archives past the promised 90 days. Isolate each archive in
  its own transaction (or savepoint with an observable terminal failure path).
- **P1: invitation acceptance can race with archival.** The enrollment policy
  trigger fires on selected identity/source columns, not `status`.
  `accept_invitation` changes only `status` and `responded_at`. If archival
  commits after the API's active-course check but before that UPDATE, the
  invitation becomes `active` on an archived course without archive access.
  Add `status` to the trigger's UPDATE columns (in a new migration) and add a
  two-connection concurrency regression test.
- **P1: bounded permanent memory can still lose all grounding.** Evidence is
  appended last and the assembled string is then prefix-truncated, so verbose
  concepts can remove every evidence line. `key_concepts` is also persisted
  outside the bounded summary with no cap. Implement the reserved evidence
  budget described in phase 1.4 and bound the complete retained record, not
  just its summary string.
- **P1: course copying remains an inconsistent half-copy.** It copies raw
  sources, concepts, and dependencies, but not locators, chunks, TOC entries,
  memory objects, or evidence mappings, and it creates no ingestion run. This
  leaves derived concepts detached from their evidence. Choose one strategy in
  phase 1.3. Also, a valid non-source object with only `content_uri` prevents
  copying; archive copy maps that to 409, while public-to-restricted PATCH does
  not catch `UncopyableCourseError` and currently returns a 500.
- **P2: cleanup terminal failure is not operationally observable enough.** A
  last-attempt failure becomes `dead`, but no error log/alert includes the job,
  course, attempt count, and final error. Maintenance also reclaims leases once
  in `run_once()` and again inside `process_cleanup_jobs()`. Assign one owner
  and log terminal failures as specified in phase 1.2.
- Add targeted tests for all findings above. The existing passing suite covers
  happy paths but does not exercise these transaction interleavings or a
  memory large enough to truncate its evidence section.
