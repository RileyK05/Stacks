# Project: Course Memory and Adaptive Study System

## One-line idea

Build a local-first academic assistant that continuously ingests course materials, preserves source-grounded course memory, learns from a student's study attempts over time, and helps the student decide what to study next.

This is **not** just “chat with PDFs.” The useful output is an inspectable, evolving model of:

1. what the course materials say;
2. how the course concepts connect;
3. what the student appears to understand, misunderstand, and need to practice.

## Problem

A course creates fragmented information:

- syllabi, slides, readings, problem sets, solutions, lecture notes, and announcements live in different places;
- course-specific notation and definitions differ from generic textbook explanations;
- ordinary chat-with-PDF tools retrieve passages but do not accumulate a reliable model of the course;
- grades and exams arrive late, giving weak feedback about whether the student actually understands a topic;
- the student’s mistakes are usually corrected once and then lost rather than turned into a reusable error model.

The project should make course work compound across a semester. It should help answer:

> What does this course actually say about this concept, what prerequisites does it rely on, and what should I practice next to demonstrate independent understanding?

## Primary user

Initially: one student using it for their own courses and self-directed learning.

The initial goal is not a multi-user product, a learning-management system, or a universal tutor. It is a useful personal instrument that can be evaluated on a real course.

## Product principles

- **Source grounded:** substantive academic answers link to uploaded source material.
- **Inspectable:** the system shows what it retrieved, what it inferred, and why it believes a concept is weak or mastered.
- **Local-first:** course material and study history should remain local by default; Ollama/local models are first-class.
- **Course-specific:** preserve a professor’s notation, definitions, rubrics, and examples rather than replacing them with generic explanations.
- **Learning over completion:** the tool should help practice and diagnose understanding, not produce assignments for submission.
- **ML earns its role:** begin with retrieval, structure, and simple measurable baselines; add fine-tuning only for documented failures.

## Non-goals

- Predicting grades from a calendar or course schedule.
- Rebuilding Canvas, Notion, Anki, or a generic PDF-chat wrapper.
- Claiming the student understands something solely because they read it or asked a question.
- Blindly fine-tuning a model on all uploaded files.
- Automating graded coursework in ways that undermine actual learning.

## Core system model

The system has five layers.

### 1. Source library

Stores original material and immutable metadata.

Examples:

- syllabus;
- lecture slides;
- textbook chapters;
- problem sets and, where appropriate, solutions;
- student notes;
- instructor feedback;
- past exams only when permitted.

Each item receives a source ID, course ID, date/version, page/slide location, section, and source type.

### 2. Retrieval index

Chunks source materials while retaining source provenance. Retrieval should return exact passages, page numbers, and source type—not just an embedding match.

Metadata filters should support questions such as:

- only use lecture slides from Week 3;
- prefer instructor-authored sources;
- exclude solutions when creating a cold probe;
- retrieve materials relevant to `MATH 361 / estimation / sufficiency`.

### 3. Course memory

A structured, versioned semantic layer built from sources and reviewed as needed. It should be small enough to inspect and revise.

Possible entities:

- `Concept`: name, course-specific definition, sources, examples;
- `Formula/Theorem`: statement, assumptions, notation, sources;
- `Dependency`: prerequisite concept -> dependent concept;
- `Example`: problem type, solution outline, concept tags;
- `Misconception`: a common incorrect rule or confusion;
- `AssessmentItem`: source, concepts tested, difficulty, rubric;
- `CourseWeek`: topics, assigned materials, relevant assessments.

Every generated memory object must retain evidence links. The system should distinguish:

- directly supported by source;
- derived from source;
- hypothesis awaiting student/instructor review.

### 4. Student model

Records evidence about the student’s understanding, not vague engagement metrics.

For every cold attempt or practice response, log:

- concept tags;
- question version;
- answer and evaluation;
- predicted confidence before feedback;
- correctness / partial credit;
- error category;
- time spent, if available;
- date;
- whether help or notes were used.

Example mastery states:

- `unseen`;
- `exposed`;
- `can recognize`;
- `can reproduce with cues`;
- `can apply independently`;
- `can transfer to a new context`.

Do not collapse all this to a single fake-precise score too early.

### 5. Tutor and evaluator

Uses retrieval + course memory + student model to provide:

- source-grounded explanations;
- concept maps and prerequisite paths;
- short cold probes;
- feedback classified into useful error types;
- targeted practice recommendations;
- a weekly “what to study next” view.

## MVP

Build a single-course, local-first MVP.

### MVP user stories

1. I can upload PDFs, Markdown notes, and text for one course.
2. I can ask a question and receive an answer with citations to the uploaded material.
3. I can view a concept page containing a course-specific definition, prerequisite links, examples, and source evidence.
4. I can request a short closed-notes diagnostic constrained to selected weeks/topics.
5. I can answer the diagnostic, state my confidence beforehand, and receive feedback.
6. The system stores my errors by concept and displays the evidence behind any recommendation.
7. I can ask, “What should I work on next?” and get a transparent answer grounded in my attempts and the course’s current material.

### MVP success criteria

The MVP is useful if, for one real course:

- source citations are correct on a manually checked evaluation set;
- a cold probe exposes at least some real gaps that rereading would not reveal;
- recommendations can be traced to specific attempts and concepts;
- the student uses it repeatedly for at least two weeks;
- it saves time or improves study decisions compared with manually searching files and guessing what to review.

## Example workflow

1. Upload Week 1 slides, reading, and Problem Set 1.
2. Ingestion extracts text, chunks it, embeds it, and records provenance.
3. The extractor proposes concepts such as `random variable`, `likelihood`, and `estimator`, each with source citations.
4. The student asks: “Explain sufficiency using only the lecture notation, then give one contrasting non-example.”
5. The system retrieves the relevant passages, uses the course memory, and presents an evidence-backed answer.
6. The student asks for a 10-minute cold probe on the week’s material and predicts 80% confidence.
7. The system scores the response, labels errors, and records evidence: e.g. “correct definition, but did not state the factorization condition.”
8. Next session, it recommends a targeted problem and names the exact source sections to revisit.

## Architecture sketch

```text
                 +--------------------+
                 | Uploaded materials |
                 | PDFs / notes / HW  |
                 +---------+----------+
                           |
                    ingestion pipeline
                           |
          +----------------+----------------+
          |                                 |
+---------v----------+            +---------v----------+
| Source-aware vector|            | Structured course   |
| index + metadata   |            | memory / concept DB |
+---------+----------+            +---------+----------+
          |                                 |
          +---------------+-----------------+
                          |
                   retrieval + context
                          |
                 +--------v---------+
                 | Local LLM / tutor|
                 +--------+---------+
                          |
          +---------------+----------------+
          |                                |
+---------v-----------+          +---------v-----------+
| Cold probes / rubric|          | Student model        |
| evaluation          |          | attempts + errors    |
+---------------------+          +---------------------+
```

## Suggested technical path

### Initial stack

Keep the first version deliberately boring:

- Python backend;
- local SQLite or Postgres for metadata and student history;
- local file storage for original materials;
- a local vector store or vector extension;
- Ollama for generation and embeddings where appropriate;
- FastAPI for the API;
- a minimal local web UI or terminal interface;
- Pydantic/Pandera-style validation for ingestion records;
- experiment and eval logs stored as files or MLflow once model comparisons begin.

Avoid microservices, Kubernetes, and hosted infrastructure in the MVP.

### Ingestion pipeline

1. Accept file.
2. Extract text while retaining page/slide offsets.
3. Detect document type and course/week metadata.
4. Chunk with section-aware boundaries.
5. Embed chunks and write to retrieval index.
6. Extract candidate concepts/definitions/formulas with evidence references.
7. Validate generated memory objects against a schema.
8. Present uncertain or conflicting extractions for review.

### Retrieval rules

- Never answer an uploaded-material question without showing sources.
- Prefer instructor sources over student notes when both address the same fact.
- When generating cold probes, block solution documents from context.
- Use a reranker after initial vector retrieval.
- Store retrieval traces for evaluation and debugging.

## Evaluation plan

Evaluation is the center of the project, not an afterthought.

### 1. Retrieval evaluation

Create 30–50 course questions with known supporting passages.

Measure:

- recall@k: does the evidence appear in the retrieved context?
- citation precision: does the cited passage actually support the answer?
- source preference: does the system use instructor material when it should?

### 2. Answer evaluation

For a small held-out set, manually score:

- factual correctness against source material;
- citation correctness;
- course-notation fidelity;
- appropriate uncertainty;
- usefulness to the student.

### 3. Probe evaluation

For generated questions, assess:

- alignment with selected concepts;
- whether the answer is supported by allowed material;
- whether it tests retrieval/application rather than mere wording;
- whether it leaks solutions or includes ambiguous grading criteria.

### 4. Student-model evaluation

Do not initially claim predictive validity. Start by checking whether:

- flagged weak concepts match the student’s own review after a session;
- error clusters are coherent;
- the tool’s next-study recommendations are actionable;
- cold-probe outcomes improve over repeated attempts.

Later, compare tool estimates against quiz/exam results only if ethically and practically appropriate.

## Fine-tuning roadmap

Fine-tuning is phase two or three, not the MVP.

### Preconditions

Do not fine-tune until there is:

- a versioned evaluation set;
- a documented baseline failure;
- enough high-quality examples of the desired behavior;
- a clear metric that can improve or regress.

### Good early fine-tuning targets

- A small structured-extraction model for course concepts, formulas, and source links.
- A reranker trained on accepted/rejected retrieved chunks.
- A probe generator trained on approved question/rubric pairs.
- An error classifier trained on manually reviewed student mistakes.

### Explicit experiments

1. **RAG-only baseline:** local model + source retrieval + prompt template.
2. **Improved retrieval:** hybrid retrieval / reranker / metadata filters.
3. **Fine-tuned component:** compare against the frozen baseline on the held-out eval set.
4. **Decision:** keep the fine-tuned component only if it clearly improves the target metric without damaging citation quality or privacy.

## MLOps / engineering learning goals

This project should deliberately teach:

- data provenance and dataset versioning;
- reproducible ingestion and model runs;
- evaluation datasets and regression tests;
- prompt/model/retrieval configuration versioning;
- model registry or a simple model manifest;
- monitoring for ingestion failures, retrieval regressions, and stale course memory;
- safe rollback to a known-good model/index configuration.

A useful directory structure might be:

```text
project/
  data/
    raw/                 # not committed; original course files
    processed/
    eval/
  configs/
  src/
    ingest/
    retrieval/
    memory/
    student_model/
    tutor/
    evals/
  tests/
  runs/
  docs/
  model_manifest.yaml
```

## Privacy and academic integrity

- Default to local storage and local inference.
- Never ingest classmates’ work without permission.
- Do not automatically submit answers, solve graded assignments on demand, or conceal source use.
- Separate practice mode from assignment-reference mode.
- Include visible provenance for every response based on course material.
- Support deletion of a course and all derived indexes/memory.

## Milestones

### Milestone 0: Define the pilot

- Select one course.
- Choose 3–5 initial source files.
- Write 15 manually answerable evaluation questions.
- Decide the minimal useful interaction: probably source-grounded explanation + cold probe.

### Milestone 1: Source-grounded retrieval

- Ingest files locally.
- Build chunk metadata and retrieval.
- Return citations with answers.
- Log retrieval traces.

### Milestone 2: Course memory

- Build concept/formula/dependency schemas.
- Extract and store source-backed memory objects.
- Create inspectable concept pages.

### Milestone 3: Cold probe loop

- Generate or select short practice questions.
- Capture answer, confidence, scoring, and error category.
- Create a basic per-concept history view.

### Milestone 4: Adaptive recommendations

- Recommend the next concept/problem using transparent rules.
- Add a weekly review view.
- Measure whether recommendations are useful over two weeks.

### Milestone 5: Fine-tuning experiment

- Choose one documented baseline failure.
- Create a clean training/evaluation split.
- Fine-tune a small component or local model.
- Keep it only if it wins on the pre-registered metric.

## First tasks

1. Pick a pilot course with accessible materials and a reason to use the tool every week.
2. Create the course/source metadata schema.
3. Build a tiny ingestion command for PDF/Markdown/text.
4. Make one source-grounded question-answer endpoint with page-level citations.
5. Hand-author 15 evaluation questions before optimizing anything.
6. Add one cold-probe workflow and log the student response.

## Open questions

- What input formats are most common: slides, scanned PDFs, Markdown notes, notebooks, or LMS exports?
- How will mathematical notation and diagrams be represented and cited?
- Which evaluation tasks matter most for the pilot: explanation, retrieval, probe generation, or error classification?
- How much manual review of course-memory objects is acceptable?
- How should a student override an incorrect concept link or mastery inference?
- What does “mastery” mean for a proof course versus a programming/data course?

## Definition of done for v1

A student can upload one course’s materials, ask source-cited questions, take a short closed-notes diagnostic, review their concept-linked mistakes, and receive a transparent recommendation for what to study next. The system works locally, records provenance, and has a small regression/evaluation suite that prevents silent quality loss.
