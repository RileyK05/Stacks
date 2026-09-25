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

### Phase A — conversations and models ✅

- [x] Saved conversations (migration 003, `api/conversations.py`,
      `tutor/chat.py`): chat list per course, titles from the first
      question, the open chat in the URL, traces and citations reopen from
      history; "nothing relevant" is recorded as the reply; a provider that
      is down is not (the question can be re-sent)
- [x] Rolling summary + the last two exchanges as the model's chat
      context, inside the fence; short follow-ups search with the two
      previous questions (a chain like "why?" → "an example?" keeps its
      topic). Chat answers skip the answer cache
- [x] Connections (`providers.py`): any number of endpoints from presets
      (OpenAI, Anthropic, Google, OpenRouter, Groq, LM Studio, Ollama,
      custom), one keychain key each; pre-connection choices and keys
      carry over unchanged. Settings: Default models / Local model /
      Connections
- [x] Model picker in chat (`provider.generate(choice=...)`, no silent
      fallback for a picked model); per-model profiles in `configs/models/`
      (MiniCPM5-2B reasoning off, K2 Horizon on)
- [x] Add a model from a Hugging Face GGUF link (published sha256 + size;
      pick a quant) or a local `.gguf` used in place (Tauri file dialog)
- [x] Source selection per conversation (retrieval narrowed per seam,
      over-fetching so chosen sources still fill the set)
- [x] Bug found on the way: the citation list was ordered by file, not by
      the model's numbering, so "[1]" could open the wrong excerpt. Fixed
      in the query, regression-tested

### Phase B — artifacts (mostly done; see §10 for what is left)

- [x] Artifacts + versions (migration 004, `common/artifacts_repo.py`,
      `api/artifacts.py`): every save a version (author you / model), a
      save based on an outdated copy is refused (409), restore saves the
      old version as the newest. Save from chat: "Save to artifacts" in
      the chat workspace panel; the item is read from the stored message
      and its citations pinned to that answer's chunks
- [x] Editors (`src/frontend/src/lib/components/artifacts/`): doc (TipTap
      rich editor, markdown storage, math, tables, citation chips), sheet
      (grid, add/remove/sort), slides (thumbnails, editor, live preview,
      full-screen presenter), quiz (take + edit), flashcards (study +
      edit), code, chart. Artifact page at
      `/courses/[id]/artifacts/[artifactId]` with autosave, versions,
      export, delete; Artifacts tab on the course page
- [x] Model edits as proposals (`artifacts/edit.py`): scope whole / one
      doc section / one slide; "add …" requests (and empty docs/decks) ask
      the model for only the new part and insert it, so the student's text
      is never rewritten; pasted-back material is stripped
      (`attribution.strip_echo`); new uncited lines that clearly copy a
      passage get its citation (`attribution.attach`), the rest are
      counted and shown as a warning before accepting; citations to
      material the model wasn't given are refused
- [x] Export: .docx, .xlsx, .pptx, .md, .csv, code file, .html (charts
      lose scripts/handlers); every file ends with its sources. In the
      app, Export opens a native Save dialog (Tauri)
- [~] Live-verified in the app: create doc → "Draft a short study guide
      on the course grading policy" → proposal in ~19 s with citations →
      Accept. **Not yet re-verified after the last fixes** (§10.2)
- [x] Source viewer at the cited passage (original PDF at its page;
      text/Markdown with line navigation; links from chats and artifacts)
- [x] `.course` format version 2 carries chats, artifacts, versions and
      source-scoped cited-passage snapshots; importer accepts v1 and v2

### Phase C — course knowledge

- [x] Table-aware PDF extraction. Measured on the owner's syllabus: the
      two-column grading table extracts row-interleaved ("93 - 100%A
      73 - 76%C"), and MiniCPM5-2B then misreads it (wrong B+/B rows;
      "the material doesn't say" for a B). A committed extraction eval
      case now pins the split rows; local PDF page 4 yields explicit
      "83 - 86% B | 63 - 66% D". Reindex an existing source from Sources
      to apply the new extractor while preserving old cited passages
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

## 10. Handoff (2026-09-25, end of the first build session)

Written for the next model picking this up. The owner will have the
original author review the result afterwards.

### 10.1 State

- Branch `main` of `RileyK05/Stacks` (public, MIT). Push is allowed once
  checks pass and nothing sensitive is included (the owner's course PDFs
  live in gitignored `runs/` and `data/`; never commit them).
- Phases A and B are built (§7). Checks at hand-off: 413 pytest passed,
  ruff clean, mypy strict clean, `npm run check` 0 errors,
  `cargo clippy` clean (last run before Phase B's frontend; re-run it).
- Version 0.2.0 (unreleased). Bump with `python -m scripts.set_version`
  and add a CHANGELOG entry when cutting a release.

### 10.2 Verify first (fixed but not yet re-tested live)

1. **Doc citations survive the editor.** TipTap's Markdown writer escapes
   "[1]" as "\[1\]". Fixed twice: `DocEditor.markdownOf()` unescapes, and
   `DocContent` unescapes on save. Check: accept a cited proposal, type in
   the doc, reload — chips still show and the Sources panel still lists
   them.
2. **No phantom versions.** Opening a doc or accepting a proposal must add
   exactly one version (accept) or none (open). `DocEditor` now only
   reports changes after real input (keydown / paste / drop / cut /
   toolbar) and compares against the editor's canonical Markdown; the
   store skips no-op saves. Check the version number after open, after
   accept, after typing.
3. **Additions insert, never rewrite.** "Add a section on exam rules" on a
   doc with text: the proposal keeps the old text byte-for-byte and adds
   the new section at the end (or after the scoped section).
4. **Pasted material is gone.** The earlier live run produced ~99 citation
   chips because MiniCPM5-2B pasted raw syllabus lines ("[1] Fraga …");
   `strip_echo` now removes those. Confirm on the owner's course.
5. **Save from chat** end to end: ask "quiz me on …" in a chat, open the
   workspace, "Save to artifacts", open it from the Artifacts tab.
6. The dev database holds test artifacts from this session (an "Untitled
   doc" whose stored Markdown has escaped citations from before fix 1).
   Delete them from the Artifacts tab before judging anything.

### 10.3 Left to build

- Phase B: source viewer (open the original PDF at the cited page),
  `.course` format v2 (chats + artifacts in the export; importer must
  accept v1 and v2), a delete/rename for artifacts from the Artifacts
  tab cards (today only on the artifact page).
- Phase C/D/E as listed in §7. Highest value next: table-aware PDF
  extraction (the grading-table misreads are the worst answer-quality
  problem seen), then concept extraction.
- Docs: `docs/AGENTS.md` structure section should list `artifacts/`,
  `api/conversations.py`, `api/artifacts.py`, `tutor/chat.py`,
  `common/model_profiles.py`, `runtime/user_models.py`; `project.md` MVP
  stories need the chat/artifact wording; README could mention artifacts.
- Packaging: rebuild the installer (`python -m scripts.build_desktop`)
  and check exports inside the installed app (PyInstaller now collects
  the docx/pptx templates; untested there).

### 10.4 How to run and check

- Backend checks: `.venv/Scripts/python -m pytest -q`, `-m ruff check .`,
  `-m mypy src`. Frontend: `cd src/frontend && npm run check`. Shell:
  `cd src/frontend/src-tauri && cargo clippy --all-targets -- -D warnings`
  (Rust lives at `%USERPROFILE%\.cargo\bin`; add it to PATH).
- Dev app: `cd src/frontend && npm run desktop` (Vite + Tauri; starts the
  backend from `.venv` against the checkout's `data/`). The Python
  backend does **not** hot-reload: restart the app after backend changes.
  After adding npm packages, Vite re-bundles and reloads the page once.
- Driving the real window: start it with
  `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333`
  (9222 is taken by another WebView2 app on the owner's machine) and use
  the DevTools protocol (`/json`, `Runtime.evaluate`,
  `Page.captureScreenshot`). `window.__TAURI_INTERNALS__.invoke('backend_info')`
  gives the backend URL and token for direct API calls. Close the app with
  the window's close (the backend then stops the model server cleanly).
- API types: after backend route/schema changes,
  `python -m scripts.dump_openapi <file>` then
  `OPENAPI_FILE=<file> npm run gen:api` (schema.d.ts is gitignored).

### 10.5 Gotchas met this session

- Many source files have CRLF line endings in the working copy; string-
  replacement scripts must normalise (the Edit tool handles it).
- Shell heredocs mangled backslashes more than once (a regex `\b` became
  a backspace byte). Write edit scripts to files, then run them.
- `structuredClone` throws on Svelte `$state` proxies: snapshot first
  (`$state.snapshot`). This silently broke the proposal view once.
- `ruff format` over whole folders reformats untouched files; format only
  the files you changed.
- The citation list must stay in the order the model numbered the
  material (`chunks_with_locators_by_ids` orders by the id list); a test
  guards it.
- Small-model behaviour seen live: MiniCPM5-2B misreads two-column PDF
  tables, adds chatty preambles (stripped for docs), forgets citations
  (attributed by overlap), and pastes material back (stripped). Measure
  prompt changes with `scripts/eval_models.py` before trusting them.

### 10.6 Continuation after the handoff

- Phase B's remaining source viewer, `.course` v2 archive, and artifact-card
  rename/delete are implemented. Format v2 includes the original source
  bytes plus chats, artifacts, all versions, and snapshots of cited
  passages. Import accepts v1, validates v2 before creating a course,
  then reindexes sources while old citations remain readable.
- PDF table extraction now detects repeated visual columns and separates
  the grading-scale cells. The committed eval case covers the two-column
  syllabus table; the owner's local PDF extracted the expected B+/B rows.
  Sources has a Reindex action for existing uploads; it snapshots cited
  chunks before replacing the search index.
- Backend tests, Ruff, mypy, frontend check/build passed. An isolated local
  browser run also verified doc autosave/versioning after reload, artifact
  rename, the original text/PDF source viewer with PDF page navigation, and
  a cited doc whose source link reopens the exact passage after an edit and
  reload. The packaged backend exported valid .docx and .pptx files from
  that isolated course, and the Windows installer built. The
  model-dependent checks in §10.2 still need the owner's model; the
  installer itself has not been installed and run.
- Next implementation work: Phase C concept extraction and study pack,
  then Phase D practice/memory and Phase E course home. The rest of §10.3
  records the original handoff and should be read as historical context.

## 11. Native Office files (planned, 2026-09-25; not started)

Owner's goal: work on a real paper in Word format, a real PowerPoint deck,
and real Excel homework (formulas) inside Stacks, together with the model.
What Phase B built is not that. It built our own formats that export to
Office:

| Type | What it is today | Gap |
|---|---|---|
| Doc | TipTap editor storing Markdown; exports .docx | Can't open a .docx; Word styles, footnotes, comments, headers, margins don't exist |
| Sheet | Grid of text cells (`rows: list[list[str]]`) | No formulas, number formats, or multiple sheets |
| Slides | Title / body / notes per slide | No layouts, images, positions, themes; can't open a .pptx |

### 11.1 Principle: the file is the artifact

- A **Word document**, **Excel workbook** or **PowerPoint deck** artifact
  *is* its .docx / .xlsx / .pptx file. Create one blank, or import one the
  student already has (their paper, the professor's homework template).
- Every version is the complete file (stored in the data folder,
  content-addressed by sha256; the DB row keeps the hash, author, note).
  Version restore, the 409 on stale saves, and proposals work as now.
- **Fidelity rule:** Stacks rewrites only what it understands and changed.
  Opening and saving without an edit must give back the same file; editing
  one paragraph, cell range or slide must leave every other part of the
  zip unchanged. This is the acceptance test for every library below.
- **Model edits** are narrow operations on the file, done in the backend,
  shown as a proposal (accept / undo), cited, and gated as today:
  - Word: replace / insert / delete paragraphs or a section, addressed by
    paragraph index or heading (python-docx edits the XML in place and
    keeps parts it doesn't know).
  - Excel: set values or formulas on a range, add a sheet, add rows
    (see 11.3 for which library writes the file).
  - PowerPoint: edit a slide's text boxes and notes, add or remove a slide
    from the deck's own layouts (python-pptx, in place).
  - The model reads a compact outline (headings + paragraphs; used ranges
    with formulas; slide texts), never raw XML. Small models get one
    section, range or slide at a time.
- **Citations:** `[n]` markers as ordinary text plus the artifact's
  ordered `sources` list, exactly as today; export appends the sources
  list. Nothing new is invented inside the Office file.
- **Open in Word / Excel / PowerPoint:** always offered. The Tauri shell
  opens a working copy with the system app and watches it; a save there
  becomes a new version ("edited in Word"). Heavy layout work happens in
  the real apps; Stacks stays useful without them.
- **Keep the current editors as lighter types.** The TipTap doc becomes
  **Notes** (fast, Markdown, citation chips); the grid and simple slides
  remain for quick model-made tables and outlines. Quiz, flashcards, code
  and chart are unchanged. Existing docs stay Notes; "Convert to Word
  document" uses the existing .docx export.

### 11.2 Candidates (researched 2026-09-25; verify before adopting)

Stacks is MIT and ships a desktop binary, so AGPL components are ruled out
unless the owner chooses to relicense Stacks. Our frontend is Svelte 5; a
React component can be mounted as an island inside a Svelte component
(adds React to the bundle; acceptable for these editors).

| Format | Candidate | License | Notes | Verdict |
|---|---|---|---|---|
| .docx | [docx-editor (EigenPal)](https://github.com/eigenpal/docx-editor) | Apache-2.0 core (React/Vue); comments, tracked changes and the programmatic editor-api are paid "Pro" | Parses OOXML directly, paged layout, claims byte-for-byte preservation of untouched content; v2.x, active | **Spike first** |
| .docx | [SuperDoc](https://github.com/superdoc-dev/superdoc) | AGPLv3 or commercial | Most complete (tracked changes, comments, Python SDK) | Excluded (AGPL) unless the owner decides otherwise |
| .docx/.xlsx/.pptx | [Oxi](https://github.com/Ryujiyasu/oxi) | MPL-2.0 core | Rust/WASM, measured Word fidelity, patches only changed XML; v0.8, tiny community | Watch; don't depend on it yet |
| .xlsx | [IronCalc](https://github.com/ironcalc/IronCalc) | MIT / Apache-2.0 | Rust engine with native xlsx reader/writer, WASM + Python bindings, React workbook UI; pre-1.0 (v0.8) | **Spike** (fits Tauri/Rust and the Python backend) |
| .xlsx | [FortuneSheet](https://github.com/ruilisi/fortune-sheet) + [FortuneExcel](https://github.com/corbe30/fortuneexcel) | MIT | Mature Excel-like React UI, formulas via a formula-parser fork; xlsx converted in and out (lossy) | **Spike** as the UI fallback |
| .xlsx | [Univer](https://github.com/dream-num/univer) | Apache-2.0 core | xlsx import/export is in paid Pro packages and needs a conversion server | Excluded |
| .xlsx (backend) | openpyxl (already a dependency) | MIT | Drops charts and images when an existing file is saved | Only for files Stacks created; never to save an imported workbook |
| .pptx | [pptx-viewer](https://github.com/ChristopherVR/pptx-viewer) | Apache-2.0 | Parse, render, edit (text, shapes, images, notes, layouts), save; ships a Svelte 5 package; small community | **Spike** |
| .pptx | [PPTist](https://github.com/pipipi-pikachu/PPTist) | AGPLv3 | Full editor, ~70-80% import fidelity | Excluded (AGPL, lossy) |
| .docx/.pptx (backend) | python-docx, python-pptx (already dependencies) | MIT | Edit XML in place, keep unknown parts | Model edits |

### 11.3 Plan

**N0 — spike and decide (no product code).** A throwaway page per format
in the dev app; run each candidate against a fidelity corpus: the owner's
real files (a paper, an accounting homework workbook, a class deck) kept
in gitignored `runs/fidelity/`, plus small synthetic files committed under
`data/eval/office/` (styles, footnotes, tables, images, headers; formulas,
number formats, charts, several sheets; layouts, images, notes). Measure
per candidate: no-edit round trip (zip parts identical), one-edit round
trip (only the touched part changes), opens in Word/LibreOffice without
repair, bundle size, first-open time on the 8 GB machine. For Excel also
decide who writes the file for model edits: IronCalc (Python bindings) or
a small cell-level XML patcher (keeps charts; IronCalc then only
evaluates formulas for display). Record results and choices in
`docs/notes.md`.

**N1 — storage and API.** Artifact kinds `word`, `excel`, `powerpoint`
with file-backed versions (migration 006), import/upload, download, the
fidelity round-trip tests in pytest, and `.course` format v3 carrying the
version files (importer keeps v1 and v2).

**N2 — Excel first** (clearest gap, best libraries): in-app workbook
editor with formulas; model edits on ranges ("fill column D with the
depreciation formula", "check my totals"), recalculated before the
proposal is shown; citations for anything taken from sources.

**N3 — Word:** the in-app document editor; model edits by paragraph or
section, and additions never rewrite the student's text (the Phase B rule
carries over).

**N4 — PowerPoint:** in-app deck editor/preview; model edits per slide
using the deck's own layouts; the presenter from Phase B.

**N5 — Open in Office + watching**, "Convert Notes to Word document",
save-from-chat into the new kinds, installer size check.

Each step ships only with its fidelity tests green in CI.

### 11.4 Risks and owner questions

- Third-party maturity: IronCalc and pptx-viewer are young. The file stays
  the truth and "Open in Office" always works, so a weak editor degrades
  to preview + model edits rather than data loss.
- Apache-2.0 components need their LICENSE/NOTICE files shipped; add a
  third-party notices screen in Settings → About.
- A 2B model editing a real paper: keep operations narrow and
  section-scoped; the bigger-model button is the escape hatch.
- **Owner decisions needed before N1:** (1) AGPL stays ruled out
  (recommended: yes)? (2) Keep Notes / simple grid / simple slides beside
  the native types (recommended: yes)? (3) Paid tiers such as
  docx-editor's comments and tracked changes: not for now?

Also stale: `docs/AGENTS.md` still points at `docs/decisions/` and
`plan-local-first.md`, which were removed; fix those references.
