# Decision 007: The Memory Model

Date: 2026-09-10
Status: ratified by operator
Supersedes: the "write each participant's course memory" wording in earlier
docs; the 2026-09-05 note reading of "memory is the user's, not the course's"
that produced per-participant writes.

## The problem this decision solves

"Memory" has been used to mean four unrelated things across the docs and
code. Every agent session re-derived its own interpretation and built the
wrong thing at least twice (per-participant memory writes, twice). This
document is the single source of truth for the vocabulary. When docs or
code disagree with this file, this file wins.

## The model

Memory is a tree with one root per user:

```
User memory (root — one per user, lifelong)
 ├── behavioral profile: how to teach THIS person
 │   (visuals vs prose, analogies, response structure — the only layer
 │    allowed to change how the model behaves)
 ├── cross-course history (what the user has taken/done — secondary)
 │
 └── Course memory (children — one per user per course)
      └── distilled FOCUS: what this person struggles with, understands
          strongly, needs more time on, in THIS course
```

**User memory (the root)** is behavioral. "This student learns well from
visuals and analogies" lives here. It is the only layer that may instruct
the model on HOW to behave. It also carries history across courses: if the
user struggled with integrals in Calc 1, the root remembers it, so when
the user works on Calc 2, the tutor brings greater understanding and
emphasis to the integrals section. The root reads its children to do
this — cross-course stitching happens at the root, at prompt time.

**Course memory (the children)** is per-user, per-course: "a big distilled
idea of what to focus on for that course," for one specific person. It
states facts about understanding (struggles, strengths, time needed). It
NEVER contains behavior instructions — those belong to the root. It is
NEVER shared: if course memory were accessible to all, a new user joining
the course would inherit a mismatch — "this user really needs to focus on
X" when they are here for Y.

**Scope ruling — main user only.** Course memory is stored ONLY for the
main user of a course (its owner). Storing a node per enrolled learner was
rejected: it gets really complex, fast. A learner in someone else's course
is served by the harness (retrieval, citations, tutor) plus their own raw
private student data (attempts, mastery — a different subsystem); they do
not get a course-memory node.

**Course knowledge is not memory.** Concepts, dependencies, memory
objects, sources, and the TOC describe what the course SAYS — the shared,
per-course knowledge layer. The TOC is the index for FINDING content (a
multi-layer location system), not a memory. No user's focus lives in it.

## Vocabulary map — operator words to code names

| Operator word | Meaning | Code home |
|---|---|---|
| User memory (root) | Behavioral profile + cross-course history | `configs/tutor.toml` profiles (presentation slice, exists); full root is M2 work |
| Course memory (child) | Per-user, per-course focus record, main user only | `course_memories` table, `common/course_memory.py`, `GET /course-memories` |
| Course knowledge | What the course says: concepts, evidence | `concepts`, `dependencies`, `memory_objects`, `memory_object_evidence` tables |
| TOC / index | Multi-layer content-location system | `tables_of_contents`, `toc_entries`, `schemas/memory.py` models |
| Student data | Raw private per-user records | `attempts`, `concept_mastery`, `recommendations`, chat tables |

Known legacy misnomers, kept for DB-history reasons and mapped here:
`schemas/memory.py` holds the course-knowledge models (Concept, Dependency,
MemoryObject, TOC) — not user memory. `MemoryObject` is a course-knowledge
note (formula/theorem/example tied to a concept and source). The
`src/backend/memory/` package is the course-knowledge extraction subsystem.
Do not rename applied tables; do not add new code under these old meanings.

## Invariants

1. Course-memory rows are written for exactly one user per course: its
   owner. The only public write seam is `course_memory.refresh_for_owner`;
   there is no API to write another user's node.
2. Nothing below the root may carry behavior instructions. Presentation
   preferences live in the root (user memory) and the tutor-profile
   machinery; course memory carries facts about understanding only.
3. Course memory is never visible to any other user, in any form, in any
   course shape.
4. Course knowledge and the TOC are shared per-course state; user focus
   never leaks into them.
5. The course-memory node belongs to the user, not the course: it survives
   course archival and purge (deletion's distilled record — golden rule 6).
6. Cross-course emphasis transfer (Calc 1 struggle → Calc 2 emphasis)
   happens at the root at prompt time; no concept-linking schema until a
   versioned eval shows the prompt-time path failing.

## Current state vs target

- The `course_memories` table and owner-only writes are correct per this
  decision (fixed 2026-09-10; enforced by `refresh_for_owner`).
- Current node content is a course-content summary with an evidence
  snapshot — the deletion keepsake. That was the only thing distillable
  before attempts/mastery data exists.
- Target node content is FOCUS memory (struggles/strengths/needs),
  deterministically distilled from the user's own attempts and mastery
  once Milestone 3 produces that data; the root (user memory) is then
  assembled from profiles + children at prompt time.
- The root's behavioral slice currently exists as tutor profiles
  (`configs/tutor.toml`, `tutor/profile.py`); elevating it to the full
  user-memory root is Milestone 2 work.