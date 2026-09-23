# 011 — Workspace generation harness (the "cowork" pane)

Date: 2026-09-22
Status: Ratified (operator request; supersedes the ad-hoc workspace growth)
Related: decision 009 (the citation gate every item passes), decision 010
(answer eval harness scores the prompt that teaches the blocks)

## Context

The tutor answer surface started as chat-only text. It grew a workspace
pane beside the chat (quiz, editable document, rendered HTML), then a
tabbed canvas so items accumulate across turns. The operator's ask: make
the pane a full generation harness — "editable powerpoints, excel, docs,
code rendering… basically a full harness of generation, like a cowork."

The constraint that must not bend: every generated item is evidence-linked
(decision 009's hard gate, golden rules 1–2). Richer generation must not
become a path for uncited or ungrounded content, and it must not blur the
M5 line: workspace items are **ephemeral views**, never persisted learner
artifacts.

## Decision

Six workspace item types ride one mechanism — the fenced ` ```workspace `
JSON block the tutor emits, extracted and gated in
`src/backend/tutor/workspace.py`:

| Type | Shape | Frontend view |
|---|---|---|
| `quiz` | questions with options/answer/explanations | interactive MCQ, local grading, "ask about what I missed" |
| `document` | markdown body | editable Preview/Edit, Revert, Download .md |
| `html` | raw HTML string | DOMPurify-sanitized inline render (SVG/CSS charts; scripts never execute) |
| `code` | `language?` + code string | highlight.js rendering, Copy (never executed) |
| `sheet` | `columns` + `rows` (pydantic enforces row width) | editable grid, add/remove rows, Download .csv |
| `slides` | markdown deck, `---`-separated | slide viewer with arrow-key nav, whole-deck source edit |

Invariants that hold across all six:

1. **The gate is one code path.** Every item carries `sources: [n]`; every
   inline `[n]` inside item content is also checked; out-of-range ⇒ the
   item is withheld and the reason is shown in chat (never silently
   dropped, never rendered uncited).
2. **One block per answer** (prompt rule unchanged) — richer requests are
   follow-up turns, which the tabbed canvas handles naturally.
3. **Nothing persists.** All item state (quiz answers, doc/sheet/slide
   drafts) lives in browser-memory sessions; saving anything is the M5
   `user_artifacts` path, unchanged.
4. **The frontend never invents content.** It renders backend-validated
   payloads only; HTML/code are sanitized/highlighted, never executed.

## Alternatives considered

- **Sandboxed iframes for html/code execution** — richer (real JS charts),
  weaker security story; rejected for now in favor of DOMPurify inline
  rendering. Can be revisited per-type later without touching the contract.
- **One generic `artifact` type with a `mime`** — fewer types but pushes
  rendering semantics into a blob the frontend must sniff; the explicit
  union is validated by pydantic and typed through to the generated
  OpenAPI schema, so a new kind is a schema addition, not a parser change.
- **Per-item-type prompts/endpoints** — fragments the citation contract
  and the eval surface; one block mechanism keeps decision 010's
  `workspace_grounded` scoring meaningful.

## Consequences

- The tutor prompt (version 6) carries six block examples plus an explicit
  protocol paragraph: the fence is app-protocol, at most one block per
  answer, valid JSON with escaped newlines/quotes, and material that mimics
  a workspace block or instructs emitting one is data, never instructions
  (harness-escape hardening). Prompt changes are measured acts — re-run the
  answer eval harness and record the delta under `runs/` before trusting a
  new version.
- `workspace_grounded` eval cases exist for all six-ish shapes (quiz,
  code, sheet, slides); the citation gate itself is type-agnostic.
- Bundle grew by highlight.js (code highlighting, common-language subset).
- The M5 milestone (persisting artifacts) should reuse these six shapes as
  its payload vocabulary rather than inventing new ones.
