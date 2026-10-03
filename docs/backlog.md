# Backlog

Updated 2026-10-03. Optional capabilities, unconfirmed candidates and findings whose
original premise did not establish a current defect. Active bugs, observed quality
gaps and decisions belong in [docket.md](docket.md). This is not a release blocker list.

A deferred candidate is **unconfirmed**, not proof the behavior is correct. Reopen
it in the docket with a current reproduction, relevant scale measurement or user
requirement. Keep completed fixes in the decision log, not a Done graveyard.

| ID | Idea / original finding | Disposition |
| --- | --- | --- |
| B-08 | Learning evidence beyond the baseline (quality gap / future work) | Longitudinal learning acceptance beyond the implemented baseline; future study, not a diagnosed regression. |
| B-09 | Companion analysis and recovery (future work) | Multi-pass companion review and recovery expansion are new capabilities. |
| B-12 | Additional live hosts (deferred design) | Google live hosts and Mac window capture are additional integrations. |
| F-19 | Quiz picks reset when question count changes | Edits invalidate question identity; authoritative saved-suite loading replaces the initial preview and restores saved runs. Reopen only for lost picks with unchanged question/version identity or picks applied to different questions. |
| STK-011 | Question naming a reading retrieved nothing from that reading (Q12) | Observed named-reading miss belongs to B-07 real-corpus acceptance; reproduce before a separate ranking change. |
| STK-013 | "No sources yet" shown while files are uploading | Transient upload-empty-state report needs a current UI reproduction. |
| STK-024 | Inline `[n]` citation markers in chat are inert; passage panel collapses line breaks | Panel line breaks are fixed. Clicking inline markers to open sources is an enhancement. |
| STK-025 | Context and graph passages bypass the reranker; no relevance floor; refusals list unrelated sources | Surrounding context intentionally preserves qualifications. Relevance/refusal failures remain B-07; do not remove context solely because it bypasses reranking. |
| STK-032 | False "not in the material" refusals in follow-ups: a keyword hit doesn't steer the passage window; follow-up queries are diluted (T7 laws, T11 empresarios) | Follow-up refusal/window quality belongs to B-07; current-window tests exist but real-course acceptance is open. |
| STK-035 | Enter while a reply is pending is silently ignored; the prompt stays unsent (tester T3 lost); no cancel | Pending Enter now reports the unsent draft. Cancellation/queuing remain optional features. |
| STK-042 | Word/Excel/PowerPoint file export works on Linux but is only on the saved-artifact page; the pane offers .md/.csv and "Open in Office" | Office export already works after saving; exposing it directly in the workspace is a convenience feature. |
| STK-019 | Sources listed in reverse upload order | Newest-first source order is a valid ordering preference. |
| STK-020 | Ambiguous "Reindex" control | A clearer reindex label/confirmation is a UX improvement; do not add routine approval prompts by default. |
| STK-022 | Enter did not submit the first chat question (unverified) | First Enter failure was never reproduced; pending-send feedback is fixed separately. |
| STK-026 | Duplicate passages are not deduplicated | Candidate IDs are deduplicated; semantically repeated passages need a measured diversity case. |
| STK-027 | Answers are not streamed; 60–90 s behind a static spinner | Streaming/progress and user cancellation need a feature contract; output completion remains an active defect. |
| STK-036 | Workspace tab origin "from Qn" is opaque (correct, but read as mislabeled) | The origin number was correct; clearer request/time labels are a UX improvement. |
| STK-045 | Companion: pasted documents are labelled "Partial or unverified capture"; Summarize pulls separator pages as course evidence | A paste cannot prove the original document was complete. Keep honest coverage; course retrieval quality is B-07. |
| STK-046 | Course export always says "Downloads folder"; falls back to `$HOME` silently; no location choice | The banner now shows the actual saved path. A course-export destination chooser is an enhancement. |
| STK-047 | Slides viewer/editor navigation gaps | Blank slides are intentionally preserved. Additional editor navigation is a feature, not grounds to delete content. |
| C-17 | Every PDF page is text-extracted twice (layout mode is expensive) | Alternate PDF extraction serves layout/quality checks; profile before removing it. |
| C-19 | Chunk→locator mapping is O(chunks × locators) | The cited legacy chunking module is retired; measure the current passage store instead. |
| C-20 | Chunk boundary cuts mid-word on tabs/newlines | The cited legacy chunker is retired; current passage splitting has original-span coverage tests. |
| C-24 | `normalise_question` only trims `[\s?!.]+$` | Broader cache normalization improves hit rate but risks conflating distinct questions; no incorrect answer reproduced. |
| C-26 | Eval repeats label lookups per seam | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| C-30 | Retrieval trace records the embedding model, not the generation model | Legacy trace model means embedding identity; generation identity is recorded in answers/usage. Clarify portable trace metadata if needed. |
| C-31 | Retrieval trace omits policy version and reranker identity | Persisting complete retrieval policy/reranker identity improves reproducibility; not a reproduced wrong-answer cause. |
| C-38 | Five divergent citation dialects | Runtime citation/content/edit scanners now share code-aware parsing. Eval/chat dialect alignment is remaining cleanup. |
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
| C-100 | Malformed stored trace id → 500 | Invalid UUIDs in stored traces require a supported corruption/import reproduction. |
| S-01 | **CRITICAL: arbitrary file write via artifact export path** | Choosing an arbitrary export destination is intentional local-app functionality; B-05 owns client authority. |
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
| P-01 | `get_settings()` re-reads `.env` from disk on every call | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-02 | TOML policies re-parsed per request/retrieval | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-03 | `db.connect` re-runs PRAGMAs and re-resolves the path every connection | Unconfirmed optimization/testing candidate; establish a current user-visible failure or representative profile before changing the architecture. |
| P-04 | `embed_texts` re-validates every vector's dimension per call | Dimension checking validates the contract; do not remove safety checks solely because they take time. |
| P-05 | `encoders` downloads tokenizer files with no hash/size cap | Large encoder files are reverified and small metadata downloads capped/streamed. Tokenizer files remain revision-pinned; optional extra hash pinning is future hardening. |
| P-06 | `funnel.concept_matches` loads all concepts and compiles regexes per query | Legacy concept lookup is retired; no current concept_matches path to optimize. |
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

## Secondary review candidates

Duplicates below are references, not additional tasks. Original severities are not
accepted without evidence. Confirmed citation, archive and connection defects were
handled in the main pass; speculative/style candidates remain deferred.

| Review ID | Location / existing task | Candidate or disposition |
| --- | --- | --- |
| REV-C1 | `common/provider.py` | Bound adaptation-cache growth under many endpoint/model failures; measure realistic growth before selecting an eviction policy. |
| REV-C2 / REV-L18 | P-05 | Verify tokenizer/model download integrity and byte caps; revision pinning and hash pinning provide different guarantees. |
| REV-C3 | `api/settings.py` | Setting a key can create a preset connection. Determine whether the UI/API intends this behavior and test it; do not assume it is critical. |
| REV-H1 / REV-H2 | C-15; `api/sources.py` | Measure whole-file storage/source-response memory and consider bounded streaming; gzip accumulation is also a whole-result cost. |
| REV-H4 | P-07 | Same course embedding materialization candidate. |
| REV-H5 / REV-M10 | `student_model/learning.py` | Profile observations and suites in targets on realistic history; batch/index only when cost warrants it. |
| REV-H6 / REV-M15 | `common/course_memory.py` | Profile full-material focus refresh and query costs; preserve evidence/freshness if introducing incremental updates. |
| REV-H7 | P-01 | Same settings/environment parsing cost candidate. |
| REV-H8 | Policy loaders | Process-lifetime config caches need change only if reload is promised; define invalidation for development/tests if required. |
| REV-H9 | `common/sources_repo.py` | Temporary paths can coincide, causing duplicate missing_ok cleanup. Low-impact clarity candidate, not a demonstrated failure. |
| REV-M1 | `tutor/answer.py` | Verify bounded empty/truncated-output retry count and latency; retry already has a one-retry bound, so do not add backoff without provider evidence. |
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
| REV-L2 | `common/config.py` | Test escaped/quoted .env values against documented development configuration; choose parser complexity based on actual supported syntax. |
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
