# Project: Course Memory and Adaptive Study System

## One-line idea

Build an academic assistant that continuously ingests course materials, preserves
source-grounded course knowledge plus a per-user course-memory focus record
(decision 007), learns from a student's study attempts over time, and helps the
student decide what to study next — deployed for a small user base with
operator-owned data.

This is **not** just "chat with PDFs." The useful output is an inspectable, evolving model of:

1. what the course materials say;
2. how the course concepts connect;
3. what the student appears to understand, misunderstand, and need to practice;
4. what new content (practice tests, study artifacts) is worth generating.

## Problem

A course creates fragmented information:

- syllabi, slides, readings, problem sets, solutions, lecture notes, and announcements live in different places;
- course-specific notation and definitions differ from generic textbook explanations;
- ordinary chat-with-PDF tools retrieve passages but do not accumulate a reliable model of the course;
- grades and exams arrive late, giving weak feedback about whether the student actually understands a topic;
- the student's mistakes are usually corrected once and then lost rather than turned into a reusable error model.

The project should make course work compound across a semester. It should help answer:

> What does this course actually say about this concept, what prerequisites does it rely on, and what should I practice next to demonstrate independent understanding?

## Primary user

A small set of students (the operator and people they know) using it for their own
courses. Multi-user from the start: accounts with email + password, per-user data
isolation in the schema. Not an LMS, not a universal tutor — a useful personal
instrument that can be evaluated on real courses.

## Product principles

- **Source grounded:** substantive academic answers link to uploaded source material. Every claim carries an evidence chain.
- **Inspectable:** the system shows what it retrieved, what it inferred, and why it believes a concept is weak or mastered.
- **Data ownership:** course material and study history live in our own Postgres. Inference goes to hosted model APIs that contractually do not retain data.
- **Course-specific:** preserve a professor's notation, definitions, rubrics, and examples rather than replacing them with generic explanations.
- **Metered compute:** model calls are budgeted per user per week and routed by
  tier (free gets the cheap model, paid gets the newer one); every call is
  logged in an append-only ledger. Generation is never anonymous and never
  unbudgeted.
- **Learning over completion:** the tool helps practice and diagnose understanding, not produce assignments for submission.
- **ML earns its role:** begin with retrieval, structure, and simple measurable baselines; add fine-tuning only for documented failures.
- **Extensible by design:** new content kinds, locator types, and formats are free strings — they insert without schema redesign.
- **One canonical code format:** course join codes and premium/support codes
  share a single format (16 chars, look-alike-free alphabet, grouped display)
  validated at the API boundary and constrained in the database.
- **Destruction leaves a distilled record:** course deletion retains the exact
  course for a 90-day copy grace period, then purges everything except the
  course owner's bounded, evidence-bearing course-memory node; account deletion
  has a 7-day grace period.

## Non-goals

- Predicting grades from a calendar or course schedule.
- Rebuilding Canvas, Notion, Anki, or a generic PDF-chat wrapper.
- Claiming the student understands something solely because they read it or asked a question.
- Blindly fine-tuning a model on all uploaded files.
- Automating graded coursework in ways that undermine actual learning.

## Core system model

The system has six layers (mirrored by `src/backend/common/schemas/` and the
Postgres migrations).

### 1. Identity & course structure

Users (email + password auth, 7-day deletion grace, customer tier — free or
paid, controlling the weekly generation budget and which models answer),
courses, **study periods** — user-definable sliding time windows (a lecture, a
month, the stretch before an exam — never a hardcoded "week"), and **course
objects** — any object a course owns and the owner publishes: uploaded sources
and shared study materials. `kind` is a free string; `content_type` routes
storage/serving; `content_uri` points at the format-appropriate store.

Each course has one owner and is in exactly one of **three shapes: private,
invite-only, or public** (decision `006_three_course_shapes.md`; a closed set
— new shapes require a deliberate schema+policy change). Every course has a
server-generated canonical join code (16 chars from a look-alike-free
alphabet, display form `XXXX-XXXX-XXXX-XXXX`) — separate from its display
name. Anonymous visitors may view published objects and the join code on
public courses, but cannot use model compute; invite-only and private courses
are invisible to them. An authenticated learner self-enrolls in a public
course, submits a join code on a public or invite-only course, or accepts an
owner invitation before using its source collection for retrieval or
generation. Invitations grant no access until acceptance. Only the owner may
change canonical course objects or base sources. Learner generations live as
private user artifacts outside the course's canonical objects; the course
owner and other learners cannot view them.
Attempts, mastery, conversations, recommendations, and tutor preferences are
also private to the learner. An uploaded source is a specialized course object
linked 1:1 to its generic object record.

Tutor preferences change presentation, not truth or retrieval. Presentation
is a user-memory (root) concern per decision 007: the owner may use a
private structured profile for interactive responses in their course;
non-owners use a versioned generic profile for now (the full user-memory
root is Milestone 2 work). Neither profile may alter the TOC, evidence
selection, citations, or mastery evaluation.

### 2. Source content

Materials are stored **whole** — nothing is destroyed at ingest. Uploads
stream to disk under a hard byte ceiling (oversized bodies are cut
mid-stream), are stored under server-generated names (path traversal
structurally impossible), and are gzip-compressed only when the mime type
allows and it saves ≥10% (`stored_encoding`: `identity` / `gzip`). Each source
gets **locators**: a free-typed per-format table of contents (slide 7, page 3,
timestamp 12:30, cell range A1:D20 — each format keeps its natural unit).
Retrieval units are **token-bounded chunks** sized to fit the model's context
window, each pointing back to the locator it spans. Sources carry `file_hash`
for dedup. Ingestion is an ordered, versioned pipeline: text extraction →
locators → chunks → cascading TOC update → course-knowledge extraction. A
stage runs only after its dependency succeeds, retries according to
versioned configuration, and stops the pipeline with an inspectable error
when its
attempts are exhausted.

### 3. Course knowledge (shared per course — not memory; decision 007)

Concepts (with synonyms, evidence levels), dependencies (nullable prereq,
in-course or external — Calc 2 can depend on Calc 1), memory objects
(concepts/formulas/theorems/examples/misconceptions with evidence), and the
**table of contents**: a model-written, per-course, versioned index describing
what's in the course and where.

**Retrieval is TOC-guided, not embedding-based.** One model's embeddings don't
align with another's; the TOC avoids that failure mode entirely and stays
inspectable. A small, stable TOC-writer model keeps descriptions consistent over
time. Embeddings may be added later only if a versioned eval shows the TOC path
failing.

### 4. Student model

Assessment items (prompt, concepts tested, difficulty, rubric), attempts
(multi-concept, confidence before feedback, evaluation, error category), concept
mastery (a per-user ladder: unseen → exposed → can recognize → can reproduce with
cues → can apply independently → can transfer — not one fake-precise score), and
recommendations ("what to study next," traceable to attempts and concepts).

### 5. Chat history

Conversations are stored in **two forms**: the raw turns (what the user sees) and
a compressed summary (what the model is prompted with), regenerated when the
conversation grows past a threshold so context stays current without paying for
full transcripts.

### 6. Evidence & grounding

The enforcement layer for source grounding: responses → claims → citations →
retrieval traces. Every claim links to the evidence that grounds it (chunk,
memory object, or TOC entry); every response records what was retrieved.
`ArtifactOrigin` records how generated content was produced; `ModelDecision`
records the model's storage/description decisions so they can be audited and
regenerated.

## MVP

Build a single-course MVP for a small set of users.

### MVP user stories

1. I can create an account and upload PDFs, Markdown notes, and text for one course.
2. I can ask a question and receive an answer with citations to the uploaded material.
3. I can view a concept page containing a course-specific definition, prerequisite links, examples, and source evidence.
4. I can request a short closed-notes diagnostic constrained to selected study periods/topics.
5. I can answer the diagnostic, state my confidence beforehand, and receive feedback.
6. The system stores my errors by concept and displays the evidence behind any recommendation.
7. I can ask, "What should I work on next?" and get a transparent answer grounded in my attempts and the course's current material.
8. I can delete a course (a compressed memory is archived; 90-day copy grace) or my account (7-day grace).

### MVP success criteria

The MVP is useful if, for one real course:

- source citations are correct on a manually checked evaluation set;
- a cold probe exposes at least some real gaps that rereading would not reveal;
- recommendations can be traced to specific attempts and concepts;
- the student uses it repeatedly for at least two weeks;
- it saves time or improves study decisions compared with manually searching files and guessing what to review.

## Technical requirements (agreed)

- **Backend:** Python / FastAPI under `src/backend/`, one package per subsystem.
- **Database:** Postgres via raw SQL (no ORM). Versioned, append-only migrations
  (`common/migrations/00X_*.sql`, currently 001–017) applied by a runner
  (`common/migrate.py`). Extracted text + metadata are the source of truth;
  giant raw originals are trimmed after a confirmed parse. Uploads live under
  `STORAGE_ROOT` on disk, named by server-generated IDs, accounted in the DB.
- **Inference:** hosted model APIs (no data retention), multiple models per
  task routed by tier from `configs/tiers.toml`: free tier gets the cheap
  generative model (DeepSeek v4 flash), paid gets the newer one, a small
  stable model writes the TOC, OCR only if scanned materials actually appear.
- **Frontend:** separate codebase (`src/frontend/`), talks to backend only via API.
- **Auth:** email + password (bcrypt, 12+ chars), JWT with issuer/audience
  validation; per-user isolation throughout.
- **Config:** tunables versioned in `configs/` (`ingestion.toml`,
  `tutor.toml`, `tiers.toml`, `lifecycle.toml`); credentials in `.env`
  (gitignored, `STORAGE_ROOT` for upload files).

## Evaluation plan

Evaluation is the center of the project, not an afterthought.

### 1. Retrieval evaluation

Create 30–50 course questions with known supporting passages. Measure recall@k,
citation precision, and source preference (instructor material when it should be
used).

### 2. Answer evaluation

For a small held-out set, manually score factual correctness against source
material, citation correctness, course-notation fidelity, appropriate
uncertainty, and usefulness.

### 3. Probe evaluation

For generated questions, assess alignment with selected concepts, whether the
answer is supported by allowed material, whether it tests application rather
than wording, and whether it leaks solutions.

### 4. Student-model evaluation

Do not initially claim predictive validity. Check that flagged weak concepts
match the student's own review, error clusters are coherent, recommendations are
actionable, and cold-probe outcomes improve over repeated attempts.

## Fine-tuning roadmap

Fine-tuning is phase two or three, not the MVP. Do not fine-tune until there is a
versioned evaluation set, a documented baseline failure, enough high-quality
examples, and a clear metric. Good early targets: a structured-extraction model
for course concepts, a reranker, a probe generator, an error classifier.

## Privacy and academic integrity

- Data ownership: course data and study history live in our Postgres.
- Inference only through providers that do not retain data.
- Never ingest classmates' work without permission.
- Do not automatically submit answers, solve graded assignments on demand, or conceal source use.
- Separate practice mode from assignment-reference mode.
- Visible evidence for every response based on course material.
- Public visibility exposes published course objects without granting compute or
  raw-source access. Enrollment unlocks source-backed retrieval and generation,
  never access to another student's attempts, conversations, mastery,
  recommendations, preferences, or private artifacts. Only the owner can mutate
  canonical course objects and base sources.
- **Deletion:** a course becomes an exact 90-day archive, copyable by current
  participants throughout the grace period. Expiry purges the full course
  tree and physical files through a durable retry job; only the course
  owner's bounded course-memory node survives. Account deletion has a 7-day
  grace period before full removal.

## Milestones

- [x] **Milestone 0: Foundations** — project scaffolding, tooling, six-layer
  Pydantic schema, Postgres migrations + runner, deletion design.
- [x] **Milestone 0.5: Accounts, courses, access & metering** — auth (JWT +
  bcrypt), course CRUD with tier gating, the three course shapes, enrollment
  (self/invitation/join-code), owner/member permissions, canonical code
  format, storage layer (streaming uploads, dedup, conditional gzip), tiers +
  weekly budgets + generation ledger, support/premium claim codes, and the
  two-phase course archive (90-day grace → purge, owner's course-memory
  node survives).
- [ ] **Milestone 1: Source-grounded retrieval** — ingestion wiring into the
  pipeline (parse → locators → chunks → TOC), TOC-guided retrieval, cited
  answers, retrieval traces. *Status: deterministic stages done (text →
  locators → chunks, run ledger, queue claims, budget-gated provider seam
  failing closed until a provider is chosen); worker loop + API handoff +
  retrieval + tutor remain.*
- [ ] **Milestone 2: User + course memory** — the memory tree of decision
  007: elevate tutor profiles into the user-memory root (behavioral,
  cross-course), evolve the owner's course-memory node from a content
  summary into FOCUS memory as student data accumulates; plus concept/
  dependency extraction with evidence, inspectable concept pages.
- [ ] **Milestone 3: Cold probe loop** — diagnostics, confidence capture,
  scoring, error categories, per-concept history.
- [ ] **Milestone 4: Adaptive recommendations** — transparent "what to study
  next," weekly review view.
- [ ] **Milestone 5: Generated artifacts** — flashcards, practice tests,
  slideshows as course objects with artifact origin records.
- [ ] **Milestone 6: Fine-tuning experiment** — only on a documented baseline
  failure, against a frozen eval set.

## Open questions

- Which model provider (OpenRouter / Groq / similar)? Verify no-retention policy before committing.
- How will mathematical notation and diagrams be represented and cited?
- How much manual review of course-knowledge objects is acceptable?
- How should a student override an incorrect concept link or mastery inference?
- What does "mastery" mean for a proof course versus a programming/data course?

## Definition of done for v1

A student can create an account, upload one course's materials, ask
source-cited questions, take a short closed-notes diagnostic, review their
concept-linked mistakes, and receive a transparent recommendation for what to
study next. The system records provenance for every claim, archives a distilled
record on deletion, and has a small regression/evaluation suite that prevents
silent quality loss.
