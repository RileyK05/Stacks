# Course access and source objects

**Status:** superseded in part by
[`003_public_enrollment_and_personal_artifacts.md`](003_public_enrollment_and_personal_artifacts.md),
2026-08-26

## Decision

Each course has one owner and optional learner memberships. A learner can view
the shared course, use its sources for retrieval and generation, and manage
their own generated materials. Only the owner can add, replace, or remove base
sources. Revocation removes future access without deleting the learner's private
study history.

Course visibility is private or public. Public visibility exposes the course
view, not raw source objects; raw sources use member scope. Attempts, mastery,
conversations, and recommendations remain private to their user.

Every source is also a course object. `sources.object_id` is a unique foreign
key to `course_objects.object_id`; the generic row owns common lifecycle and
access data, while the source row owns upload and ingestion details. The foreign
key also includes course and creator identity, preventing a valid source and a
valid object from different users or courses from being linked together.

## Consequences

- Ownership, membership, authorship, and private student state are separate.
- Member source mutation is denied centrally by the permission policy.
- Database triggers reject records whose stated user lacks active course access
  and enforce owner-only creation of base source objects.
- Member-generated objects default to creator scope and can later be explicitly
  promoted or copied through a separate feature.
- Source creation must insert the course object and source detail in one
  transaction.
