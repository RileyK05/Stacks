# Plan: Stacks as a course notebook

Created: 2026-09-25. **Approved direction** (owner review 2026-09-25; the
answers are in §8 and decision 013). Builds on `docs/plan-local-first.md`
(the desktop app, done through Phase 6's installer) and decisions 007
(memory), 009 (three zones), 011 (workspace items). Check items off as
they land.

---

## 1. Goal

Stacks is a **course notebook**: one notebook per course, holding the
course's sources, your conversations about them, and the artifacts you
make with the model — docs, spreadsheets, slide decks, quizzes,
flashcards — all cited back to the sources, all on your own laptop.

The closest reference is **NotebookLM** (sources → grounded chat → study
outputs), with **hints of Notion and Office**: real documents, sheets and
decks you edit yourself or together with the model. What none of them
has, and Stacks does, is that it **learns you**: which concepts you're
weak on, what you got wrong, and what to study next.

### What Stacks is not

- **Not a general assistant** (ChatGPT, Cowork). Every conversation lives
  inside a course and answers from that course's material. No web search,
  no agents acting on your computer.
- **Not a general workspace** (Notion). Artifacts and tables exist to
  study a course, not to run a life or a team wiki.
- **Not an LMS.** No teachers, no grading of submissions, no sharing
  platform (a course can still be exported as a `.course` file).
- **No audio or video overviews.** Stacks sticks to its strong spot:
  grounded answers, editable study material, and knowing the student.

The golden rules still hold: answers cite sources, the app shows its
reasoning (what it retrieved, why it thinks you're weak on something),
your data stays on your machine, and it helps you learn graded work
rather than doing it for you.

## 2. Starting point

| Area | Today | Gap |
|---|---|---|
| Courses + sources | Upload, ingest, locators, chunks, embeddings, TOC from author structure, trash, `.course` export/import | Viewing a source at the cited passage; choosing which sources a chat uses |
| Grounded chat | Task-framed answers with citations, reranker, answer cache, "Ask a bigger model" | **Nothing is saved** — closing the course loses the chat |
| Workspace items | quiz, document, html, code, sheet, slides (decision 011), cited and gated | **Ephemeral by design**; editing is local drafts only |
| Course knowledge | Tables exist (`concepts`, `dependencies`, `memory_objects`) | **Extraction is a skip**: the real course has 43 chunks, 24 TOC entries, **0 concepts** |
| Student model | Designed (project.md §4), packages empty | Not started |
| Memory | Course memory = a content-summary keepsake; the behavioural root is tutor profiles | Focus memory and the user-memory root not built |
| Models | Catalog of 6 local models (download on demand, MiniCPM5-2B default), 3 slots, one key each for OpenAI / OpenRouter + one custom endpoint | No model picker in chat; one key per provider; no per-model profiles; can't add a model outside the catalog |

## 3. The course screen

```
┌──────────────┬───────────────────────────────┬──────────────────────┐
│ Chats        │ Chat                          │ Artifacts            │
│ + New chat   │ [Model ▾]  Sources: 2 of 3 ▾  │ + New ▾              │
│ Week 2 recap │                               │ 📄 Study guide Ch. 2 │
│ Exam prep    │ … answer with [1][2] …        │ 📊 Key dates         │
│              │ [Save as doc] [Bigger model]  │ 🖼 Week 3 slides     │
│ Sources      │                               │ ❓ Practice quiz     │
│ ☑ Syllabus   │ Ask about this course…        │                      │
│ ☑ Ch. 2      │                               │ (opens full editor)  │
└──────────────┴───────────────────────────────┴──────────────────────┘
```

A **course home** sits above it: what to study next, upcoming dates from
the syllabus, weak concepts, recent chats and artifacts. Opening an
artifact gives it the full width with its editor, and the chat can sit
beside it to work on it together.

## 4. Features

### 4.1 Sources

- **Source viewer.** Clicking a citation opens the original file at the
  cited page with the passage shown (PDF pages rendered; text and
  markdown natively).
- **Source selection.** A conversation can be narrowed to chosen sources
  (NotebookLM's checkboxes).
- **Per-source summary**, generated in the background (study pack, §4.5).

### 4.2 Conversations

- **Unlimited individual chats per course**, closer to Cowork: a list in
  the course sidebar, each renamable and deletable, each titled from its
  first question.
- What carries across chats is the course itself: its **memory**, its
  **artifacts**, its sources and concepts. A chat is a working session;
  the course is what accumulates.
- Each message keeps its trace (what was retrieved), citations, model and
  cache flag, so an old answer still opens its sources.
- Long chats are compressed for the model: you see the raw turns; a small
  model is prompted with the recent turns plus a rolling summary.
- **Model picker** per chat (and "Ask a bigger model" per answer).

### 4.3 Artifacts (decision 013: typed and editable)

Everything the model makes for you, and everything you write, is an
**artifact** of a real type, saved in the course, with its own editor:

| Type | Editor | Export |
|---|---|---|
| **Doc** | Rich block editor (headings, lists, quotes, callouts, code, math, tables); slash menu; markdown shortcuts | .docx, .md |
| **Sheet** | Grid: type in cells, add/remove rows and columns, sort | .xlsx, .csv |
| **Slides** | Slide list + slide editor (title, body, notes); present full-screen | .pptx |
| **Quiz** | Take it: pick answers, confidence first, score, review | — |
| **Flashcards** | Flip and grade yourself; feeds practice (§4.7) | .csv |
| **Code**, **chart/HTML** | Highlighted / sanitized view (never executed) | file |

- **Collaboration with the model.** From an artifact you can ask the
  model to change it ("make slide 3 shorter", "add a due-date column",
  "turn section 2 into a quiz"). The model's edit arrives as a proposed
  change you **accept or undo**; anything it adds from the sources is
  cited and passes the citation gate.
- **Citations stay live**: a citation inside an artifact opens the source
  passage. What you write yourself needs no citation.
- **Save from chat**: any answer or workspace item can be saved as an
  artifact (a new one, or appended to a doc).
- **Version history**: every save keeps a version; restore any of them.
- Artifacts belong to the course (not to a chat), travel in the `.course`
  file (format version 2), and are listed on the course home.

### 4.4 Concepts (course knowledge, finally extracted)

- **Decomposed extraction** at ingestion: per chunk, a narrow task — "list
  the terms this passage defines, quoting the defining sentence" — verified
  verbatim like quote mode. Then merge duplicates (embeddings + names) and
  link prerequisites (TOC order + "uses the term" evidence).
- **Concept pages**: definition in the course's words, where it appears,
  prerequisites and dependents, examples, and how well you know it.
- **Concept map**: concepts and prerequisite links as a navigable graph.

### 4.5 Study materials (made as artifacts)

The "Generate" menu makes artifacts from chosen sources or TOC sections:
study guide (doc, built section by section), summary/briefing (doc),
glossary (sheet, deterministic from concepts), FAQ (doc), timeline
(sheet), flashcards, practice quiz, slides. A **study pack** (per TOC
section: summary, key terms, practice questions) is generated in the
background at ingestion so these are mostly retrieval plus light rewriting.

### 4.6 Course dates

Assignments, exams and readings extracted from the syllabus, each cited to
its syllabus line and editable, shown on the course home — always with the
note: **"Double-check dates with Canvas or your course site; syllabi
change."**

### 4.7 Practice and memory (what only Stacks does)

- **Practice**: quizzes and flashcards record attempts — your answer,
  confidence *before* feedback, right or wrong, error type.
- **Mastery per concept** on the ladder (unseen → exposed → recognise →
  reproduce with cues → apply independently → transfer), always showing
  the attempts behind it.
- **What to study next** on the course home, traceable to attempts.
- **Course memory** becomes focus memory: what you struggle with and
  what you're strong in, per course, distilled from attempts.
- **User memory (root)**: how you learn, plus cross-course history.
  Study-focused only.
- **Memory summary** (decision 013): a short generated summary of what
  Stacks has learned about you — readable in Settings and on each course —
  rather than the full raw record. You can reset a course's memory or all
  of it.

### 4.8 Models and connections

- **Connections** replace fixed presets: add as many as you like — OpenAI,
  Anthropic, Google, OpenRouter, Groq, custom endpoints, your LM Studio /
  Ollama — each named, each with its own key in the OS keychain. Existing
  keys migrate over.
- **Model picker** lists local models and each connection's models;
  Settings sets the defaults per task.
- **Add a model easily**: paste a Hugging Face GGUF link (or pick a local
  `.gguf` file) and Stacks downloads it, checks it, and tries to load it,
  with a clear message if the bundled runtime can't run that architecture.
- **Per-model profiles** (`configs/models/*.toml`): reasoning on/off,
  context to use, output limit, passages to read, JSON-schema reliability.
- The installer never carries a model; the catalog is download-on-demand.
- **K2 Horizon** waits for upstream llama.cpp support (decision 013);
  then it joins the catalog with reasoning on.

## 5. Data (new migrations)

All in the one SQLite file, cascading from the course; course-owned rows
travel in the `.course` export.

| Table | Holds |
|---|---|
| `conversations` | course, title, model choice, selected sources, rolling summary |
| `messages` | conversation, role, text, trace, citations, model, cached flag, workspace payloads |
| `artifacts` | course, type, title, current content JSON, origin (model, prompt version, sources), timestamps |
| `artifact_versions` | artifact, content JSON, author (you / model), created_at |
| `course_dates` | course, title, date, kind, cited syllabus chunk, confirmed flag |
| `attempts`, `concept_mastery`, `recommendations` | the student model |
| `user_memory` | root items + per-course focus items, each with evidence; the generated summary |
| `connections` | name, kind, base URL, default model (key in the keychain under the connection id) |
| `user_models` | models added by the user (source URL / path, file, size, sha256, status) |

## 6. Keeping it small-model friendly

- Heavy work (concept extraction, study pack) runs **in the background**,
  with progress, and is reused.
- Long outputs are built **section by section** and stitched in code.
- Model edits to artifacts are **narrow operations** (edit this section /
  these rows / this slide) returned as structured changes, not whole
  rewrites — small models do targeted edits well and whole rewrites badly.
- Extracted facts are **quoted and verified verbatim**; every generated
  item passes the **citation gate**; each new item type gets **eval
  cases** before it ships.

## 7. Phases

### Phase A — conversations and models

- [ ] Saved conversations (tables, API, sidebar), traces and citations
      reopen from history; titles from the first question
- [ ] Rolling summary + recent turns as the model's chat context
- [ ] Connections: many providers/endpoints with one key each; migrate
      existing keys
- [ ] Model picker in chat; per-model profiles
- [ ] Add a model from a Hugging Face GGUF link or a local file
- [ ] Source selection per conversation

### Phase B — artifacts

- [ ] Artifacts + versions (tables, API); save from chat
- [ ] Doc editor (rich blocks), sheet editor (grid), slides editor +
      presenter, quiz and flashcards players
- [ ] Model edits as proposed changes (accept / undo), cited and gated
- [ ] Export: .docx, .xlsx, .pptx, .md, .csv
- [ ] Source viewer at the cited passage
- [ ] `.course` format version 2 carries chats and artifacts

### Phase C — course knowledge

- [ ] Decomposed concept extraction, verbatim-verified; measured
- [ ] Concept merge + prerequisites; concept pages; concept map
- [ ] Study pack at ingestion; Generate menu (study guide, summary, FAQ,
      glossary, timeline, flashcards, quiz, slides)

### Phase D — practice and memory

- [ ] Attempts with confidence-before-feedback and error types
- [ ] Mastery ladder per concept, with evidence
- [ ] Focus course memory; user-memory root; generated memory summary
- [ ] What to study next

### Phase E — course home

- [ ] Course home (next up, dates, weak concepts, recent work)
- [ ] Dates from the syllabus with the double-check note

### Later

- [ ] K2 Horizon when upstream llama.cpp supports it
- [ ] LoRA adapter for our formats

## 8. Decisions (owner, 2026-09-25)

1. **Editable artifacts**: docs, sheets and slides edited in the app, by
   the user and together with the model. Rich block editor for docs.
2. **Unlimited individual chats** per course, Cowork-style. Memory,
   artifacts and course knowledge persist across chats.
3. **Typed artifacts** (option A): each keeps its type and its own editor;
   no universal page format. "Harder is better long term."
4. **Dates from the syllabus**, always with "double-check with Canvas or
   your course site".
5. **Memory summary**, not the full record: a short generated summary is
   what the user reads.
6. **No audio/video overviews.**
7. **K2 waits** for upstream support; adding models must be easy.

## 9. Risks

| Risk | Mitigation |
|---|---|
| A 2B model writes weak long documents | Section-by-section generation, study pack, bigger-model button |
| Model edits mangle an artifact | Narrow structured edits, proposed-change review, version history |
| Concept extraction is noisy | Narrow per-chunk task, verbatim quotes, measured precision |
| Editors are a lot of UI | Established libraries where they exist (TipTap for docs); simple, well-styled grid and slide editors of our own |
| 8 GB machines | Background heavy work, per-model profiles, measure on the floor machine |
| Memory feels wrong | Summary shown, evidence kept, reset per course or overall |
