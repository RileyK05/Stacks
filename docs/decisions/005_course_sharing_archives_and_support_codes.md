# Course sharing, archive retention, and support codes

**Status:** accepted, 2026-08-30

## Decision

Account support codes and course join codes are unrelated credentials with
different exposure rules.

**Account support codes.** Registration creates one account-bound support-code
record atomically with the user. Only its SHA-256 hash is persisted;
registration and every other user-facing API response omit the plaintext and
all code metadata. The initial plaintext is intentionally discarded. Customer
support may rotate the record through an internal operator function, receive the
new plaintext once, and send it out of band. A signed-in user may submit that
code to claim a support-arranged entitlement. It is never accepted as identity
authentication and never replaces the normal email/password and billing flow.

**Course sharing.** A course has a server-generated, globally unique random
join code that is separate from its user-chosen display name. Private course
codes are not exposed. Invite-only codes are exposed only to the owner; public
codes are shown in the public course view. Owners may rotate a shareable code.
Public courses also support direct self-enrollment. An owner invitation creates
a pending record and grants no course access until the learner accepts it.

**Restriction and deletion.** Deleting an active course removes it from normal
use immediately but retains the exact course tree for 90 days. Restricting a
public course creates an atomic version boundary: the public course becomes the
90-day archive and the owner receives a new active restricted copy. Existing
learners receive archive access to the old version, not enrollment in the new
one. During the grace period each participant may copy the archive as many
times as they like, subject to their normal active-course and stored-byte
limits.

**Permanent course memory.** Before archiving, the course's main user (its
owner) receives a course-memory node (decision 007): a bounded, evidence-
bearing distilled record of the course. It remains after the full archive is
purged and contains the course name, key concepts, bounded summary, and a
compact evidence snapshot with source names, source hashes, and
representative first-chunk excerpts of up to ten sources where chunk text is
available. The configured budget scales with the square root of source count
and is capped at 1,000 approximate tokens for free accounts and 5,000 for
paid accounts. Enrolled learners receive archive/copy access for the grace
period, not a memory node. The owner's course-memory node is the only
course-derived record intentionally retained after the 90-day archive
expires.

**Purge reliability.** Expired database trees are removed in foreign-key-safe
order. The same transaction writes a durable physical-storage cleanup job.
Cleanup workers claim jobs with leases and retry failures up to a configured
attempt cap, after which the job is marked dead for operator inspection
instead of retrying forever; expired leases are reclaimed the same way, so a
process crash cannot silently orphan stored files or wedge a job. A periodic
sweep also removes orphaned course directories that committed database
operations could not clean up.

## Consequences

- Normal billing can later drive the existing subscription state directly;
  support-code redemption remains an exceptional, authenticated entitlement
  path.
- A database or API client cannot recover a support-code plaintext. Support
  must rotate before giving a user a code.
- Course names never act as identifiers, and account support codes never act as
  course invitations.
- Archival storage remains charged while retained; copying can therefore fail
  cleanly at a quota boundary rather than bypassing storage limits.
- Public-to-restricted transitions return a new active `course_id`; clients
  must navigate to the successor returned by the PATCH response.
- Copied raw sources are marked `uploaded` and pass through ingestion again;
  user-specific attempts, conversations, mastery, and artifacts are not cloned
  and are removed when the old archive expires.
