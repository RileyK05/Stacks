# Public discovery, enrollment, and personal artifacts

**Status:** accepted, 2026-08-26

## Decision

Course visibility, course enrollment, and content ownership are separate.

A public course may expose owner-published canonical objects to anyone,
including an anonymous visitor. Public visibility does not expose uploaded raw
sources and does not authorize model compute. A signed-in user must first
self-enroll in a public course before using its sources for retrieval or
generation. An owner invitation remains pending and grants no access until the
learner accepts. Invite-only courses may also be joined with a server-generated
random code exposed only to the owner. Account support codes are never course
join codes; decision 005 defines both lifecycles.

Enrollment grants use of the course, not control of it. Only the course owner
may add, replace, remove, or publish canonical course objects and base sources.
Revoking an enrollment removes future source use and generation access.

Material a learner generates is a private `user_artifact`, not a course object.
It remains accessible only to that learner after enrollment revocation. When
the source course is archived, the artifact is retained only for the 90-day
course grace period and is then purged; the course owner's course-memory node
is the sole course-derived retention exception (decision 007). The course
owner and other learners receive
no access merely through their relationship to the course. Copying or promoting a
personal artifact into canonical course content is a separate future workflow,
not an implicit permission.

Interactive presentation preferences are also user-scoped. The course owner may
use their own structured tutor profile; every non-owner initially receives a
versioned generic profile. Owner preferences never leak into another learner's
interactive responses. Tutor profiles may control presentation such as
verbosity, analogy use, structure, and quotation balance, but may not affect
retrieval, TOC construction, evidence selection, or mastery evaluation.

## Consequences

- Public discovery works without anonymous model usage.
- Enrollment is an explicit course-access record, not site membership.
- Canonical course content and private learner work have different tables and
  authorization rules.
- Course ownership does not grant visibility into learner artifacts, attempts,
  mastery, conversations, recommendations, or tutor preferences.
- Personal artifacts keep their course label and provenance through enrollment
  revocation and the archive grace period, then are removed with the archive.
- Supporting collaborative authoring later will require an explicit role and
  promotion/copying workflow; it is not part of learner enrollment.
