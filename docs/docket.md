# Active engineering docket

Updated 2026-10-03. This file contains unresolved problems, observed quality gaps,
required platform verification and decisions with real tradeoffs. Deferred ideas
and unconfirmed static candidates live in [backlog.md](backlog.md). Completed
fixes were removed; consequential contracts/evidence are in `system.md` and the
2026-10-03 triage record in `notes.md`. No user confirmation is required to remove
a completed routine fix.

The historical STK observations came from Linux Tauri development at `684a585`,
LongCat-2.5-Preview, five course PDFs, 27 questions, a 30-turn conversation and
artifact/export checks. That run is evidence of observed failures, not proof
every failure persists in today's tree. Current mechanical tests cannot close
semantic-quality or installed-platform acceptance.

## Decisions awaiting user input

### B-04 — Local runner scheduling

One llama-server switches models under a lock while generation HTTP runs outside
that lock. Changing models can interrupt a request; status/stop may wait through
startup. A runner lease and queue fit the 8 GB floor but add waiting/reloads.
Concurrent runners improve overlap but require RAM limits and eviction.
Recommendation: one runner with foreground priority, optional concurrency later.
The user has been asked to choose. Related: X-07, X-11, X-12, X-15, X-16.
Reproduce competing foreground/background calls and stop-during-load before
selecting cancellation/shutdown behavior. This pass did not implement a scheduler.

### B-05 — Integration authority and Office pairing

Arbitrary user-selected export destinations, custom local/LAN model URLs and
opening selected Office documents are intended capabilities. Define which clients
may exercise them; do not silently restrict them to an app-only directory.
Recommendation: authenticated one-time Office pairing and narrow grants tied to
native file selections. The user has been asked about pairing. Optional Office
authentication still exists; loopback and the desktop token do not isolate the
app from every program running as the same OS user. S-01/S-04/S-07/S-08/S-18 are
references to this decision, not five independent emergency rewrites.

### B-14 — Backup fidelity

Full/partial/heavy currently choose retained categories; ZIP compression preserves
retained content exactly. The user already authorized willingness to lose detail
in reduced tiers. The remaining design decision is which source representations
may lose detail while exact passages/locators remain recoverable. Lossy downsampling
can discard visual evidence; compressing memory into summaries can discard history.
No lossy source rewriting was added. Installed backup activation remains B-10.

### C-63 — Cloud budget semantics

Current budget checks are a stop between requests, not reservations: concurrent
in-flight calls can overshoot the remaining allowance. Usage now includes empty,
truncated and reasoning-retry responses before their validation fails, and local
traffic is classified separately. A hard ceiling needs token reservations and
rules for missing/late provider usage. Decide whether that extra cost/queuing is
required; do not describe the present soft stop as a strict spending cap.

## Actual output and history gaps

### Output completion — STK-004, STK-029, STK-038, STK-040

The LongCat profile, per-attempt usage accounting, explicit quiz-count checks
and title-only document/deck withholding are fixed, but the shared
model-output controller remains **planned** in `plan-notebook.md`. Unprofiled
models default to 2,048 output tokens. The quiz schema now supports the existing
20-question workspace limit; a requested ten-question quiz either has ten verified
questions or is withheld with an honest count. Multi-unit recovery/checkpointing
is still absent. Degenerate content beyond title-only material can still pass
mechanical validation. Summaries can
consume their allowance in reasoning and fail; those failed completions are now
billed correctly, not silently free.

Implement model/task budgets, count complete requested units, bounded unit retries,
checkpointed assembly and truthful partial/failure results through the shared
provider seam. Preserve pinned source scope and prevent partial/retried work from
creating duplicate artifacts or student-memory observations. Acceptance requires
ten usable questions, substantive document/deck sections, and retained progress
after cutoff; JSON validity alone is insufficient.

### Conversation continuity — STK-028, STK-030, STK-031, STK-037

`tutor/chat.py` still combines a rolling summary with four recent messages and
600-character excerpts; failed/delayed summaries leave intervening history absent.
Workspace quiz history still omits questions beyond six and clips the key. This
can make a previous quiz unavailable or make conversational grading contradict
its own saved questions. Summarization now includes workspace notes and singleton
older messages, but that does not repair the context gap or full-artifact recall.

Complete the context portion of the output plan: retain unsummarized state within
the actual model budget, retrieve referenced saved turns/items, and route quiz
grading to the stored practice suite/key instead of re-deriving it from new course
retrieval. Conversation meta-questions need saved-chat evidence, while academic
claims still require eligible original material. Old citation numbers cannot be
reused against a new numbered source list. Acceptance: make a ten-question quiz,
discuss another topic, grade question ten correctly, then change source selection
without resurrecting excluded factual evidence.

### Request routing and scope — STK-033, STK-039

Artifact intent heuristics can mistake an essay mentioning a
table for a spreadsheet; the study-sheet case is now fixed, while an essay
mentioning a table still needs a current routing check. Changes to an existing
table need an explicit edit route.
Week/exam scope phrases can retrieve exam-logistics pages instead of lesson
content. Filename week tags do not prove the syllabus's exam coverage. Distinguish
the requested output, target item, academic topic and source scope; ambiguous exam
scope should be shown to the student rather than guessed. Check the original
Week 1–5 guide and follow-up table-edit journeys on current real material.

### Workspace export and narrow layout — STK-041, STK-043

Workspace `.md`/`.csv` still use blob downloads, which the Linux development
webview wrote into its working directory without a destination notice or source
legend. Use the existing cited artifact export with a native destination choice,
including unsaved draft content, and show the actual saved path. Course export's
incorrect "Downloads" notice is fixed separately. Narrow sheet cells still use
single-line inputs; verify readable/editable long cells and quiz options in the
companion. Native download behavior needs B-10, not an unsupported success claim.

## Quality acceptance

### B-06 — Generated academic and pedagogical correctness

Independent semantic fixtures, expectation enforcement and a judge seam exist.
Run and inspect them against capable and local models. The broader recorded run
passed 7/10 and included an output-limit failure; narrow 2/2 probes did not close
that gap. Later better mechanical counts still accepted an invalid code transform.
Verify explanations, all quiz alternatives/keys, generated examples, hints that
help without leaking answers, research hypotheses, edits and mind-map membership.
Literal co-occurrence and citation numbers do not prove entailment. Preserve false
acceptance/refusal measurements and avoid executing generated code for validation.

STK-023 is part of this gate: broken PDF glyphs now trigger OCR instead of guessed
digit repair, but low-quality retained passages can still induce invented numeric
claims when OCR is unavailable. Models must admit illegible evidence, not infer a
number from font punctuation. This pass did not establish real-model correctness.

### B-07 — Real-course retrieval and extraction

Committed synthetic span/retrieval cases and precision/MRR/recall checks exist;
real labeled PDFs, OCR, proofs, tables, slides and large courses remain unmeasured.
Rerun named-reading misses, follow-up refusals, irrelevant logistical pages and
named-table retrieval (STK-011/-025/-032/-044) against the current tree. Evaluate
context preservation/relevance together before deleting graph or neighbor context.
Measure index memory, source update latency and O(n²) similarity rebuild cost.
No prerequisite/concept/TOC factual store should be resurrected.

C-16 remains a resource gap: PDF bitmap/PIL handles now close, but ingestion can
still batch up to 50 rendered pages into one OCR request. Bound per-page pixels
and batch resident bytes while retaining page alignment and full-source coverage
reporting. Do not silently drop pages or concatenate ambiguous OCR page boundaries.

### B-10 — Native installed journeys and lifecycle fault checks

No compilation/packaging was performed, as requested. Python/frontend/Office unit
checks do not establish installed Windows/Mac/Linux behavior. Exercise companion
opening, TLS trust/untrust and port recovery, Word/Excel/PowerPoint reconnect,
download destinations, backup activation/restart/rollback, and sudden process exit.
The source fixes for X-01/X-04/X-05/R-04/R-05 now drain stdout during health polling,
clean up watcher-spawn failures, bound readiness waits and parse status codes.
Rust formatting parsed them; they remain uncompiled and require native verification.
X-06 still needs a graceful setup/spawn failure page. X-09 needs confirmed job-object
assignment/termination coverage; do not claim hard-kill process-tree cleanup from
the normal stdin-EOF shutdown path alone.

### B-11 — Document changes during Office capture

Revision-bound Stacks snapshots reject stale replies, but an Office document may
change while multiple ranges/slides are read. A whole-document snapshot should
detect that change, retry within a bound or report uncertain coverage. Decide the
read-coherence guarantee before picking event counters/re-reads; verify each host.
PowerPoint notes now follow actual slide relationships when a deck is reordered;
unlinked notes are labelled uncertain. Live read coherence remains unresolved.

## Remaining concrete engineering work

| IDs | Current concern | Next acceptance |
| --- | --- | --- |
| S-16, S-29, S-30 | Individual certificate/manifest writes are atomic, but concurrent issuance/connect/disconnect and partial trust/register failure are not one coordinated operation. | Fault injection preserves existing trust/registration, reports failed rollback and makes status safe during disconnect. |

Confirm-dialog Tab/focus restoration and flashcard order invalidation are repaired
in source; keyboard interaction remains part of installed UI acceptance. F-19's
generic reset claim is deferred: question edits deliberately invalidate a session,
while the server's saved suite supplies the authoritative question/key identity.

Delete a resolved entry once its behavior and durable contract are recorded.
Do not turn this into another historical Done ledger.
