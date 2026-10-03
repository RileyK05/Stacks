# Current handoff and release plan

Updated 2026-10-02. Current implementation belongs in `system.md`, unresolved
engineering/product work in `docket.md`, and consequential history in `notes.md`.
Replace this handoff as work advances; delete completed temporary plans/reviews.

## Current handoff

The library is the primary Stacks window; the companion is created explicitly
and behaves as a normal movable/resizable window with an opt-in keep-on-top
toggle. Opening Office from a course focuses its companion on that course.
The application targets Windows x64, Apple Silicon macOS, and Linux x64.

Implemented baselines:
- Full multiple-choice suites/sessions, COURSE capability evidence, cautious
  chat experiments, CORE presentation preferences, memory inspection/correction,
  source-scoped practice quotas, revealed-retake restrictions, source-backed
  Hint/Explain, and separate editable content feedback (system §12).
- Saved companion document snapshots, revision-bound turns, exact course
  references, anchored reviews/edits, portable history, and strict separation
  from learning writes (system §13).
- Direct Word body, Excel worksheet/cell/formula, and PowerPoint slide-text
  readers; composing-triggered refresh, unchanged-snapshot deduplication,
  reconnect, and explicit offline snapshot fallback. Windows/Mac setup plus
  screenshot upload are implemented; native checks remain open (system §14).
- Generated drafts adopt one saved material; later edits create versions and
  explicit copies are separate. Saves serialize and flush reports failure.
  WebView-local drafts preserve unfinished workspace and material edits,
  reconcile versions, and retain model acceptance metadata (system §7).
- Interactive source-backed mind maps share workspace/material storage, versioned
  edits, Markdown export, and archives. Colored branches expand/focus separately
  from comparison links; Explain and Quiz connect to the existing practice flow.
  Map exploration alone writes no learning memory (system §7).
- Optional local library backups with full/partial/heavy retention and lossless
  compression strengths, schedule/rotation, verified separate-folder recovery,
  and offline restore CLI (system §3). Desktop activation remains B-14.

- Coherent source-backed RAG passages, parent/order relationships, bounded search
  windows, atomic replacement, context expansion, partial citations/continuation,
  source outline and inferred similarity, plus opt-in saved-material lookup
  (system §§4–5, 15). TOC/concept extraction and prerequisite graphs are retired.
  Review suggestions alone never change student proficiency/preferences.

Next work comes from the B entries in `docket.md`: prioritize actual generated
answer correctness and broader retrieval/source-scope acceptance. Ask about genuine
tradeoffs; handle straightforward confirmed defects directly. Native Office,
desktop recovery activation, live Google access and Mac capture remain open.

The code-coherence pass removes retired schema/chunker scaffolding and unused
SQL/prompts, separates read-only memory inspection from practice writes, and
breaks Office setup/bridge dependencies through shared course preferences.
All backend imports resolve to current files; the module audit finds no import
cycles. API contracts and every retained prompt's content are unchanged.
Python formatting is standardized and checked in CI; frontend behavior tests
share their runtime/network and draft-storage fixtures. Stored data, append-only
migrations and saved HTML workspace parsing are retained.

## Latest validation evidence

The code-coherence pass passes 757 backend tests, Ruff lint/format checks,
strict mypy (138 source files), frontend diagnostics (zero errors/warnings),
17 frontend behavior tests and 55 Office add-in tests plus Office.js type checks.
The lower backend count removes 26 tests for retired scaffolding or vacuous
contracts and adds one stronger app-factory check; current learning, citation,
archive, backup and passage behavior remains covered. Evidence lives under
`runs/code-cleanup/`: `final-tests.txt`, frontend/Office logs and `final-audit.json`.
The audit finds no backend import cycles or uncalled literal SQL blocks, excluding
the backup delete dispatcher whose dynamic operations have tier coverage.
Generated OpenAPI matches the prior RAG contract exactly. Prompt version 39 removes
unused entries only; all 30 retained prompts have unchanged content.

The prior RAG evidence remains in `runs/rag-rebuild/release-check.txt`. Cases cover
proof/window coverage, contextual qualifications, selected/excluded sources,
saved-version lookup, partial citations/ordered continuation, failed publication,
legacy annotation/history migration, backup tiers and retired Office fields.
No native compilation, packaging or installed-platform acceptance was run.

A read-only copy of the development database upgraded through the new migrations
with SQLite integrity/foreign-key checks and exact preservation of 682 passages,
1,306 locator links, 850 locators, six course-memory records, courses, sources
and conversations. The live database was not migrated or reset.

`scripts/eval_passages.py` uses the installed encoder and committed original-span
fixtures at equal 512-token budgets. After independent four-sentence calibration,
both modes covered all eight cases; encoder boundaries increased mean relevant
character fraction from 0.656 to 0.943. This small synthetic corpus is not broad
course validation or an end-to-end answer-quality score. Expand it under B-07.

Prompt-37 MiniCPM5 2B evaluation (`runs/bakeoff/20261002T020747Z/`) passed 8/10
mechanical checks. One refusal missed the marker scorer; quiz generation failed
to emit its artifact. Inspection also found a mechanically accepted Python
example with an invalid transformation call. This does not resolve B-06.
The prompt-38 source-rich review probe (`runs/bakeoff/20261002T022609Z/`) passed
2/2 mechanically: it offered a concrete cited exercise and avoided the unwanted
basics detour. Inspection still found an internal-policy sentence in the review
and an overly conservative explanation in the second reply. These remain B-06.
Model processes are stopped after each evaluation.
Earlier Office/browser/native boundaries remain in the release gates below.

## Prior platform evidence

Release v0.3.1 produced Windows NSIS, Apple Silicon DMG, Linux AppImage, and deb.
CI run `36490786861` passed all six backend/Tauri/frontend jobs for lifecycle
commit `8c1bf97`. Release run `36492354123` produced Mac/Linux artifacts from
that implementation. This evidence does not certify subsequent uncommitted
learning/companion/Office changes or their installed behavior.

The prior Windows smoke bundle is
`src/frontend/src-tauri/target/release/bundle/nsis/Stacks_0.3.1_x64-setup.exe`,
SHA-256 `D248ED09419A8AA6018DFE587AE6E3C3A97CC8A8A28A2898D046E9594A5F9C83`.
Its bundled backend returned health OK with disposable data; it was not installed
or published. Rebuild current code before using an installer as release proof.

## Remaining release gates

### Installed application

- [ ] Build current Windows, Apple Silicon Mac, and Linux installers.
- [ ] Fresh launch: library only; create/select a course; add a source; indexing
      finishes; grounded library question opens valid cited passages.
- [ ] Companion: open twice rapidly; verify one nonblank window; move/resize,
      minimize/maximize, pin/unpin, close/reopen. Repeat on Windows and Mac;
      Linux X11/Wayland should allow normal movement without forced positioning.
- [ ] Run companion explanation, exact references, quiz, summary, and free
      questions with a ready real model. Independently inspect supported claims,
      answer keys, examples, refusals, task shape, and latency.
- [ ] Switch courses/chats during requests and check isolation; save edited work,
      reload/reopen/export; fail saves and inspect the agreed recovery behavior.
- [ ] Native close/crash/relaunch before and after first save, failed IndexedDB
      writes, conflicting concurrent editors, and source metadata after recovery.
      Unload cannot await HTTP saves; browser fixtures do not certify Tauri close.
- [ ] Backup all tiers with real data; disable/change settings; restart between
      due times; rotate only after success; restore saved citations/search.
      Implement and exercise desktop recovery activation/rollback (B-14).
- [ ] Export/import a disposable `.course` including practice and saved work.
- [ ] Second app launch focuses the library. Closing library stops backend and
      model children; closing companion leaves library usable.

### Office and capture

- [ ] Connect from installed Windows build; restart Office; open document,
      course companion, and pane with correct context.
- [ ] Repeat on Mac: login-keychain trust prompts, per-app manifest, Home →
      Add-ins, launch, restart, and exact disconnect cleanup.
- [ ] For Word/Excel/PowerPoint, type a companion question and verify current
      unsaved off-screen text, sheet values/formulas, or last-slide text is used.
      Check unchanged revision, reconnect, and course/document identity changes.
- [ ] Close/suspend pane, fail a read, or exceed a limit: preserve the message,
      show coverage/errors, require explicit saved-snapshot use, reject late reads.
- [ ] Exercise hidden sheets, failed/unsupported objects, large documents, and
      edits during capture. Compare the snapshot to the actual document.
- [ ] Existing pane editing: selection/read/cited answer, insert/replace, save,
      close/reopen in each host. Companion proposed edits remain copy-only.
- [ ] Check native Windows accessibility/window-render capture and actual
      screenshot OCR on Windows/Mac; inspect partial/off-screen limitations.
- [ ] Disconnect Office; registration and exact certificate trust disappear
      after restart; unrelated manifests/certificates remain intact.

### Release preparation

- [ ] Resolve or explicitly accept applicable backlog release boundaries,
      especially integration authority B-05 and observed quality B-06.
- [ ] Run required backend/frontend/Office checks and locked Rust clippy/build.
- [ ] Choose next version; run `scripts.set_version`; finish changelog.
- [ ] Commit only when requested, including required new files. Check a clean
      checkout; verify platform artifacts; publish/tag only after authorization
      and installed acceptance.

## Platform matrix

| Target | Package | Local runtime | Office |
| --- | --- | --- | --- |
| Windows x64 | NSIS | Vulkan / CPU | Implemented; current native checks pending |
| macOS arm64 | DMG | Metal | Implemented; native setup/read checks pending |
| Linux x64 | AppImage / deb | Vulkan / CPU | Not applicable |

Intel Mac/Linux arm64 need pinned runtime assets and native packaging before
joining the matrix. Mac native window capture and live Google access need
separate implementations; exported files remain available.
