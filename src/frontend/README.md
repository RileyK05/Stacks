# Frontend

SvelteKit + TypeScript SPA (Svelte 5 runes, Tailwind CSS v4). Talks to the
backend **only** over its HTTP API. CSR-only (`ssr = false`,
`adapter-static`) — auth is a JWT in `localStorage`, so there is no
SSR/token complexity; the build output is a plain static bundle.

## Setup

```bash
npm install
cp .env.example .env   # see "Configuration" below
```

## Commands

```bash
npm run dev       # dev server (default http://localhost:5173)
npm run check     # svelte-check type/diagnostics — must pass
npm run build     # static SPA into build/ (fallback 200.html)
npm run preview   # serve the built bundle locally
npm run gen:api    # regenerate src/lib/api/schema.d.ts from the backend
```

## Configuration

- `.env` → `PUBLIC_API_BASE`. Empty (default) = same-origin: the Vite dev
  proxy (dev) or a reverse proxy (prod) forwards API prefixes to the
  backend. Set an absolute URL only when serving the SPA without a
  proxying web server (requires CORS on the backend, which is currently
  not configured).
- `API_PROXY_TARGET` (shell env, not `.env`) overrides the dev proxy target
  (`http://localhost:8000` by default).

## API types: generated, never hand-written

`src/lib/api/schema.d.ts` is generated from the backend's OpenAPI schema
and committed. Regenerate after any backend route/schema change:

```bash
# with the backend running (uvicorn src.backend.main:app --port 8000)
npm run gen:api
```

The backend is the single source of truth for API shapes. Use the types via
`paths` from `$lib/api/schema`, call endpoints via the typed client in
`$lib/api/client` (`api.GET('/courses')`, `api.POST(...)`), and surface
failures as `ApiError` (`$lib/api/errors`) — every thrown error from the
client is an `ApiError`, including network failures. The client injects the
Bearer token and bounces to `/login` on a rejected stored token.

## Structure

```
src/lib/api/         generated schema + typed client + ApiError
src/lib/auth/token.ts   localStorage JWT seam (the only token touchpoint)
src/lib/stores/      runes stores: auth, theme, toast, confirm, debug, workspace
src/lib/components/  Button, Card, TextInput, Select, Spinner, Skeleton, ErrorBanner,
                     EmptyState, RichText (markdown + LaTeX + sanitized HTML for
                     model output; pipeline in $lib/utils/render.ts), Quiz +
                     EditableDocument + WorkspaceHtmlView + CodeView +
                     SheetView + SlidesView + SourceChips + WorkspacePanel
                     (the tabbed chat-side workspace, see below), Toaster,
                     ConfirmHost
src/routes/
  (auth)/            login, register, password-reset (chromeless layout)
  (app)/             guarded shell: my courses, discover, archives, account
    courses/[id]/    course overview: tutor chat + workspace pane with
                     expandable cited sources, owner: dropzone upload + live indexing
                     state, join code, members; milestone stub links
      probe/         Milestone 3 placeholder
      progress/      Milestone 4 placeholder
      artifacts/     Milestone 5 placeholder
```

Global UI feedback: `toast()` (`$lib/stores/toast.svelte`) for success/error
snackbars, `confirmDialog()` (`$lib/stores/confirm.svelte`) for destructive
action prompts — both mounted once in the root layout.

## Theme

Dark/light mode is class-based: the `dark` class on `<html>` (Tailwind v4
custom variant in `app.css`). `src/lib/stores/theme.svelte.ts` holds the
state, persists the choice to localStorage (`theme`), and defaults to the OS
preference. The toggle lives in the app sidebar. New UI must carry `dark:`
companions for hardcoded light colors. `app.html` carries a tiny pre-paint
script mirroring the store so dark-mode users never see a light flash.

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
kinds, plus auth/route state) is hidden from the UI on purpose. Toggle it
with **Ctrl+Shift+.** (period); the setting persists in localStorage
(`debug-panel`) and the log clears when the panel is disabled. There is no
menu entry for it.

## Deployment

`npm run build` emits `build/` — a static SPA. Serve it from any static
server that proxies `/auth`, `/courses`, `/course-archives`, and
`/course-memories` to the uvicorn backend (same-origin keeps CORS a
non-issue). `200.html` is the SPA fallback for client-side routes.
`/courses/<id>` is both an API path and a page, so the proxy must send
browser navigations (`Accept: text/html`) to the SPA, not the backend —
`vite.config.ts` does exactly this in dev.

Backend docs live in the repo's `docs/` (`AGENTS.md`, `project.md`,
`system.md`, `decisions/`, `notes.md`).
