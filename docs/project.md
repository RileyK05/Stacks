# Project: Stacks — course memory and adaptive study

## One-line idea

A desktop study tool that ingests a student's course materials, keeps
source-grounded course knowledge plus a course-memory focus record
(decision 007), and helps the student decide what to study next. It runs
on the student's own laptop, with a small open model by default and any
cloud model the student chooses (decision 012).

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

One student on their own machine, using it for their own courses. No
accounts, no server: one SQLite database per user in their app-data
folder. Not an LMS, not a universal tutor — a useful personal instrument
that can be evaluated on real courses. The target is an ordinary laptop
(8 GB RAM minimum, 16 GB recommended).

## Product principles

- **Source grounded:** substantive academic answers link to uploaded source material. Every claim carries an evidence chain.
- **Inspectable:** the system shows what it retrieved, what it inferred, and why it believes a concept is weak or mastered.
- **The user owns their data:** course material and study history stay in
  the user's data folder. The default model runs locally; a cloud provider
  is used only if the user picks one, after a one-time notice of what it
  receives. A whole course can be exported as one `.course` file.
- **Course-specific:** preserve a professor's notation, definitions, rubrics, and examples rather than replacing them with generic explanations.
- **Small models, strong harness:** the harness frames each task (prompt,
  output schema, bounded citations) so a ~2B local model does narrow,
  checkable work. Every model call is recorded in a local usage ledger.
- **Learning over completion:** the tool helps practice and diagnose understanding, not produce assignments for submission.
- **ML earns its role:** begin with retrieval, structure, and simple measurable baselines; add fine-tuning only for documented failures.
- **Extensible by design:** new content kinds, locator types, and formats are free strings — they insert without schema redesign.
- **Destruction leaves a distilled record:** a deleted course sits in the
  trash for 30 days; purging it keeps only its bounded, evidence-bearing
  course-memory keepsake.

## Non-goals

- Predicting grades from a calendar or course schedule.
- Rebuilding Canvas, Notion, Anki, or a generic PDF-chat wrapper.
- Claiming the student understands something solely because they read it or asked a question.
- Blindly fine-tuning a model on all uploaded files.
- Automating graded coursework in ways that undermine actual learning.

## Core system model

The system has six layers (mirrored by `src/backend/common/schemas/`). The
SQLite baseline (migration 001) holds layers 1–3 and 6; the student model
and chat history are designed below and land with Milestones 3–4.

### 1. Courses

Courses and their uploaded sources. `kind` is a free string;
`content_type` routes storage/serving. A course can be exported to a
`.course` file (the original files plus a manifest) and imported on
another machine, where normal ingestion rebuilds everything else.

Tutor preferences change presentation, not truth or retrieval.
Presentation is a user-memory (root) concern per decision 007 and may not
alter the TOC, evidence selection, citations, or mastery evaluation.

### 2. Source content

Materials are stored **whole** — nothing is destroyed at ingest. Uploads
stream to disk under a hard byte ceiling, are stored under generated names
(path traversal structurally impossible), and are gzip-compressed only
when the mime type allows and it saves ≥10% (`stored_encoding`:
`identity` / `gzip`). Each source gets **locators**: a free-typed
per-format table of contents (slide 7, page 3, timestamp 12:30, cell range
A1:D20 — each format keeps its natural unit). Retrieval units are
**token-bounded chunks**, each stored once with its locator set in a join
table (`chunk_locators`). Sources carry `file_hash` for dedup. Ingestion
is an ordered, versioned pipeline: text extraction → OCR (image-only PDFs;
rasterization-capped) → locators → chunks → chunk embeddings → TOC update →
course-knowledge extraction. A stage runs only after its dependency
succeeds, retries per versioned configuration, and stops the pipeline with
an inspectable error when its attempts are exhausted.

### 3. Course knowledge (not memory; decision 007)

Concepts (with synonyms, evidence levels), dependencies (nullable prereq,
in-course or external — Calc 2 can depend on Calc 1), memory objects
(concepts/formulas/theorems/examples/misconceptions with evidence), and the
**table of contents**: a per-course, versioned index of what's in the
course and where, built from the author's own structure when the file has
one.

**Retrieval is hybrid four-seam (decision 008).** Keyword (SQLite FTS5),
TOC routing, dependency walk, and embeddings generate candidates; fusion
normalizes and allocates the cited set, and a cross-encoder reranker picks
what the model reads. Each seam must beat the funnel without it on the
eval set, and fusion must beat the best single seam, or it is dropped.

### 4. Student model

Assessment items (prompt, concepts tested, difficulty, rubric), attempts
(multi-concept, confidence before feedback, evaluation, error category), concept
mastery (a ladder: unseen → exposed → can recognize → can reproduce with
cues → can apply independently → can transfer — not one fake-precise score), and
recommendations ("what to study next," traceable to attempts and concepts).

### 5. Chat history

Conversations are stored in **two forms**: the raw turns (what the user
sees) and a compressed summary (what the model is prompted with),
regenerated when the conversation grows past a threshold so a small
model's context stays current.

### 6. Evidence & grounding

The enforcement layer for source grounding: responses → claims → citations →
retrieval traces. Every claim links to the evidence that grounds it (chunk,
memory object, or TOC entry); every response records what was retrieved.
`ArtifactOrigin` records how generated content was produced; `ModelDecision`
records the model's storage/description decisions so they can be audited and
regenerated.

## MVP

A single-course MVP for one student on their own laptop.

### MVP user stories

1. I can install the app, create a course, and upload PDFs, Markdown notes, and text.
2. I can ask a question and receive an answer with citations to the uploaded material — and see the cited passages ("sources used") without leaving the answer.
3. I can view a concept page containing a course-specific definition, prerequisite links, examples, and source evidence.
4. I can request a short closed-notes diagnostic constrained to selected topics.
5. I can answer the diagnostic, state my confidence beforehand, and receive feedback.
6. The system stores my errors by concept and displays the evidence behind any recommendation.
7. I can ask, "What should I work on next?" and get a transparent answer grounded in my attempts and the course's current material.
8. I can delete a course (30 days in the trash; its course memory survives the purge) and export or import a course as one file.

### MVP success criteria

The MVP is useful if, for one real course:

- source citations are correct on a manually checked evaluation set;
- a cold probe exposes at least some real gaps that rereading would not reveal;
- recommendations can be traced to specific attempts and concepts;
- the student uses it repeatedly for at least two weeks;
- it saves time or improves study decisions compared with manually searching files and guessing what to review;
- answers stay usable on the floor machine (< 30 s each on 8 GB RAM, no GPU).

## Technical requirements (agreed)

- **App:** a Tauri v2 shell showing the SvelteKit SPA, with the FastAPI
  backend (frozen by PyInstaller) as a child process; shipped as a
  per-user installer. A per-launch token between the window and the
  backend is the only auth.
- **Backend:** Python / FastAPI under `src/backend/`, one package per subsystem.
- **Database:** SQLite (WAL, foreign keys, FTS5) via raw SQL, no ORM.
  Versioned, append-only migrations (`common/migrations/00X_*.sql`) applied
  by `common/migrate.py`. Every foreign key cascades.
- **Generation:** one seam, `common/provider.py`, routed per task class
  (interactive answers, background work, and an optional "bigger model")
  to the endpoint the user chose in Settings: the bundled llama.cpp server
  (default MiniCPM5-2B; others in `configs/runtime.toml`), OpenRouter,
  OpenAI, or any OpenAI-compatible endpoint. Keys live in the OS keychain.
- **Encoders:** embeddings (IBM granite-embedding-english-r2) and the
  reranker run in-process on ONNX Runtime, pinned and checksummed. Model
  choice is a pencil mark: `chunk_embeddings` rows are keyed by model name,
  so a swap is re-ingest, not a rewrite.
- **Frontend:** separate codebase (`src/frontend/`), talks to the backend only via its API.
- **Config:** tunables versioned in `configs/` (`ingestion.toml`,
  `retrieval.toml`, `embeddings.toml`, `models.toml`, `runtime.toml`,
  `prompts.toml`, `tutor.toml`, `lifecycle.toml`). `.env` holds only
  optional development settings.

## Evaluation plan

Evaluation is the center of the project, not an afterthought. The
mechanical harness is live (decision 010): retrieval
(`retrieval/evals.py` + `data/eval/retrieval/cases.json`) and the answer
harness (`evals/answer.py` + `data/eval/answer/cases.json`, mechanical
scorers, prompt-version-stamped logs under `runs/`).
`scripts/eval_models.py` runs it against the bundled runtime, any model in
the catalog, and optionally a real course.

### 1. Retrieval evaluation

Create 30–50 course questions with known supporting passages. Measure recall@k,
citation precision, and source preference (instructor material when it should be
used).

### 2. Answer evaluation

For a small held-out set, score factual correctness against source
material, citation correctness, course-notation fidelity, appropriate
uncertainty, and usefulness. *Status: the mechanical half is live —
citation validity, refusal honesty, steer behavior per decision 009's
three zones, workspace output. LLM-judged qualities (notation fidelity,
usefulness) are open.*

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

- Course data and study history stay on the user's machine unless the user
  exports them.
- Nothing is sent to a cloud model unless the user chooses one; the
  one-time notice says what it receives.
- Never ingest classmates' work without permission.
- Do not automatically submit answers, solve graded assignments on demand, or conceal source use.
- Separate practice mode from assignment-reference mode.
- Visible evidence for every response based on course material.

## Milestones

- [x] **Milestone 0: Foundations** — scaffolding, tooling, six-layer
  Pydantic schema, migrations + runner, deletion design.
- [x] **Milestone 0.5: Hosted accounts and metering** — built for the
  hosted version (accounts, tiers, enrollment, sharing), then replaced by
  decision 012. That version lives on in the original hosted repository.
- [x] **Milestone 1: Source-grounded retrieval** — the ingestion pipeline,
  hybrid four-seam retrieval with fusion + traces (decision 008), the
  worker loop, the tutor endpoint (ask with strict refusal), and the
  citations endpoint behind the "sources used" panel.
- [x] **Milestone 1.5: Local-first desktop** — SQLite, the bundled
  llama.cpp runtime, provider choice, ONNX encoders, task framing, the
  desktop shell and packaging (`docs/plan-local-first.md`).
- [ ] **Milestone 2: User + course memory** — the memory tree of decision
  007: elevate tutor profiles into the user-memory root (behavioral,
  cross-course), evolve the course-memory node from a content summary
  into FOCUS memory as student data accumulates; plus concept/dependency
  extraction with evidence, inspectable concept pages.
- [ ] **Milestone 3: Cold probe loop** — diagnostics, confidence capture,
  scoring, error categories, per-concept history.
- [ ] **Milestone 4: Adaptive recommendations** — transparent "what to study
  next," weekly review view.
- [ ] **Milestone 5: Generated artifacts** — flashcards, practice tests,
  slideshows as course objects with artifact origin records; the
  three-zones assistance policy (decision 009) governs them.
- [ ] **Milestone 6: Fine-tuning experiment** — only on a documented baseline
  failure, against a frozen eval set.

## Open questions

- How will mathematical notation and diagrams be represented and cited?
  (Extraction is text-only; image-only PDFs need local OCR, which is
  planned but not yet bundled.)
- How much manual review of course-knowledge objects is acceptable?
- How should a student override an incorrect concept link or mastery inference?
- What does "mastery" mean for a proof course versus a programming/data course?
- How well does the default model hold up on the 8 GB floor machine?

## Definition of done for v1

A student can install the app, upload one course's materials, ask
source-cited questions, take a short closed-notes diagnostic, review their
concept-linked mistakes, and receive a transparent recommendation for what to
study next — all on their own laptop. The system records provenance for
every claim, keeps a distilled record when a course is purged, and has a
small regression/evaluation suite that prevents silent quality loss.
