# Customer tiers and generation spend control

**Status:** accepted, 2026-08-28

## Decision

Every user has a tier — `free` (default) or `paid` — and every model call is
metered. Model compute is gated on a weekly token budget and routed by tier.

**Tier state.** `users.tier` is the current tier, synced by a trigger from
`user_subscriptions`, an append-only history of subscription periods. At most
one active subscription per user (partial unique index). Ending the last
subscription resets the user to `free`. The trigger is the only writer of
`users.tier`, so tier never disagrees with subscription history.

**Weekly budget.** A rolling calendar week — Monday 00:00 UTC to now. Each tier
defines `weekly_token_budget` (input + output tokens summed) in the versioned
`configs/tiers.toml`. Generation paths call `budget.check_budget` before model
compute and raise `BudgetExceededError` at the boundary; the check returns an
inspectable `BudgetState` (spent, budget, remaining, week start) so the UI can
show spend without any opaque score. The budget check gates; it does not
reserve — a burst of concurrent requests can overshoot slightly, accepted at
this scale.

**Course limits.** Each tier also defines `max_owned_courses` (free: 2, paid:
20). Course creation calls `budget.check_course_limit`; the cap counts owned
courses only — enrollment in others' courses is not limited, and deleting a
course frees the slot. The cap exists to stop storage and quota farming (many
courses, many uploads) rather than to price collaboration.

**Course storage limits.** Each tier defines two caps: `max_course_storage_bytes`
(free: 100 MB, paid: 1 GB) and `max_total_storage_bytes` (free: 1 GB, paid:
10 GB across all owned courses) — the total cap exists so storage cannot be
multiplied by making many courses with the same content. Upload calls
`budget.check_course_storage` (per-course) and `budget.check_total_storage`
(aggregate) with the incoming file size before accepting it; both sum
`sources.size_bytes` and project the total with the incoming file. `size_bytes`
is recorded on every uploaded source (migration 008), so the accounting
reflects files actually stored. Uploads are compressed on entry where the
format allows (§ upload contract); the cap applies to stored bytes. Source
deletion frees the space.

**Free-tier overhead.** Free users are charged an extra
`free_tier_overhead_percent` (5%) of each generation's tokens, recorded as
`overhead_tokens` in the ledger and counted toward the weekly budget. The
overhead is applied when *recording* spend, never when gating: an in-flight
generation is never cut off mid-answer — the overhead only tightens the
*next* budget check.

**Downgrade grace.** Downgrade is a soft landing: a user who loses paid tier
keeps their over-cap courses and storage, and is only blocked from *new*
creation until under the free caps. A 60-day grace deadline
(`users.downgrade_grace_deadline`, set by trigger when a paid subscription
ends, cleared on resubscribe) bounds the soft landing: past it, excess
courses/storage may be removed by the operator — archive-first, per the
deletion principle.

**Tier verification.** Limits resolve the tier from the authenticated
account and `budget.verify_tier` re-checks it against `users.tier`, so a
stale or spoofed caller-supplied tier can never unlock paid limits.

**Tier-routed models.** The same config maps each generation task
(`tutor_answer`, `toc_update`, `probe_generation`, `probe_evaluation`,
`memory_extraction`, `artifact_generation` — the `KNOWN_GENERATION_TASKS`
vocabulary, the same strings the ledger records) to a model per tier. Free
tiers run the cheap generative model; paid tiers run the newer model; the
small stable TOC-writer is shared. The loader validates every tier defines
every task, so a config edit cannot silently drop a tier's routing.

**Ledger.** `generation_ledger` is append-only: one row per model call with
user, course, task (free string from `KNOWN_GENERATION_TASKS`), model, token
counts, and the free-tier overhead. Each row also snapshots `course_label`,
so spend history keeps course attribution even after the course is deleted
(the `course_id` reference is nulled, the label survives). Spend is
inspectable per user and per week; entries are never edited or updated.

## Consequences

- Anonymous generation was already blocked by the permission layer; now
  authenticated generation is bounded too. The stranger token-spend chain is
  closed: register → self-enroll → generate is capped at the free weekly
  budget.
- Ingestion model calls (`toc_update`, `memory_extraction`) are charged to the
  uploading owner's budget, tying the upload-size gap to a real limit.
- Retry double-spend is visible in the ledger: a re-run stage writes a second
  row. The idempotency contract for model-calling handlers remains open.
- Payment processing is out of scope. Subscriptions are created/ended by the
  operator or a future billing flow; the tier state machine is what billing
  will drive.
- New tiers are a new enum value + config section, not a schema redesign; the
  `user_tier` enum may gain values (e.g. `pro`) without touching existing rows.

## Claim codes (2026-08-29, amendment)

Every account can be issued a personal claim code; the operator flags codes
as premium-granting (`grants_premium`). Codes are stored as SHA-256 hashes
(plaintext shown once at issue), normalized case-insensitively with
separators stripped. Claiming requires an authenticated user (anonymous
callers can never flip tiers) and goes through `premium_codes.redeem`, which
starts the paid subscription through the standard subscription machinery —
tier state stays single-sourced in `users.tier`. Codes issued for a specific
user are bound to that account. A code whose claiming user is deleted is
fully released (claim reset, claimable again). Purpose: premium recovery
when authentication is broken ("enter your premium code" path) and easy
manual testing without a payment provider.