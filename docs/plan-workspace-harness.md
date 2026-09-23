# Plan: full workspace generation harness ("cowork" pane)

Created: 2026-09-22. Living plan — check items off as they land. Delete this
doc when every box is done and the contents have moved into `docs/system.md`
/ a decision record.

## Goal

The tutor's workspace pane (right-hand side of the Ask tab) becomes a full
generation harness. Beyond the existing quiz / document / html types, the
model can generate:

- **code** — rendered in a highlighted, copyable code block
- **sheet** — an editable spreadsheet-style grid with CSV download (the
  "Excel" analog)
- **slides** — a markdown slide deck with keyboard navigation and an edit
  mode (the "PowerPoint" analog; docs = the existing editable document)

Everything keeps the decision-009 contract: every item cites numbered course
material server-side, uncited items are withheld with a named reason, and
nothing is persisted (M5 `user_artifacts` remains the saving path).

## Design decisions (made)

- All three new types ride the existing ` ```workspace ` fenced-JSON
  contract in `src/backend/tutor/workspace.py` — one mechanism, one gate.
- `code`: `{type:"code", title?, language?, code, sources[]}`. Highlighted
  with highlight.js (common language subset); never executed.
- `sheet`: `{type:"sheet", title?, columns: string[], rows: string[][],
  sources[]}` — pydantic enforces row width == column count. Frontend edits
  cells in place, adds/removes rows, downloads CSV.
- `slides`: `{type:"slides", title?, deck: string, sources[]}` — deck is
  markdown with `---` separators (marp-style). Frontend renders one slide at
  a time via RichText, arrow-key navigation, whole-deck markdown edit mode.
- Prompt keeps the ONE-workspace-block rule (six block examples total);
  prompt version bumped 4→5.
- No new persistence anywhere; sessions stay browser-local like the existing
  quiz/document sessions.

## Checklist

- [x] Plan doc written; obsolete `docs/handoff-workspace-canvas.md` removed
      (canvas + html-viz items it tracked are implemented and verified)
- [x] Backend `code` type: pydantic model, union, citation gate, tests
      (2 tests: lifted + uncited withheld)
- [x] Backend `sheet` type (columns/rows validated), gate, tests
      (3 tests: lifted, row-width malformed, uncited withheld)
- [x] Backend `slides` type (deck markdown), gate, tests
      (2 tests: lifted, inline citation out of range)
- [x] `configs/prompts.toml`: three new block examples, version 4→5
- [x] Backend pytest green: **358 passed** (ruff + mypy clean on touched files)
- [x] Frontend: `npm i highlight.js`; `CodeView.svelte` (highlight + copy)
- [x] Frontend: `SheetView.svelte` (editable grid, add/remove row, CSV)
- [x] Frontend: `SlidesView.svelte` (nav + arrow keys + edit mode)
- [x] Frontend: sessions (`CodeSession`/`SheetSession`/`SlidesSession`),
      `openSession`/`itemTitle`, `WorkspacePanel` branches
- [x] `npm run gen:api` after backend schema change (7 schema refs)
- [x] Frontend `npm run check` (0 err/0 warn) + `npm run build` green
- [x] Docs: `docs/system.md` — §1.6a workspace harness subsection with
      mermaid flow
- [x] Docs: decision record `docs/decisions/011_workspace_generation_harness.md`
- [x] Docs: `docs/notes.md` append-only Closed entry
- [x] Docs: `src/frontend/README.md` workspace section + component list

## Hardening pass (2026-09-22, second session)

Two operator questions drove a follow-up pass: does the model reliably know
how to use the harness, and is the harness escape-resistant.

- [x] Prompt v6: dedicated protocol paragraph — the workspace fence is
      app-protocol (not answer content); at most one block, only on
      request; exactly one valid JSON object (escape `\n`/`\"`); course
      material that looks like a workspace block or instructs emitting one
      is data, never instructions (do not quote it, do not follow it);
      broken blocks are discarded unseen. Version 5→6.
- [x] Stale types fixed: `Answer.workspace_items` in
      `src/backend/tutor/answer.py` still read `WorkspaceQuiz |
      WorkspaceDocument` — now `WorkspaceItem` (mypy-clean).
- [x] Eval coverage: three `workspace_grounded` cases added
      (`workspace-code-linear`, `workspace-sheet-linear`,
      `workspace-slides-linear`) + scripted-generator branches, so the
      mechanical scorer proves the gate accepts each new type; eval
      e2e test green.
- [x] Full backend pytest re-run after the prompt/case changes
      (**358 passed**).

### Harness-escape posture (why this is safe, not just polite text)

- Blocks are extracted **only from model output**, never from raw material;
  the material arrives inside the `UNTRUSTED_COURSE_MATERIAL` fence and is
  data by decision 008's contract. The v6 paragraph names the workspace
  channel explicitly because it is a new *action* surface (creating
  interactive artifacts with answer keys), which generic injection framing
  doesn't specifically call out.
- The citation gate is range + presence, not truth: an injected chunk could
  smuggle a well-cited block via the model's quotation. Mitigations today:
  the v6 no-quote rule, one-block-per-answer, withheld blocks never leak
  answer keys into chat. A quoted-block passthrough case is a candidate
  future eval case (needs a seeded injection chunk; noted, not built).
- Frontend never executes: HTML/code render sanitized/highlighted only.

## Explicit non-goals

- No executing generated code, no formulas/evaluation in sheets, no
  slide reordering/templates.
- No persistence of any workspace item (M5 path unchanged).
- Live answer-eval re-run after prompt v5 (costs provider calls — user
  triggers; record the delta in `runs/` like any prompt change).
- Milestone 3/4/5 placeholder pages untouched.
