# Current handoff and release plan

Updated 2026-10-03. Current implementation belongs in `system.md`, unresolved
engineering/product work in `docket.md`, deferred candidates in `backlog.md`,
and consequential history in `notes.md`.
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
  offline restore CLI, and desktop activation with rollback (system §3, B-14).
  Activation validates, migrates, and swaps the recovered database + `raw/`
  into the live data folder with the backend stopped, keeps the previous
  library, and restarts the backend; models/runtime/Office state are preserved.
  The activation swap is exercised on isolated data dirs; the full installed
  desktop restart journey remains the B-10 native gate.

- Coherent source-backed RAG passages, parent/order relationships, bounded search
  windows, atomic replacement, context expansion, partial citations/continuation,
  source outline and inferred similarity, plus opt-in saved-material lookup
  (system §§4–5, 15). TOC/concept extraction and prerequisite graphs are retired.
  Review suggestions alone never change student proficiency/preferences.

The next planned change is the shared model-output controller, scoped below.
Per-attempt billing, explicit quiz-count checks, the hidden six-question cap,
title-only artifact validation and conversation-bound teaching evidence were
repaired during docket triage. Recovery, checkpointing and context budgeting
below remain planned. B-06 remains the broader
generated-answer correctness gate; B-07 owns retrieval acceptance. Ask about
genuine tradeoffs; handle straightforward confirmed defects directly. Native
Office, desktop recovery activation, live Google access and Mac capture remain open.

The code-coherence pass removes retired schema/chunker scaffolding and unused
SQL/prompts, separates read-only memory inspection from practice writes, and
breaks Office setup/bridge dependencies through shared course preferences.
All backend imports resolve to current files; the module audit finds no import
cycles. API contracts and every retained prompt's content are unchanged.
Python formatting is standardized and checked in CI; frontend behavior tests
share their runtime/network and draft-storage fixtures. Stored data, append-only
migrations and saved HTML workspace parsing are retained.

## Active plan: model output and completion

### Objective and scope

Complete the requested answer or study material within the chosen model's real
limits. Support capable models without imposing the bundled model's small output
allowance on every connection. Keep budgeting, retries and optional compaction
internal; students interact with their answer, material and understandable progress.

This work covers output allowances, cutoff detection/recovery, bounded generation
of longer materials, integration and evaluation. It does not redesign provider
setup/routing, add OpenRouter features, replace retrieval, introduce a general
coding agent, or add a PDF exporter. A document intended for PDF is generated as
structured content first; file rendering is a separate existing/future export step.
No native compilation or packaging is part of this work.

### Verified starting points

- `common/provider.py` chooses output allowance by model profile, falling back
  to 2,048 tokens. The bundled runtime context is configured to 8,192 tokens;
  these are distinct settings, not universal model capabilities.
- A provider length stop raises before returning text. Reported usage is now
  recorded before output validation, including empty/truncated attempts and
  reasoning retries.
  The tutor retries once with "much more briefly" at the same allowance. Artifact
  editing and quiz help call the provider separately; composition also has schema
  fallback and content-repair calls. Nested retries can multiply attempts.
- Workspace quizzes allow at most 20 questions; saved quiz content allows 100.
  Increasing an output allowance alone cannot change this product contract.
- Saved material versions, source snapshots, citation checks, editor recovery and
  rolling conversation summaries already exist. Reuse these boundaries.

### Behavioral contracts

1. Success means the requested scope is complete, structurally valid and grounded,
   not merely that generation stopped normally or JSON parsed. Do not silently
   shorten a requested quiz, omit sections, or replace an artifact with prose.
2. Pin course, selected sources, numbered evidence/snapshots, document revision,
   artifact base version and model choice for a generation. Late results cannot
   land in a different course, source selection or edited artifact. Preserve
   existing routing rules; do not introduce new automatic model substitution.
3. Preserve original evidence and its identifiers across units. Generated sections
   and summaries are working context, never factual authority. Revalidate at final
   publication and retain actual supplied excerpts in provenance.
4. Incomplete output is internal recovery data, never a complete answer, quiz,
   saved artifact version or reusable answer-cache entry. Quiz keys remain hidden
   from chat, progress and raw error output.
5. Generation, retries and compaction write no COURSE proficiency or CORE
   preferences. Delivered hints still use existing assistance/assessment guards.
6. Hide mechanics, not outcomes: incomplete work remains visibly incomplete;
   cancellation, failure and preservation of prior work are understandable.

### Implementation sequence

**1. Separate task demand from model limits.**

Add a versioned output policy using the existing config/profile seams. Distinguish
desired output allowance by task, model output ceiling, usable context capacity,
reasoning allowance where applicable, and a context safety margin. Profiles are
model/connection-specific where runtime allocation differs; unknown limits stay
unknown with a configurable conservative fallback, not invented capabilities.
Provider discovery and new settings UX are deferred.

Reserve output space before assembling the prompt. Count with a compatible
tokenizer when available; otherwise explicitly use a conservative estimate in
diagnostics. Include instructions, framing, history, evidence and schema overhead.
Do not use encoder token counts as exact generation-model token counts. A larger
ceiling permits more output without requesting unnecessarily verbose prose.

When input and output cannot fit, reduce irrelevant context or split a material
unit. Preserve necessary evidence, qualifications and task constraints. If they
still cannot fit, return an actionable failure instead of relying on silent
server truncation. Test candidate allowances (including 4k/8k on capable models)
before choosing defaults; do not apply those numbers to every endpoint.

**2. Normalize one-call outcomes and share recovery accounting.**

Keep `provider.py` as the routed transport/usage seam. Capture complete, length-
limited, empty, rejected and interrupted outcomes with reported usage and stop
reason before downstream validation. Keep incomplete text internal and strip
private reasoning from visible content. Record usage for cutoff/invalid-content
attempts as well as successes when the provider supplies counts; missing counts
must not become claimed exact measurements.

Put output recovery in one small shared controller (`common/generation.py` is the
proposed home), with one operation-level attempt, elapsed-time and token budget.
All schema fallbacks, repairs, continuations and section calls consume this budget;
there is no fresh retry allowance per nested helper. Recheck the existing user
usage limit before each further call. Preserve cancellation and provider errors;
rate-limit handling is not reclassified as an output cutoff.

For a cutoff, retry the same bounded unit with a larger allowance only when it
fits verified limits and the operation budget. If that cannot solve it, split
supported materials. For ordinary prose, permit bounded continuation using the
same evidence and task; assemble and check repeated/unfinished content before
delivery. Regenerate incomplete structured units rather than concatenating JSON
fragments or asking the model to invent missing closing syntax. Empty output and
invalid content have separate recovery decisions. Replace the tutor's blanket
"be shorter" retry and account for existing compose repair paths.

**3. Generate longer materials as independent complete units.**

Start with quiz questions and study-document sections. Keep a one-call path when
the requested scope fits; do not force small batches on capable models. Establish
requested count/topic coverage or section order before generation. Prefer
deterministic structure when the request provides it; use a bounded outline call
only when needed, validating its scope before using it.

Generate complete schema-validated units sized for the selected model. Each unit
gets the task, relevant original evidence, stable citation identifiers, and only
the minimal prior-output context needed for coherence and duplicate avoidance.
Track completed unit IDs and remaining scope. Retry/split only unfinished units;
merge accepted units deterministically and check count, ordering, duplicates,
coverage, citations and format-specific constraints before publishing.

Use a lightweight local generation operation tied to the existing chat/material
flow, not a second artifact store or general-purpose job framework. Persist
validated checkpoints only where needed for long-material resume, using one
append-only migration if necessary. Checkpoints are hidden drafts, excluded from
practice, generated-material retrieval and finished exports. Resume uses the
same pinned inputs or requires a new generation after they change. Reuse existing
artifact adoption/version conflict checks; publish one completed material, never
one visible version per batch. Course deletion removes pending work.

Keep the current 20-question workspace limit initially and report out-of-contract
requests honestly. Enlarging suite limits is a separate product decision. Slides,
sheets, maps and code continue through budgeted single-unit recovery initially;
enable splitting only with explicit adapters and final checks (map IDs/edges,
table headers, code integrity, etc.). They cannot inherit naive list/text merging.

**4. Keep compaction optional, local to the task and invisible.**

Most generations start from a bounded task and retrieved evidence, rather than
the entire chat trajectory. Reuse the existing chat summary when appropriate.
For a long material, retain structured completion state and reload relevant source
evidence per unit; do not continuously append every section to the next prompt.
Summarize prior generated prose only if needed for coherence and capacity.
Required scope, source identity, numbers, citations and current edit targets stay
in explicit records, not lossy summaries. Compaction cannot stand in for cutoff
recovery. Do not add a user-facing compaction control or status notification.

**5. Connect delivery and failure paths.**

Apply the controller to tutor answers, workspace generation, material edits,
quiz Hint/Explain and companion/Office callers through their existing seams.
Background summaries retain appropriate small budgets and cannot create recursive
recovery. Longer material operations expose simple progress such as "Preparing
your study guide" or "12 of 20 questions prepared", cancellation and retry/resume.
Use an operation API only where longer work needs polling/resume beyond the
current request lifetime; regenerate frontend API types if contracts change.

Preserve current saved work throughout recovery. Cancelled/failed edits do not
overwrite a version. Failed long generation can retain prepared work as an
explicit unfinished draft, with finished export/practice disabled. Ordinary
answers deliver a checked complete response or a clear failure; raw truncated
JSON and internal policy language never leak into the user flow. Operational
diagnostics remain available to developers without forcing technical choices on
students. No new token sliders or retry configuration are required in normal use.

### Acceptance and evidence

- Force cutoff mid-sentence and mid-JSON: bounded recovery produces a complete
  result or understandable failure; no partial success/cache/version/practice.
- Verify exact requested quiz count within existing limits, complete keys and
  explanations, section coverage, no duplicated units after retry/resume, and
  valid original citations throughout. Inspect actual correctness independently.
- Test short-answer/hint budgets, large-output capable profiles, unknown profiles,
  reasoning consuming allowance, near-full input, provider context rejection,
  absent usage, cancellation, exhausted budgets and nested schema repairs.
- Test source/course/document changes, edits during generation, restart/resume,
  failed checkpoints and course deletion. Quiz help must retain answer-leakage
  and late-delivery assessment guards. Generation must not alter student memory.
- Measure completion, correct requested scope, semantic correctness, grounding,
  latency, total calls/tokens and wasted output separately. Compare the current
  baseline with capable-model and constrained-model cases under identical tasks;
  local-only green checks do not certify the design for stronger models.
- Run targeted tests while implementing, then required backend/frontend/Office
  lint/type/behavior checks. Measure prompt/model changes through the existing
  eval harness and independently review generated materials. No native builds.
  If a capable endpoint is unavailable, mark live verification pending rather
  than treating mocks as quality evidence.

Implement steps 1–2 first, then quiz/document units and their delivery lifecycle;
integrate remaining call sites and run acceptance before declaring this plan
complete. On completion, transfer implemented contracts to `system.md`, remaining
quality gaps to B-06 and consequential decisions to `notes.md`, then remove this
active-plan section. Keep the seven-document lifecycle; create no completed archive.

## Latest validation evidence

The current docket triage passes 845 backend tests, Python lint/format and strict
mypy (145 source files), frontend diagnostics with zero errors/warnings and 19
behavior tests. Office.js diagnostics and 55 add-in tests also pass. No native
compilation or packaging was performed. Confirm-dialog and flashcard component
changes are typechecked; installed keyboard/navigation behavior remains a native
acceptance check. The active docket retains semantic quality, output recovery,
history continuity, Office setup/read coherence and platform gaps. Prior evidence
below records earlier baselines and does not replace those current limits.

The issue pass (B-02, B-06, B-07, B-13, B-14) passes 774 backend tests, Ruff
lint/format checks, strict mypy (141 source files), frontend diagnostics (zero
errors/warnings) and 17 frontend behavior tests. It adds: source-scope
revisions in chats (migration 018) so excluded sources cannot supply facts
through a rolling summary or prior reply; a desktop activation command that
stops the backend, swaps a validated backup database + `raw/` in place with
rollback, and restarts it; a pinned cross-platform `constraints.txt` with a CI
drift gate; a Windows-safe bake-off report path; production eval seeding moved
to `src/backend/evals/seed.py`; a per-process pytest basetemp; and semantic
answer-eval infrastructure (a judge seam, a committed semantic case file, and
enforcement of previously ignored expectation keys). Encoder ONNX↔torch parity
and the answer-eval/retrieval-eval suites now have CI jobs. The retrieval eval
reports precision@k and MRR and its committed cases run on every push.

**B-06 remains open as a quality gate:** the infrastructure exists, but actual
generated-answer correctness has not been established. Run the semantic suite
against capable and local models, inspect the quiz keys/worked examples/edits
by hand, and measure false acceptance/refusal. **B-07 remains open as a
retrieval-acceptance gate:** the committed cases are synthetic; real PDFs,
OCR, unmarked proofs, tables, slides, restricted sources and large courses are
still unmeasured. Both now have harnesses and baselines; neither has
independent real-material evidence.

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
      Desktop activation/rollback is implemented and unit-tested (B-14); exercise
      the installed stop → activate → restart journey, including a failure during
      the switch, every retention tier, source-search rebuild and citation
      readability.
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
