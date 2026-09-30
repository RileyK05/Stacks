# Current handoff and release plan

Updated 2026-09-30. Current implementation belongs in `system.md`, unresolved
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

Next work: use the remaining B entries at the top of `docket.md`. Ask about genuine
tradeoffs; handle straightforward confirmed defects without boilerplate questions.
Keep model-quality failures and native verification gaps visible until resolved.
Google live access and automatic Mac window capture are not implemented.

## Latest validation evidence

The mind-map pass completed 778 backend tests, then 88 focused map/compose/support/
archive checks after source/model metadata changes, and 15 map checks after the
final saved-quiz version/pinned-help regression. Ruff, mypy across 132 source
files, regenerated API types, frontend diagnostics, 17 frontend behavior tests,
and production build passed, including the final HTML edge controls.
Browser acceptance used isolated synthetic sources and simulated model output:
expand/focus/comparison details, automatic evidence loading, Explain, generated
saved quiz, complete scored submission, map adoption, reload, restored quiz score,
and full saved map view. It exposed and fixed lazy citation loading and an
unreliable SVG edge hit area. Proof: `runs/mind-map/mind-map.png`.
The real MiniCPM5 2B prompt-35 probe is `runs/mind-map/semantic/report.json`;
it still omits named examples and produces imperfect explanations/alternatives.
The latest narrow harness is `runs/bakeoff/20260930T174204Z/`: 1/2 mechanically;
inspection found a proper refusal missed by the marker scorer. These results do
not resolve B-06 or certify installed native behavior.
The fresh acceptance tab, fixture services, and evaluation model processes were
stopped after acceptance. An earlier stalled IAB tab (8) could not be closed
through either documented binding; it may remain pointed at the stopped fixture.

The quiz support pass completed a 761-test full backend run, followed by focused
assessment/archive, 11-case support/routing, and 14-case backup checks after the
last changes. Ruff, mypy across 128 source files, generated API types, frontend
diagnostics, 14 frontend tests, and production build passed. Browser acceptance
covered hint → assisted submission → Explain → independent question/help votes
→ optional reason → reload/reopen with saved results, assistance, feedback, and
cached help. Proof is `runs/quiz-support/quiz-controls.png`; it uses simulated
model output. A real MiniCPM5 2B probe exercised a reasoning hint, missed-answer
explanation, and excluded-question explanation
(`runs/quiz-support/semantic/report.json`, prompt 31). Basic concept handling
improved after inspection, but the excluded reply still echoed a feedback-policy
sentence. The narrow 2/2 grounding/refusal rerun is
`runs/bakeoff/20260930T140643Z/`; broader quality remains B-06. Temporary browser,
fixture services, and the evaluation model process were stopped.

The 2026-09-30 saving/backup pass completed 751 backend tests, Ruff, mypy across
127 source files, generated API types, frontend diagnostics and production build.
The preceding Office pass completed 55 JavaScript tests and Office.js type checks;
Office code was unchanged by saving/backup and quiz work. One existing
Starlette/httpx deprecation warning remains. A subsequent 18-case course-archive/
settings run covered a new WAL-size race: Settings must stay usable if
checkpointing removes the WAL during measurement. These checks cover retention
bytes (not just deleted rows), source hash changes, failed/overlapping backups,
restore schema/path/hash validation, restored source queues/citations, adoption/
retry/copy and course-import identity, in-flight edits, failed flush, recovery
revision/writer isolation, and model-save metadata.

Isolated browser checks covered edited draft save/reopen, complete quiz results
and revealed retakes, document refresh/deduplication, latest tail text, offline
recovery, reload, and course isolation. They used seeded or simulated model/Office
output. Browser acceptance also exercises backup settings/create/recover and
unfinished-before-first-save draft reload. A persistent-editor recovery failure
missed by helper tests was reproduced and corrected. The visible failed save →
reload → recovered title/body → Retry journey persisted the exact paragraph as
version 4 of the same artifact; local proof is `runs/save-backup/recovered-draft.png`.
Actual-store tests include client proxy metadata to catch that serialization edge.
Folder recovery was also exercised through the offline CLI; backup controls and
heavy-tier recovery have local proof in `runs/save-backup/backup-settings.png`.
The disposable fixture services and browser tab were stopped/closed. These
establish UI/persistence contracts, not real Office behavior or general factual/
pedagogical quality.

Generated-advice quality remains mixed (B-06): the broader recorded model check
passed 7/10; later narrow grounding/refusal probes do not establish general
quality. Exact stored-passage lookup is deterministic. Syntax, citation, and
draft-anchor checks cannot establish correct explanations or executable examples.

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
