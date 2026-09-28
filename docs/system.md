# System design

Updated 2026-09-28. This document describes the current local-first desktop
system. Hosted accounts, Postgres, enrollment, tiers, and shared courses were
retired and remain only in git history.

## 1. Product shape

Stacks is one desktop application for one user and one local data directory.
It has three user-facing surfaces:

1. **Companion window**: the primary 420 px Windows sidebar. It docks to the
   right work area, can stay above other apps, collapses to a 56 px tab, and
   accepts context copied from any application.
2. **Library window**: the full course interface for sources, saved chats,
   artifacts, models, data controls, and Office setup. It starts hidden and is
   opened from the companion.
3. **Office task pane**: an optional Word, Excel, and PowerPoint bridge. Office
   reads and writes its own documents through Office.js; Stacks supplies cited
   answers.

The companion and library are SvelteKit routes in two Tauri WebView2 windows.
They share one Python backend child process and one SQLite database.

```mermaid
flowchart LR
    APP["Word / browser / PDF"] -->|copy context| COMP["Companion window"]
    COMP -->|open| LIB["Full library window"]
    COMP --> API["FastAPI /api"]
    LIB --> API
    OFFICE["Office task pane"] --> BRIDGE["HTTPS /office bridge"]
    BRIDGE --> TUTOR["Grounded assistant"]
    API --> TUTOR
    API --> DB[("SQLite + source files")]
    TUTOR --> RET["Retrieval + reranker"]
    RET --> DB
    TUTOR --> MODEL["Local or selected cloud model"]
```

## 2. Process topology

The Tauri shell starts first. It creates `companion` and a hidden `main`
window, then launches `src.backend.serve`:

- Development uses the checkout virtualenv and `data/`.
- A packaged build uses the PyInstaller backend under Tauri resources and the
  per-user app-data directory.
- The backend binds a free loopback port and prints `STACKS_PORT=<port>`.
- The shell waits for `/api/health`, then gives the URL and a random per-launch
  token to its own webviews through `backend_info`.
- API requests carry the token in `X-App-Token`.
- Closing backend stdin requests a clean shutdown. The shell kills the child if
  it does not stop within the shutdown deadline.
- The single-instance plugin brings the existing companion forward instead of
  starting a second backend on the same database.

The companion owns the explicit Quit action. Closing the library hides that
window. There is currently no tray process.

## 3. Data and storage

SQLite is the source of truth. Connections enable WAL, foreign keys, and FTS5.
Raw SQL lives in `src/backend/common/queries/`; append-only migrations live in
`src/backend/common/migrations/`.

The data directory contains:

- `course_assistant.db`: courses, source metadata, chunks, locators, retrieval
  traces, settings, chats, artifacts, versions, and usage records.
- `raw/`: original course files under generated names.
- model/runtime downloads managed by the runtime subsystem.
- Office add-in certificate and manifest state after the user connects Office.

Original sources are retained whole. Derived text, chunks, embeddings, table of
contents entries, and course knowledge can be rebuilt. Deleting a course moves
it to a 30-day trash; a bounded course-memory keepsake survives purge.

Course export creates a `.course` archive containing source files and portable
history. Imports validate the archive before making it live.

## 4. Ingestion

Uploads stream to a temporary file under a byte ceiling, then become a stored
source and a queued ingestion run. The pipeline is ordered and versioned:

```text
extract -> OCR when needed -> locators -> chunks -> embeddings
        -> table of contents -> course-knowledge extraction
```

PDF, Markdown, text, and Office package readers preserve natural locators such
as page, slide, heading, and cell range. Chunks are token bounded and can point
to several locators. The ingestion worker records stage state and errors in the
run ledger so failures are inspectable.

ONNX Runtime runs embeddings and reranking in process. The reference Torch
stack is a development-only parity check and is excluded from the desktop
bundle.

## 5. Retrieval and grounding

Retrieval uses four candidate seams:

1. SQLite FTS5 keyword matches.
2. Course table-of-contents routing.
3. Concept dependency expansion.
4. Dense embedding similarity.

The funnel normalizes and combines candidates, then a cross-encoder reranker
chooses the passages sent to generation. Retrieval traces record the candidate
path and selected chunks.

Substantive answers must cite the numbered material. Citation validation has
the last word: unsupported structured output is withheld, and empty retrieval
is refused. The assistance policy steers requests for graded work toward
learning help.

## 6. Tutor, conversations, and companion

The tutor frames a request, retrieves allowed course material, builds a fenced
prompt, calls the selected provider, validates citations, and returns text plus
citation metadata.

Saved conversations retain raw turns and a rolling summary for limited model
contexts. Workspace blocks can produce validated quizzes, documents, HTML,
code, sheets, and slide decks; the frontend renders them but never executes
model-authored code.

`POST /api/companion/assist` reuses the Office assistant request and response
contract. The companion therefore shares the same source-grounding and graded
work rules as the Office pane. Its visible conversation is currently
session-local.

## 7. Artifacts

Course artifacts are typed JSON objects: notes, schedules, study decks,
quizzes, flashcards, code, and charts. Every save creates a version and checks
that cited chunk IDs belong to the course. Model edits arrive as proposals;
accepting one becomes a normal versioned save.

Exports create Markdown, CSV, text, Word, Excel, PowerPoint, or chart HTML as
appropriate. Exported content carries a Sources section. Model-authored chart
HTML is placed in a sandboxed iframe with a restrictive content security policy
before it leaves the app.

## 8. Models and privacy

All generation goes through `src/backend/common/provider.py`. Task classes map
to a provider choice stored in local settings:

- bundled llama.cpp runtime and a downloaded GGUF model;
- OpenRouter;
- OpenAI;
- another OpenAI-compatible endpoint.

API keys live in the OS keychain. A cloud provider is used only after the user
selects it and sees the disclosure. Usage is written to a local ledger and can
be limited by a monthly token budget.

Uploaded material is untrusted data. It is fenced by
`prompt_registry.grounded_prompt` and cannot supply system instructions.

## 9. Office bridge

Connecting Office performs per-user setup:

1. Create a localhost certificate from a throwaway local CA.
2. Ask Windows to trust the CA.
3. Render and register the add-in manifest for the fixed Office HTTPS port.
4. Start the pane host alongside the desktop backend.

The pane calls `/office/courses`, `/office/assist`, and `/office/read` on the
same HTTPS origin. Host adapters use Word, Excel, or PowerPoint APIs with the
Office Common API as fallback. Document mutations always go through Office.js;
the backend never rewrites a `.docx`, `.xlsx`, or `.pptx`.

## 10. Frontend and desktop security

- The static SvelteKit build is embedded in Tauri.
- The library and companion have separate Tauri capability files. Only the
  library receives file dialogs and external URL/file reveal permissions.
- External links open through the OS browser and are scoped to Tauri's default
  HTTP, HTTPS, mail, and telephone URL set.
- Model Markdown and workspace HTML are sanitized with DOMPurify before render.
- The desktop API binds to loopback and expects the per-launch token in packaged
  operation.
- The Tauri content security policy allows only embedded assets, IPC, and the
  loopback backend.

## 11. Build and release

`scripts/build_desktop.py` is the supported installer path:

1. PyInstaller freezes the backend, configs, SQL, encoders, and Office pane.
2. Tauri builds the static frontend and Rust shell with the locked Cargo graph.
3. NSIS creates a current-user Windows installer.
4. The script fails if the build produces no installer.

`scripts/set_version.py` updates the backend, Python package, frontend package
and lockfile, Rust package and Cargo.lock. `tests/test_version.py` verifies the
manifests agree and the changelog has the version.

CI runs Python tests, Ruff, mypy, generated API types, Svelte diagnostics, the
Office.js type and logic checks, the production frontend build, and Rust clippy.
A version tag triggers the same gate before an installer and draft release are
created.

## 12. Planned subsystem

The student model remains planned. Its intended records are diagnostic items,
attempts, confidence, concept-linked errors, mastery states, and transparent
study recommendations. It may not claim mastery from passive reading or chat
activity. Implementation waits for a versioned evaluation path and real course
use.
