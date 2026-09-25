# Frontend

The Stacks desktop app: a SvelteKit + TypeScript SPA (Svelte 5 runes,
Tailwind CSS v4) inside a Tauri v2 shell (`src-tauri/`, Rust). The SPA
talks to the backend **only** over its HTTP API. CSR-only (`ssr = false`,
`adapter-static`), so the build is a plain static bundle that Tauri ships
inside the app.

## How the pieces connect

The shell starts the Python backend (`src/backend/serve.py`) as a child
process with a per-launch token, learns the port it bound, and waits for
`/api/health`. The root layout calls `connectBackend()`
(`src/lib/api/backend.ts`), which asks the shell for the address and token
(`backend_info`); every request carries the token (`X-App-Token`). Until
then `app.html` shows a start-up splash; if the backend never answers, the
root layout shows why. Quitting the app closes the backend's stdin, which
shuts it down.

## Setup

Needs Node.js 22+, a Rust toolchain (rustup; on Windows also the MSVC
build tools), and the repo's Python virtualenv (`.venv`) with the backend
installed.

```bash
npm install
```

## Commands

```bash
npm run desktop   # the app in dev: Vite + tauri dev, starts the backend from .venv
npm run dev       # SPA in a browser only (run `uvicorn src.backend.main:app` beside it)
npm run check     # svelte-check type/diagnostics — must pass
npm run build     # static SPA into build/
npm run gen:api   # regenerate src/lib/api/schema.d.ts from the backend
```

The installer is built from the repo root with
`python -m scripts.build_desktop` (backend via PyInstaller, then
`tauri build`). In `src-tauri/`, `cargo clippy` must be clean.

In the browser-only setup the Vite dev server proxies `/api` to
`http://localhost:8000` (`API_PROXY_TARGET` overrides it) and no token is
needed. The dev app (`npm run desktop`) uses the checkout's `data/`
folder; an installed app uses the per-user app-data folder.

## API types: generated, never hand-written

`src/lib/api/schema.d.ts` is generated from the backend's OpenAPI schema
(and gitignored). Regenerate after any backend route/schema change:

```bash
# with the backend running (uvicorn src.backend.main:app --port 8000)
npm run gen:api
# or without one: python -m scripts.dump_openapi <file>, then
# OPENAPI_FILE=<file> npm run gen:api
```

The backend is the single source of truth for API shapes. Use the types via
`paths` from `$lib/api/schema`, call endpoints via the typed client in
`$lib/api/client` (`api.GET('/courses')`, `api.POST(...)`), and surface
failures as `ApiError` (`$lib/api/errors`) — every thrown error from the
client is an `ApiError`, including network failures.

## Structure

```
src-tauri/           the desktop shell (Rust): window, backend process, plugins
src/lib/api/         backend connection, generated schema, typed client, ApiError
src/lib/stores/      runes stores: theme, toast, confirm, debug, workspace
src/lib/components/  Button, Card, TextInput, Select, Spinner, Skeleton, ErrorBanner,
                     EmptyState, Icon, Badge, Monogram, PageHeader, RichText (markdown + LaTeX + sanitized HTML for
                     model output; pipeline in $lib/utils/render.ts), Quiz +
                     EditableDocument + WorkspaceHtmlView + CodeView +
                     SheetView + SlidesView + SourceChips + WorkspacePanel,
                     LocalModelCard, Toaster, ConfirmHost
src/routes/
  (app)/             the app shell: my courses, trash, settings
    courses/[id]/    a course: tutor chat + workspace pane with cited
                     sources, uploads with live indexing state, export
```

Global UI feedback: `toast()` (`$lib/stores/toast.svelte`) for success/error
snackbars, `confirmDialog()` (`$lib/stores/confirm.svelte`) for destructive
action prompts — both mounted once in the root layout. Links to other
sites open in the user's browser, never inside the app window.

## Theme

Dark/light mode is class-based: the `dark` class on `<html>` (Tailwind v4
custom variant in `app.css`). `src/lib/stores/theme.svelte.ts` holds the
state, persists the choice to localStorage (`theme`), and defaults to the OS
preference. The toggle lives in the app sidebar. `app.html` carries a tiny
pre-paint script mirroring the store so dark-mode users never see a light
flash.

Colors are **semantic tokens** defined once in `app.css` (`:root` and
`.dark`) and exposed as Tailwind utilities: `bg-bg`, `bg-surface`,
`bg-surface-2/3`, `border-line`, `border-line-strong`, `text-fg`,
`text-fg-soft`, `text-muted`, `text-subtle`, `bg-accent`, `text-accent-text`,
`bg-accent-soft`, `text-on-accent`, and `success|warning|danger|info` with
`-soft`/`-text` variants. Use these instead of raw palette colors (`slate-*`,
`indigo-*`) so new UI needs no `dark:` companions. Fonts ship with the app
(Fontsource packages, imported in the root layout): Inter (UI), Fraunces
(`font-display`, headings), JetBrains Mono (`font-mono`). Icons come
from `Icon.svelte` (inlined Lucide paths; add new ones there), and shared
pieces live in `PageHeader`, `Badge`, `Monogram` (per-course color tile), and
`$lib/utils/labels.ts` (human labels for backend enums).

## Tutor answer rendering & the workspace

Answers render through `RichText` (`$lib/utils/render.ts`): markdown → KaTeX
(`$...$` / `$$...$$`) → DOMPurify-sanitized HTML. Scripts never execute.

The Ask tab is a chat (left) plus a **workspace** pane (right, sticky;
stacked below the chat on narrow screens) that opens when an answer carries
a quiz or an editable study document. The contract is owned by the
**backend**: the tutor prompt (`configs/prompts.toml`) teaches the model to
emit fenced ` ```workspace ` JSON blocks, and `src/backend/tutor/workspace.py`
lifts them out of the answer and applies the decision-009 citation gate
(every quiz question / document must cite provided material). The `/ask`
response carries the chat body as `text`, validated items as `workspace`
(typed in the generated schema), and a reason for each withheld block as
`withheld` — shown inline in the chat, never silently dropped.

The frontend only renders: `$lib/stores/workspace.svelte.ts` wraps each item
in a session (`QuizSession` holds answers/grading, `DocumentSession`/
`SheetSession`/`SlidesSession` hold editable drafts; html and code items
carry no state) and `WorkspaceCanvas` keeps them as
tabs that accumulate across turns until closed. `Quiz.svelte`
grades locally and offers "Ask about what I missed" (pre-fills the chat);
`EditableDocument.svelte` has Preview/Edit, Revert, and Download .md;
`WorkspaceHtmlView.svelte` renders model-authored HTML (tables, SVG charts)
through the same DOMPurify config — scripts never execute;
`CodeView.svelte` highlights with highlight.js (common languages) and
copies, never runs; `SheetView.svelte` is an editable grid with
add/remove row and Download .csv; `SlidesView.svelte` renders a
`---`-separated markdown deck one slide at a time with arrow-key
navigation plus a whole-deck source edit mode.
`SourceChips` maps cited `[n]` to the answer's citation list. Nothing in the
workspace is persisted — saving to `user_artifacts` is the Milestone 5 path
(decision 011 documents the six-type contract).

## Debug panel

An operator-only debug drawer (API request log with timings/status/error
kinds, plus backend/route state) is hidden from the UI on purpose. Toggle it
with **Ctrl+Shift+.** (period); the setting persists in localStorage
(`debug-panel`) and the log clears when the panel is disabled. There is no
menu entry for it.

Backend docs live in the repo's `docs/` (`AGENTS.md`, `project.md`,
`system.md`, `decisions/`, `notes.md`).
