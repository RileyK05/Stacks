# Handoff: Canvas-style workspace + dark mode (frontend)

Written: 2026-09-22. For the next agent picking this up. Read this fully before editing.

## Progress log

- **2026-09-22 (update 1):** Tabbed canvas is DONE. `WorkspaceCanvas`
  (in `workspace.svelte.ts`) accumulates tabs across turns; `WorkspacePanel`
  renders a scrollable tab bar (title + origin + close); new answers append
  tabs without evicting old ones; per-turn button and panel close updated on
  the course page. Verified: `npm run check` clean, `npm run build` ok,
  backend pytest 348 passed (before this change; frontend-only). Dark-mode
  `dark:` sweep confirmed complete across components and route pages.
- **2026-09-22 (update 2):** HTML visualization workspace type is DONE
  (user chose sanitized inline HTML over sandboxed iframe).
  `WorkspaceHtml {type:"html", title?, html, sources}` in
  `src/backend/tutor/workspace.py` (same decision-009 citation gate),
  prompt example added in `configs/prompts.toml` (version bumped 3→4),
  4 new gate tests in `tests/test_tutor_workspace.py`, API types
  regenerated. Frontend: `HtmlSession`, `WorkspaceHtmlView.svelte`
  (DOMPurify-sanitized, SVG/CSS charts work, scripts never run), panel
  branch added. Verified: workspace tests 14 passed, `npm run check`
  clean, `npm run build` ok, sanitizeHtml smoke passed (table/SVG pass,
  script/onerror stripped).
- **Remaining:** live answer-eval re-run after the prompt change (v3→v4;
  costs provider calls — not done), visual dark-mode QA with the dev
  stack up, end-to-end browser sanity (quiz grades, doc edits, html tab).

## The user's vision (their words, paraphrased)

ChatGPT-style split canvas on the course Ask page:
- **Left pane = the chat as a whole** — a place to talk to the tutor, nothing else.
- **Right pane = a workspace where the assistant *creates* things** — quizzes with
  multiple choice, editable documents, HTML visualizations. Multiple generated
  items coexist as **tabs** (see the user's reference screenshot: a tab bar over
  the right pane with several open artifacts, one active at a time).
- Plus dark/light mode, already built.

## Current state (all committed in `3cfbe45 "Stuff and stuff"` unless noted)

The workspace is **backend-driven** — a parallel effort replaced the earlier
frontend-only ` ```artifact ` JSON convention (my `artifacts.ts` no longer
exists; don't resurrect it). What exists now:

- `POST /courses/{course_id}/ask` returns `AnswerView` **plus `workspace`**:
  validated `WorkspaceQuiz` / `WorkspaceDocument` items, generated and
  citation-gated **server-side** (`src/backend/tutor/workspace.py`, gated per
  `docs/decisions/009_three_zone_assistance_policy.md`; the chat `text` comes
  back with workspace blocks already lifted out).
- Frontend wiring: `src/frontend/src/lib/stores/workspace.svelte.ts`
  (`QuizSession` classes hold student progress; `missedFollowUp()` builds a
  chat follow-up from missed questions), `src/frontend/src/lib/components/
  WorkspacePanel.svelte`, `SourceChips.svelte`, and the split grid in
  `src/frontend/src/routes/(app)/courses/[id]/+page.svelte` (~line 399).
  Panel shows **one turn's** workspace items, selected via `workspaceTurn`.
- Rich rendering: `src/frontend/src/lib/utils/render.ts` +
  `RichText.svelte` — markdown → KaTeX (`$..$`, `$$..$$`) → DOMPurify-sanitized
  HTML. No scripts ever execute.
- Dark mode: class-based Tailwind variant in `app.css`
  (`@custom-variant dark`), store in `src/lib/stores/theme.svelte.ts`
  (localStorage `theme`, OS-preference default), toggle in the app sidebar.
  The `dark:` sweep across components and all route pages is **done** except
  the three Milestone placeholder pages (probe/progress/artifacts — trivial
  `EmptyState` stubs).

Last verified: `npm run check` (svelte-check) **0 errors / 0 warnings**.

## Dirty working tree — DO NOT REVERT (not ours)

`configs/tiers.toml`, `src/backend/common/config.py`,
`src/backend/common/provider.py`, `tests/conftest.py`, `tests/test_spend.py`
are modified but uncommitted, from backend work unrelated to this handoff.
Leave them alone; run backend tests rather than assuming they pass.

## Remaining work, in order

1. **`npm run build`** in `src/frontend` — confirm the production build passes
   (only `check` has been run since the workspace refactor landed). Also run
   `pytest` from the repo root (`.venv`) to see where the backend stands.
2. ~~Tabbed workspace~~ — **done** (see progress log). If revisiting: quiz
   progress survives tab switches because `QuizSession` instances are held by
   the page's turns and referenced (not recreated) by tabs; `DocumentSession`
   drafts likewise.
3. **HTML visualization item type** (user explicitly wants "HTML processing"
   in the canvas — their example was a chart). Two sub-decisions to put to the
   user before building:
   - Sanitized inline HTML (consistent with `RichText`; no JS — charts must be
     SVG/CSS) vs sandboxed `<iframe sandbox="allow-scripts">` (real JS charts,
     heavier, weaker security story).
   - Requires a backend `WorkspaceHtml`/similar schema addition → run
     `npm run gen:api` (backend must be running) and extend
     `tutor/workspace.py` + its prompts. **The answer-eval harness
     (`src/backend/evals/answer.py`, `data/eval/answer/cases.json`) scores
     prompt changes** — re-run evals after touching prompts and report the
     delta; don't silently change prompts.
4. **Visual QA of dark mode** with the dev stack up (`npm run dev` in
   `src/frontend`, backend on :8000): toggle flips chrome + rendered prose
   (`dark:prose-invert`), quiz grading colors, workspace panel, auth pages.
   Fix contrast breaks as found.
5. **End-to-end sanity**: ask a question that yields a quiz (if the backend
   prompt generates one), verify tab opens, quiz grades, `missedFollowUp()`
   posts back to chat; edit a document, confirm local-only edits.

## Conventions & gotchas

- **Never write test scripts via bash heredocs/`-e` strings containing
  backslashes** — the shell layer eats `\f` (form feed), `\a` (bell), `\i`,
  `\,`, etc. Write `.mts` files with the Write tool; build backslashes via
  `String.fromCharCode(92)` if needed. This cost real debugging time.
- No frontend test framework exists and none should be added without asking.
  Verification pattern: `npm run check`, `npm run build`, throwaway `npx tsx
  scripts/*.mts` smokes (delete after), manual dev-server pass. jsdom was
  previously installed with `npm install --no-save jsdom` for DOMPurify smokes
  (needs `globalThis.window/document` from a `<!doctype html>` JSDOM; quirks
  mode makes KaTeX warn) and pruned with `npm prune` — same trick works again.
- `src/frontend/src/lib/api/schema.d.ts` is **gitignored and generated**: after
  any backend schema change, regenerate with `npm run gen:api` (backend
  running). Never hand-edit it.
- Frontend README (`src/frontend/README.md`) documents the answer-rendering
  pipeline and theme rules ("new UI must carry `dark:` companions") — keep it
  in sync if you change either.
- Svelte 5 runes throughout (`$state`/`$derived`/`$props`), raw Tailwind
  classes inline, no icon library (inline SVG), no class-merge library.
- Project guidance lives in `docs/AGENTS.md` (moved there in 3cfbe45).
- Backend answers are non-streaming single JSON; no SSE anywhere.

## What NOT to do

- Don't reintroduce a frontend-only artifact JSON convention — workspace items
  are server-validated now (citation gate is deliberate, decision 009).
- Don't touch the Milestone 3/4/5 placeholder pages (probe/progress/artifacts
  routes) — separate milestones.
- Don't commit; the user commits themselves (history shows they batch-commit
  agent work, e.g. "Stuff and stuff").
