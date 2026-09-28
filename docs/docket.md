# docket.md — Bugs, latent bugs, and optimizations

> **Status: static-review ledger, triaged for the companion release on
> 2026-09-28 and superseded by the central-library direction later that day.**
> Findings remain candidates until reproduced or verified. The current product
> direction in `plan-notebook.md` is authoritative when it conflicts with this
> older snapshot or finding wording.
>
> Generated from a full read of the tree at commit `7c61147` (working tree dirty:
> `companion.py`, `companion.rs`, and `routes/companion/` are untracked; several
> files modified). Every item is a *candidate* — verify before acting. Line
> numbers can drift; re-grep before editing.
>
> Severity scale:
> - **CRITICAL** — data loss, security hole, or a feature that is silently wrong.
> - **HIGH** — user-visible breakage, race, or resource leak on a normal path.
> - **MEDIUM** — wrong behavior in an edge case, hardening gap, or real perf cost.
> - **LOW** — correctness nit, inconsistent error handling, fragile assumption.
> - **NIT** — style, dead code, duplication, naming.
>
> Finding IDs are stable: `C` correctness/data, `S` security, `X` concurrency/races,
> `P` performance, `F` frontend, `R` Tauri/Rust, `O` runtime/office, `T` tests/CI,
> `D` docs/dead-code. Use them to track in review.

---

## Product direction correction (2026-09-28)

The library is again the launch and primary product surface. The companion is
created only after the user presses **Open companion** and now behaves as a
normal movable, resizable native window. The previous right-edge docking,
collapse tab, hidden library, and companion-owned Quit behavior are retired.
Windows x64, Apple Silicon macOS, and Linux x64 are core build targets; only the
optional Microsoft Office bridge remains Windows-specific.

---

## Historical companion-release snapshot (2026-09-28)

This snapshot predates the product-direction correction above. Its companion
first assumptions and release decisions are retained only as audit history.
Current release work is tracked in `plan-notebook.md`.

### Resolved or cleared in this pass

| ID | Result |
| --- | --- |
| S-02 | Chart HTML export now runs inside a sandboxed iframe under a restrictive CSP; the existing filters remain defense in depth. |
| S-03 | The desktop API now refuses production requests when no launch token is configured. Development and tests may still opt into the tokenless loopback API. |
| S-05 | App-token comparison uses UTF-8 bytes, so non-ASCII input returns 401 instead of raising `TypeError`. |
| S-06 | Production no longer publishes OpenAPI, Swagger, or ReDoc routes; development retains the generated schema workflow. |
| R-01 | The library uses `opener:default`, which includes the required command and HTTP/HTTPS URL scope. |
| R-03 | Packaged startup failures point to `backend-stderr.log` and runtime failures to `backend.log`. |
| R-08 | Main and companion windows now use separate Tauri capabilities; the companion gets only core permissions. |
| T-02 | `set_version.py` updates the Stacks entry in `Cargo.lock`, and the version test checks it. |
| T-05 | `lxml` and its typing stubs are direct dependencies instead of transitive accidents. |
| T-17 | A missing npm lockfile now fails the version bump loudly. |
| T-18 | The installer script exits with an error when Tauri produces no installer. |
| T-19 | Backend bundle cleanup no longer swallows removal failures. |
| T-24 | Release version discovery imports the version module; installer builds pass `--locked`. |
| D-01 | `system.md` was replaced with the current SQLite/Tauri/companion architecture. |
| D-03/D-04 | Public and frontend READMEs now point to the live docs and enumerate the real release gates. |
| D-05 | `.env.example` now lists the supported development overrides. |
| D-24 | `.env` is ignored and is not tracked; no secret contents were inspected. |

### Release blockers still open

| ID | Release decision |
| --- | --- |
| T-01 / D-02 | At the time of this snapshot, companion files and their references had not landed together. |
| Installer proof | The snapshot's PyInstaller + NSIS build still needed installed smoke testing without the checkout or Vite. |
| Office proof | Complete selection/read/write/save/reopen tests in Word, Excel, and PowerPoint from the installed build before advertising all three as verified. |
| S-01 | The native save dialog intentionally permits user-chosen export paths. Before wider distribution, move file writing behind a Tauri capability or formally document this desktop trust boundary. |
| S-04 | The Office pane is same-origin with its fixed HTTPS bridge but does not yet use a per-install bridge token. Define and test that boundary before wider distribution. |

### Deferred engineering work

The correctness, concurrency, retrieval-eval, performance, and accessibility
items below remain useful follow-up. Their original severity is a reviewer's
assessment, not proof of reproduction. Promote an item into the release gate
only with a failing test, a reproduced user path, or a clear security boundary.

---

## 0. The angry summary (read this first)

This codebase has real craft in it — the citation gate, the fail-closed provider
seam, the migration discipline — and then it trips over its own feet in the same
breath. The pattern I keep hitting:

1. **The transaction discipline the project brags about is violated in the one
   place it hurts most** (`sources_repo.upload_source` copies up to a gigabyte
   while holding SQLite's single writer lock).
2. **The security model is "loopback is safe" but at least three paths let a
   token-holder write/read arbitrary files and drive arbitrary HTTP.**
3. **Fail-open defaults everywhere** — auth, Office bridge, reranker, embedding
   seam — despite the entire architecture doc being about failing loudly.
4. **The new untracked `companion` code is referenced from tracked, modified
   files** (`main.py`, `lib.rs`, `tauri.conf.json`, `capabilities/default.json`).
   Commit that as-is and a clean checkout does not import.
5. **The eval harness — golden rule 3, the "center" — can't actually score the
   cases it claims to, because it only ever looks at each chunk's primary
   locator.** The kill switch it exists to drive is therefore measuring noise.

Everything below is the long form.

---

## 1. Correctness and data loss — backend core

### C-01 — `sources_repo.upload_source` holds the write transaction across a file copy
- **Where:** `src/backend/common/sources_repo.py:82-127`
- **Severity:** HIGH (explicit project-rule violation)
- **What:** `with connection()` opens an IMMEDIATE write transaction at line 82.
  `storage.write_stored_from_temp` (line 93) then copies the staged file into
  place while the writer lock is held. The docstring even claims "the file write
  happens before the row commits" as if that were the intended design. Every
  other writer (ingestion, all API mutations) blocks for the duration of a
  possibly-gigabyte copy. The project contract forbids exactly this.
- **Fix:** compute the final path, write the file *before* opening the
  transaction, then open `connection()` and insert. Keep the orphan-cleanup
  contract by tracking `final_written` outside the transaction.

### C-02 — Dead-letter gap: poison sources strand forever with no failure record
- **Where:** `src/backend/ingest/runs.py:227-234`, `src/backend/common/queries/ingestion.sql:65-82`, `:173-176`
- **Severity:** CRITICAL
- **What:** `claimed_runs` is incremented on every claim and is never reset by
  `release_stale_claims`. Once it reaches `claimed_runs_max` (default 5), the row
  is excluded from claiming forever: status stays `uploaded`, it is never marked
  `failed`, and nothing is written to `ingestion_history`. A source that reliably
  crashes a parser (segfault, OOM) simply disappears with no operator signal.
- **Fix:** when `claimed_runs` exceeds the cap, transition the source to `failed`
  with a typed "max attempts exhausted" reason, record history, and clear the
  queue row; surface `claimed_runs` in `queue_status`.

### C-03 — OCR page-merge silently discards text when the model over-splits
- **Where:** `src/backend/ingest/ocr_pages.py:22-25`
- **Severity:** CRITICAL
- **What:** if the model emits more boundary separators than there are pages
  (`len(parts) > page_count != 1`), `parts = parts[:page_count]` throw away every
  later part and the stage still reports success. All OCR text after the
  `page_count`-th separator is lost from the corpus.
- **Fix:** merge overflow into the final page or fail the stage loudly; never
  truncate silently.

### C-04 — `StageSkipped` commits whatever the handler wrote before skipping
- **Where:** `src/backend/ingest/pipeline.py:75-81`, `src/backend/ingest/orchestrator.py:230-242`
- **Severity:** HIGH
- **What:** `update_toc` deletes all of a source's TOC entries (line 240) and
  *then* raises `StageSkipped` when there are no drafts (line 242).
  `execute_pipeline` treats `StageSkipped` as success without rollback, and the
  subsequent `SUCCEEDED` observe commits the deletion. A source with no
  detectable headings silently loses previously-committed TOC entries.
- **Fix:** `conn.rollback()` before recording a skip, or move the emptiness check
  before the delete (the drafts are already computed).

### C-05 — A failed post-pipeline step leaves the run ledger stuck at `running`
- **Where:** `src/backend/ingest/orchestrator.py:343-353`, `src/backend/ingest/runs.py:178-186`
- **Severity:** HIGH
- **What:** `observer.finish(...)` writes `mark_run_terminal` but does not commit.
  If the following `runs.mark_source_indexed` raises its documented invariant
  `RuntimeError`, that is not an `IngestionPipelineError`, so it escapes the
  handler, the surrounding `with connection()` rolls back, and the terminal write
  vanishes — the run is never marked finished.
- **Fix:** commit inside `finish`, or wrap the terminal-success writes and audit
  failures explicitly.

### C-06 — Heartbeat only advances on stage transitions; long stages get re-claimed
- **Where:** `src/backend/ingest/worker.py:164-188`, `src/backend/ingest/runs.py:152-176`
- **Severity:** HIGH
- **What:** `RunObserver.observe` heartbeats only when a stage starts/succeeds/
  fails. A large embedding batch or a 50-page OCR can exceed `STALE_CLAIM_AFTER`
  (30 min) with no heartbeat, so a second worker releases and re-claims the
  source — duplicate concurrent ingestion racing the derived-row deletes.
- **Fix:** heartbeat on a timer during long stages, or require an explicit worker
  lease token to release a stale claim.

### C-07 — Standalone ingestion worker busy-spins at 100% CPU
- **Where:** `src/backend/ingest/worker.py:191-210`
- **Severity:** HIGH
- **What:** `main()` loops calling `process_batch()` with no sleep. When the queue
  is empty, `process_batch` returns immediately, so the process pegs a core. The
  docstring claims "Polls until Ctrl+C"; `poll_interval_seconds` in
  `configs/ingestion.toml` is only honored by `run_forever`, which the standalone
  entrypoint does not use.
- **Fix:** `time.sleep(interval)` between empty passes, or use `run_forever` with
  an asyncio loop.

### C-08 — Worker shutdown strands already-claimed rows
- **Where:** `src/backend/ingest/worker.py:57-72`
- **Severity:** MEDIUM
- **What:** `process_batch` breaks on `should_stop` after `claim_pending_sources`
  has committed `claimed_at` for the whole batch. Unprocessed claimed rows have no
  heartbeat and are unavailable until the stale sweep.
- **Fix:** on stop, release claims for rows not yet processed, or claim one row at
  a time.

### C-09 — Orphan-claim cleanup skips the history ledger
- **Where:** `src/backend/ingest/worker.py:134-146`
- **Severity:** MEDIUM
- **What:** `_cleanup_orphaned_claim` marks the source failed and clears the queue
  but never writes `ingestion_history`, unlike `_commit_failure_audit`. The audit
  trail is inconsistent for unexpected errors.
- **Fix:** capture `queued_at_for` and record history before clearing, matching
  the documented call-order contract.

### C-10 — `mark_source_failed` is unconditional and can overwrite a success
- **Where:** `src/backend/ingest/runs.py:312-316`, `src/backend/common/queries/ingestion.sql:104-108`
- **Severity:** MEDIUM
- **What:** it sets `failed` regardless of current status, so a late/stale failure
  audit can clobber a concurrent `indexed` (or `scanned`) state.
- **Fix:** guard `WHERE status IN ('uploaded','scanned')` and surface when no row
  matched.

### C-11 — Requeue idempotency hole: `DO NOTHING` can leave a row unclaimable
- **Where:** `src/backend/ingest/runs.py:272-294`
- **Severity:** MEDIUM
- **What:** `requeue_failed_source` updates status then calls `requeue_row` with
  `ON CONFLICT (source_id) DO NOTHING`. A stale `pending_ingestion` row with
  `claimed_at` set (or at max attempts) is left alone and stays unclaimable — the
  user pressed retry and nothing happens.
- **Fix:** `ON CONFLICT DO UPDATE SET claimed_at=NULL, heartbeat_at=NULL,
  claimed_runs=0, reason=excluded.reason`.

### C-12 — `record_history` can raise on a NULL `queued_at`
- **Where:** `src/backend/ingest/runs.py:253-269`
- **Severity:** MEDIUM
- **What:** `queued_at` is `NOT NULL` but the parameter is unvalidated `Any`; the
  success path passes `runs.queued_at_for()`, which can be `None` if the queue row
  was concurrently cleared. Result: `IntegrityError`.
- **Fix:** validate and treat `None` as a typed no-op.

### C-13 — Partially-scanned PDFs silently lose their scanned pages
- **Where:** `src/backend/ingest/orchestrator.py:131-137`
- **Severity:** MEDIUM
- **What:** OCR is deferred only when *no* page has a text layer. A mixed PDF
  ingests the text pages and silently drops the scanned ones — no warning, no
  trace.
- **Fix:** detect per-page emptiness and route empty pages to OCR, or at least
  record a warning.

### C-14 — UTF-16 / legacy encodings are silently mojibakized, and cp1252 can throw
- **Where:** `src/backend/ingest/extract.py:119-134`
- **Severity:** HIGH
- **What:** `utf-8-sig` fails, then `cp1252` "succeeds" on UTF-16LE bytes (full of
  `\x00`, later stripped) and the garbage is ingested as citable text. Worse, real
  cp1252 undefined bytes (`0x81`, `0x8D`, `0x8F`, `0x90`, `0x9D`) make the cp1252
  codec raise `UnicodeDecodeError`, which is *not* caught — the fallback itself
  explodes as a raw traceback.
- **Fix:** BOM-detect UTF-16/UTF-32 first; catch the cp1252 failure and raise a
  typed `UnsupportedEncodingError`; never rely on NUL-stripping to sanitize a
  binary misupload.

### C-15 — Text decode loads the entire (up to 1 GiB) file, multiple copies
- **Where:** `src/backend/ingest/extract.py:119-134`, `configs/lifecycle.toml:33`
- **Severity:** HIGH (memory)
- **What:** `read_stored` returns the whole file (cap 1 GiB by default), then
  `decode` plus `replace` materialize two more full copies. A 1 GiB text upload
  balloons to ~3-4 GiB RSS.
- **Fix:** stream/chunk the decode with an incremental decoder, and set a
  text-specific cap far below the archive cap.

### C-16 — PDF rasterization blows memory and leaks native handles
- **Where:** `src/backend/ingest/extract.py:406-446`
- **Severity:** HIGH
- **What:** up to 50 pages render at `scale=2.0`, all PNGs held in a list, then
  base64-encoded into one JSON body (another ~1.33x plus a full copy). `bitmap`
  is never closed (only `page.close()`), and `bitmap.to_pil()` yields a PIL image
  that is never closed — pypdfium2 bitmaps pin native memory.
- **Fix:** batch pages into bounded OCR calls, close bitmaps/images in `finally`,
  and drop the PIL round-trip.

### C-17 — Every PDF page is text-extracted twice (layout mode is expensive)
- **Where:** `src/backend/ingest/extract.py:344-352`
- **Severity:** MEDIUM
- **What:** `page.extract_text()` always runs, and `extract_text(extraction_mode=
  "layout")` runs again for every page with text.
- **Fix:** extract layout once and derive plain text from it, or invoke layout only
  when a cheap column heuristic fires.

### C-18 — No content sniffing: a `.txt` that is a PDF/zip decodes as garbage
- **Where:** `src/backend/ingest/extract.py:272-307`
- **Severity:** MEDIUM
- **What:** `UnsupportedSourceTypeError` only guards the declared mime. Verify
  magic bytes for PDF and reject NUL-dominant / high-entropy "text" before decode.
- **Fix:** magic-byte check at the boundary (also see S-xx on upload sniffing).

### C-19 — Chunk→locator mapping is O(chunks × locators)
- **Where:** `src/backend/ingest/chunking.py:62-66`
- **Severity:** MEDIUM
- **What:** each chunk scans every locator. A 500k-line text source yields
  thousands of chunks × thousands of locators.
- **Fix:** two-pointer walk (locators are emitted ascending by `start`) or bin
  locators.

### C-20 — Chunk boundary cuts mid-word on tabs/newlines
- **Where:** `src/backend/ingest/chunking.py:94-97`
- **Severity:** LOW
- **What:** only ASCII space is considered (`rfind(" ")`), so tab/newline-runs and
  long tokens (URLs, base64, CJK) are hard-cut mid-token, contradicting the module
  docstring.
- **Fix:** search all whitespace (`\s`), fall back to the next whitespace, else
  document the exception.

### C-21 — TOC extraction swallows errors silently
- **Where:** `src/backend/ingest/toc.py:85-88`, `:108-111`, `:93`
- **Severity:** MEDIUM
- **What:** a bookmark whose page lookup fails is dropped with no log; a page-text
  extraction failure returns `[]` so an entire page's headings vanish
  indistinguishably from "no structure"; `reader.outline` itself is unprotected
  and can fail the stage on a malformed PDF.
- **Fix:** log at warning with context, and wrap `reader.outline` in the same
  guard as per-item lookups.

### C-22 — `_description` uses `body.find(title)` after whitespace normalization
- **Where:** `src/backend/ingest/toc.py:51-58`
- **Severity:** LOW
- **What:** if the title's whitespace was collapsed, `find` misses and the
  description over-includes the title.
- **Fix:** match on the first N words of a normalized title/body pair.

### C-23 — Answer-cache fingerprint relies on `group_concat` ordering
- **Where:** `src/backend/common/queries/answer_cache.sql:7-18`
- **Severity:** MEDIUM
- **What:** SQLite does not guarantee `group_concat` order; the inner `ORDER BY`
  happens to influence it today but is not a contract. If it changes, cache keys
  mismatch and `drop_stale` churns.
- **Fix:** use an ordered aggregate (SQLite 3.44+ supports `ORDER BY` in the
  aggregate) or hash each row and concatenate sorted hashes in Python.

### C-24 — `normalise_question` only trims `[\s?!.]+$`
- **Where:** `src/backend/common/answer_cache.py:36-38`
- **Severity:** LOW
- **What:** trailing commas, ellipses, quotes, and leading punctuation are not
  normalized, so trivially-equal questions miss the cache.
- **Fix:** broaden the strip set symmetrically.

### C-25 — Eval harness can only ever match a chunk's *primary* locator
- **Where:** `src/backend/retrieval/evals.py:117-126`, `:234-237`; `queries/retrieval.sql:13,52,78`
- **Severity:** CRITICAL (for the eval's stated purpose)
- **What:** `_labels_for_candidates` resolves labels from `candidate.locator_id`,
  which is `chunks.locator_id` — the primary locator only. A chunk whose full span
  (`chunk_locators`) includes the expected page/section but whose primary locator
  differs scores as a miss. Since `_hit` requires all expected labels, eval cases
  targeting any non-primary locator are unfalsifiable misses. This corrupts
  `fused_recall` vs `seam_recall` and therefore decision 008's kill switch
  (`fusion_beats_best_single`).
- **Fix:** resolve the full locator set per candidate via `chunk_locators`, or
  require expected labels to be the primary locator and document it loudly.

### C-26 — Eval runs ~10 queries per case (N+1)
- **Where:** `src/backend/retrieval/evals.py:227-237`
- **Severity:** MEDIUM
- **What:** four seams + `concept_matches` + five `_labels_for_candidates` calls
  per case, serialized.
- **Fix:** batch label lookups across cases/seams.

### C-27 — Empty `expected_labels` counts as a miss
- **Where:** `src/backend/retrieval/evals.py:144-149`
- **Severity:** LOW
- **What:** a case with no expected labels is scored a failure rather than
  rejected/unresolved.
- **Fix:** reject/flag such cases at load.

### C-28 — `rerank.select_for_generation` length mismatch escapes the fails-open contract
- **Where:** `src/backend/retrieval/rerank.py:33-39`
- **Severity:** MEDIUM
- **What:** `provider.rerank_scores` is inside the try/except, but the
  `zip(..., strict=True)` and `sorted` are outside it. A reranker returning the
  wrong count raises `ValueError` into the request instead of falling back.
- **Fix:** validate `len(scores) == len(candidates)` inside the guarded block.

### C-29 — NaN reranker scores produce undefined ordering
- **Where:** `src/backend/retrieval/rerank.py:36-39`
- **Severity:** LOW
- **What:** `-item[0]` with NaN gives inconsistent sort keys.
- **Fix:** replace non-finite scores with `-inf`.

### C-30 — Retrieval trace records the embedding model, not the generation model
- **Where:** `src/backend/retrieval/trace.py:67`
- **Severity:** MEDIUM
- **What:** the trace's `model` field is set to `embedding_model`; every reader
  will interpret it as the answering model. The answering model lives in
  `usage_ledger`.
- **Fix:** rename to `embedding_model` in the payload/schema or store both.

### C-31 — Retrieval trace omits policy version and reranker identity
- **Where:** `src/backend/retrieval/trace.py:34-42`
- **Severity:** LOW
- **What:** an auditor cannot reproduce which `retrieval_config_version` or rerank
  cutoff produced the set, undermining golden rule 2.
- **Fix:** persist policy version and `generation_k`/reranker model.

### C-32 — `record_trace` default drops matched TOC entries
- **Where:** `src/backend/retrieval/trace.py:41`
- **Severity:** LOW
- **What:** `toc_entry_ids` defaults to `()`, and eval/artifact paths call
  `record_trace` without passing `result.matched_toc_entry_ids`, so traces claim
  no TOC entries matched.
- **Fix:** default to `result.matched_toc_entry_ids`.

### C-33 — Citation gate misses combined/range citations
- **Where:** `src/backend/tutor/workspace.py:29`, `:176-192`
- **Severity:** HIGH
- **What:** `INLINE_CITATION_RE = r"\[(\d+)\]"` requires `]` immediately after the
  digits, so `[1, 2]`, `[1,2]`, and `[1-3]` are never matched. A document with
  `sources=[1]` and body `... [9, 10]` passes the gate. This is exactly the form
  the codebase's own `content.CITATION_RE` supports.
- **Fix:** use one shared citation scanner (see C-38).

### C-34 — Citation gate skips quiz options and sheet cells
- **Where:** `src/backend/tutor/workspace.py:176-188`
- **Severity:** MEDIUM
- **What:** `WorkspaceSheet` scans only `sources`, never cell text; `WorkspaceQuiz`
  scans `prompt`/`explanation` but not `options`. Both render to the student, so
  out-of-range citations there are ungoverned. `prompts.toml` even instructs
  sheet cells to cite like `[1]`.
- **Fix:** scan options and every sheet cell, or remove the contradictory prompt.

### C-35 — No citation-range gate on prose answers
- **Where:** `src/backend/tutor/compose.py:339-345`, `:371-415`
- **Severity:** HIGH
- **What:** `workspace.py` gates only fenced workspace blocks. Plain and
  quote-mode answers can cite `[99]`, `[0]`, or fabricated numbers and are
  returned verbatim, contradicting the module docstring.
- **Fix:** after composing prose, validate every `[n]` against
  `len(candidates)`; withhold or strip invalid markers.

### C-36 — `quotes.anchor_citations` is a no-op when any citation exists
- **Where:** `src/backend/tutor/quotes.py:125-132`
- **Severity:** HIGH
- **What:** it returns early if `_CITATION_RE.search(answer)` is truthy, so an
  answer with *any* `[n]` (including fabricated ones) is left unanchored and
  unvalidated.
- **Fix:** always reconcile markers against `verified` sources; strip markers
  with no verified quote.

### C-37 — Fragile JSON extraction from model output
- **Where:** `src/backend/tutor/compose.py:288-309`
- **Severity:** MEDIUM
- **What:** `_JSON_FENCE_RE` is greedy across the whole text, and the brace
  fallback uses `text.find("{")`/`rfind("}")`. With multiple objects, echoed
  course snippets, or braces inside strings, this returns the wrong object or
  `None` nondeterministically.
- **Fix:** brace-depth scanner that respects string state.

### C-38 — Five divergent citation dialects
- **Where:** `src/backend/artifacts/content.py:59-63`, `tutor/workspace.py:29`, `evals/answer.py:217-226`, `tutor/quotes.py:117`, `tutor/chat.py:72-76`
- **Severity:** MEDIUM
- **What:** `content.CITATION_RE`, `workspace.INLINE_CITATION_RE`,
  `evals.answer.CITATION_RE`, `quotes._CITATION_RE`, and `chat._CITATIONS` all
  implement incompatible parsing. This is the root cause of C-33, C-35, and the
  eval citation-validity bug.
- **Fix:** one parser in `content.py`, imported everywhere.

### C-39 — `content.cited_numbers` treats array indexing in code as citations
- **Where:** `src/backend/artifacts/content.py:170-203`
- **Severity:** HIGH
- **What:** it recurses into every string, so `CodeContent.code` containing
  `arr[0]`, `x[12]` yields citations `0`/`12`. `_checked` then rejects the
  artifact, and `compact`/`renumber` *rewrite subscripts* (`arr[5]` → `arr[3]`),
  corrupting code. `workspace.py` explicitly avoids scanning code; `content.py`
  does not.
- **Fix:** make citation extraction field-aware (skip `code`/`html`).

### C-40 — `_ESCAPED_CITATION` unescape applies inside code spans/blocks
- **Where:** `src/backend/artifacts/content.py:59-63`
- **Severity:** MEDIUM
- **What:** `\[1\]` inside a fenced code sample is rewritten to `[1]`, changing
  literal text and then feeding the citation scanner.
- **Fix:** limit the substitution to non-code text.

### C-41 — `int(n)` in `_walk` can raise a bare `ValueError`
- **Where:** `src/backend/artifacts/content.py:181-183`
- **Severity:** LOW
- **What:** a non-numeric `sources` entry escapes the `except UnknownCitationError`
  handlers in `edit.py`.
- **Fix:** coerce/validate with a clear error.

### C-42 — Whole-artifact edit 500s when the artifact cites > `MAX_MATERIAL` chunks
- **Where:** `src/backend/artifacts/edit.py:450-456`, `:371-373`, `:503`
- **Severity:** HIGH
- **What:** `_material` truncates `chunk_ids` to 8, so `to_material` omits higher
  cited numbers, and `artifact_content.renumber` raises `UnknownCitationError`
  **outside** the try block. The API only catches `EditFailedError`/
  `EmptyModelError`/`ProviderUnavailable`/`BudgetExceeded`, so a doc citing ≥9
  sources returns 500.
- **Fix:** raise the cap, catch `UnknownCitationError` and surface
  `EditFailedError`, or include all cited chunks.

### C-43 — Edit trace records stale layer provenance
- **Where:** `src/backend/artifacts/edit.py:519-526`
- **Severity:** LOW
- **What:** candidates are filtered to `material.chunk_ids` but
  `layer_contribution` is copied unchanged.
- **Fix:** recompute or drop the counts.

### C-44 — `_combine` silently drops empty placeholder slides
- **Where:** `src/backend/artifacts/edit.py:413-420`
- **Severity:** LOW
- **What:** `if s.get("title") or s.get("body")` loses intentional blank slides on
  any add.
- **Fix:** preserve them.

### C-45 — `attribution` substring matching causes false "echo" deletions
- **Where:** `src/backend/artifacts/attribution.py:73-75`
- **Severity:** LOW
- **What:** `plain in p` matches "the cat" inside "the category", deleting the
  model's output as "copied".
- **Fix:** match on word-token subsequences.

### C-46 — `attribution` fence toggle is confused by nested/indented fences
- **Where:** `src/backend/artifacts/attribution.py:117-118`
- **Severity:** LOW
- **What:** `in_code` flips on any stripped line starting with a fence, so a code
  line that looks like a fence mis-toggles.
- **Fix:** reuse `edit._fenced_spans`.

### C-47 — `course_archive.export_course` loads each whole source into memory
- **Where:** `src/backend/common/course_archive.py:106-172`
- **Severity:** HIGH (memory)
- **What:** `storage.read_stored` returns the full (up to 1 GiB) payload, then
  `archive.writestr` may copy it again.
- **Fix:** stream via `archive.open(path, "w")` + `shutil.copyfileobj`, or cap
  export source size.

### C-48 — Import total-size cap trusts attacker-declared `ZipInfo.file_size`
- **Where:** `src/backend/common/course_archive.py:234-264`
- **Severity:** MEDIUM (security)
- **What:** a malicious archive can under-declare member sizes to bypass the total
  limit; only per-file is enforced later by `stream_to_temp`. The manifest read
  (`:175-194`) is also unbounded relative to its declared size.
- **Fix:** enforce totals against actual bytes read, and cap the manifest read.

### C-49 — `_unique_path` TOCTOU
- **Where:** `src/backend/common/course_archive.py:97-103`
- **Severity:** LOW
- **What:** existence check then write; two concurrent exports can pick the same
  path and clobber.
- **Fix:** `O_EXCL`/`os.open` with retry.

### C-50 — Failed import can leave a course/keepsake behind
- **Where:** `src/backend/common/course_archive.py:284-339`
- **Severity:** MEDIUM
- **What:** the import creates the course before validating every member; `_discard`
  itself calls `move_to_trash` → `course_memory.refresh` → `purge_course`, any of
  which can fail while the original error propagates. The "failed import leaves
  nothing behind" docstring is not guaranteed.
- **Fix:** wrap `_discard` in its own try/log.

### C-51 — `ArchiveNotebook` export trace order is nondeterministic
- **Where:** `src/backend/common/archive_notebook.py:149-171`
- **Severity:** MEDIUM
- **What:** iterates a `set` of trace ids, so the serialized notebook JSON — and
  therefore `notebook_sha256` — varies run to run for the same course.
- **Fix:** sort the trace ids.

### C-52 — Notebook import creates dangling chunk references
- **Where:** `src/backend/common/archive_notebook.py:233-251`
- **Severity:** MEDIUM
- **What:** citations whose `source_id` is absent are skipped, but their chunk ids
  remain in `chunk_map` and traces/artifacts still reference them, so those
  citations resolve to nothing.
- **Fix:** drop referenced ids from traces/artifact sources or fail the import.

### C-53 — Notebook export N+1
- **Where:** `src/backend/common/archive_notebook.py:93-189`
- **Severity:** MEDIUM
- **What:** one query per conversation (messages), per artifact (versions), per
  trace.
- **Fix:** batch with `WHERE ... IN (...)`.

### C-54 — `json.dumps` without `ensure_ascii=False` in the notebook importer
- **Where:** `src/backend/common/archive_notebook.py:310,318,319,333`
- **Severity:** LOW
- **What:** non-ASCII content is escaped differently than the export side,
  bloating archives and diverging bytes.
- **Fix:** be consistent.

### C-55 — `_remap_payload` only remaps top-level ids
- **Where:** `src/backend/common/archive_notebook.py:192-210`
- **Severity:** LOW
- **What:** nested payload shapes (per-workspace-item citations) keep old ids.
- **Fix:** recurse, or document.

### C-56 — `purge_course` refreshes the keepsake before validating the course is trashed
- **Where:** `src/backend/common/courses_repo.py:126-147`
- **Severity:** MEDIUM
- **What:** `course_memory.refresh` runs unconditionally at line 132;
  `purge_trashed_course` then returns no row for an active course and the function
  returns `False`, but the memory node was already rewritten.
- **Fix:** refresh only after confirming the delete.

### C-57 — `sweep_storage_orphans` unguarded `stat`/`iterdir` races abort the sweep
- **Where:** `src/backend/common/courses_repo.py:194-197`, `:235-236`
- **Severity:** MEDIUM
- **What:** a concurrent removal raises `FileNotFoundError`/`OSError` in the
  predicate, which the surrounding try does not cover.
- **Fix:** per-entry try/except, log-and-continue.

### C-58 — Orphan sweep reads every live course directory + all source ids each pass
- **Where:** `src/backend/common/courses_repo.py:210-215`
- **Severity:** LOW (perf)
- **What:** full-directory scan + `all_source_ids` full-table read, hourly.
- **Fix:** bound by course, query lazily.

### C-59 — `assert row is not None` used as control flow across repos
- **Where:** `src/backend/common/courses_repo.py:44-51`, `sources_repo.py:123`, `trace.py:70`, `api/courses.py:53`, `api/conversations.py:219,291`, `orchestrator.py:167,188,273`
- **Severity:** LOW
- **What:** stripped under `python -O`, turning missing rows into `AttributeError`
  / `TypeError` or silently passing guards.
- **Fix:** explicit exceptions.

### C-60 — `course_memory` budget accounting undercounts separators
- **Where:** `src/backend/common/course_memory.py:113-144`, `:84-87`
- **Severity:** MEDIUM
- **What:** separators are 2 chars but accounting adds `spent + 1`; `_fit_lines`'s
  single-line branch omits the `\n`. The assembled "bounded" summary can exceed
  the budget. With a tiny budget, `max(remaining // 3, len(header))` forces
  sections past a depleted `remaining`, driving it negative.
- **Fix:** count the exact emitted bytes; refuse to force a header when
  `remaining <= 0`.

### C-61 — `course_memory` reads lifecycle policy twice per refresh, dead vars
- **Where:** `src/backend/common/course_memory.py:47,197`, `:110-111`, `:43`
- **Severity:** NIT
- **What:** `load_lifecycle_policy()` twice; `used` computed never read;
  `[truncated at token budget]` marker defined never used.
- **Fix:** load once, delete dead code.

### C-62 — `usage_repo.set_monthly_budget` accepts zero/negative
- **Where:** `src/backend/common/usage_repo.py:91-95`
- **Severity:** MEDIUM
- **What:** `0` budget blocks all cloud calls; negative always blocks.
- **Fix:** `ge=0`.

### C-63 — Cloud budget check-then-act race (unbounded overshoot)
- **Where:** `src/backend/common/provider.py:127-128`, `usage_repo.py:98-105`
- **Severity:** MEDIUM
- **What:** the budget is read on one connection, the call happens, the ledger is
  written after. Concurrent calls blow past the monthly budget with no bound.
  Documented as "never cut off in flight", but the concurrency window is unbounded.
- **Fix:** reservation row or a post-call bound.

### C-64 — Cloud token counting misclassifies the local `environment` provider
- **Where:** `src/backend/common/usage_repo.py:73-78`, `queries/usage.sql:19-24`
- **Severity:** LOW
- **What:** `provider <> 'local'` counts `'environment'` loopback calls as cloud.
- **Fix:** record/read an explicit `is_local` flag.

### C-65 — `provider.generate` drops empty-output usage from the ledger
- **Where:** `src/backend/common/provider.py:126-149`
- **Severity:** HIGH
- **What:** whitespace-only output raises `EmptyModelError` *before*
  `usage_repo.record`, so the provider consumed tokens but the ledger
  under-counts, letting a broken endpoint burn quota invisibly.
- **Fix:** record, then validate output.

### C-66 — Connections read-modify-write with no transaction (lost update)
- **Where:** `src/backend/common/providers.py:179-189`, `:205-231`, `:234-264`
- **Severity:** HIGH
- **What:** `_saved_connections()` (SELECT) then `_store_connections()`
  (INSERT/UPSERT) are separate connections; concurrent add/update/remove lose one
  update.
- **Fix:** one `with connection()` transaction around read+write, or an atomic
  JSON-array update.

### C-67 — `remove_connection` leaves a dangling saved choice on partial failure
- **Where:** `src/backend/common/providers.py:275-279`
- **Severity:** LOW
- **What:** three more round-trips after mutating settings; a mid-loop failure
  leaves the connection gone but a choice pointing at it.
- **Fix:** make it one transaction.

### C-68 — `providers.resolve` silently falls back to the environment endpoint
- **Where:** `src/backend/common/providers.py:376-387`
- **Severity:** MEDIUM
- **What:** a saved interactive/background choice that resolves to `None`
  (missing key / bad URL) quietly routes course text to `LLM_BASE_URL`, which may
  be remote. The user picked an endpoint on purpose.
- **Fix:** fail loudly when a saved choice cannot resolve.

### C-69 — Local-detection only recognizes `http://127.0.0.1` and `http://localhost`
- **Where:** `src/backend/common/providers.py:359-373`
- **Severity:** LOW
- **What:** `http://[::1]`, `https://localhost`, and LAN self-hosted servers
  (`192.168.*`) are treated as cloud (budget counted, disclosure shown).
- **Fix:** parse the host and classify loopback/LAN explicitly.

### C-70 — `conversations_repo.next_seq` is a non-atomic read
- **Where:** `src/backend/common/queries/conversations.sql:60-62`, `conversations_repo.py:191-195`
- **Severity:** HIGH
- **What:** `MAX(seq)+1` runs before the connection's IMMEDIATE transaction is
  established (which starts on first write). Two concurrent turns can read the
  same `MAX(seq)` and the second gets a `UNIQUE(conversation_id, seq)`
  `IntegrityError`.
- **Fix:** `BEGIN IMMEDIATE` before reading, or atomic
  `INSERT ... SELECT COALESCE(MAX(seq),0)+1`.

### C-71 — `add_turn` re-reads all messages and assumes exactly two new rows
- **Where:** `src/backend/common/conversations_repo.py:218-219`
- **Severity:** MEDIUM (perf/correctness)
- **What:** O(n) rows per turn; `stored[0], stored[1]` mis-indexes if a duplicate
  slips in.
- **Fix:** return the inserted rows directly via `RETURNING`.

### C-72 — `set_summary` can overwrite a better summary with an empty one
- **Where:** `src/backend/common/conversations_repo.py:222-233`
- **Severity:** LOW
- **What:** monotonic by `summary_through`, but an advancing empty summary
  replaces a good earlier one.
- **Fix:** reject empty text.

### C-73 — `chat.pending_summary` can permanently omit a trailing turn
- **Where:** `src/backend/tutor/chat.py:104-117`
- **Severity:** MEDIUM
- **What:** an odd number of messages below the recent window never summarizes
  (`len(older) < 2`), so a trailing user message can be absent from the summary
  forever; empty model output also silently skips forever.
- **Fix:** include the remainder or track summarized seq explicitly.

### C-74 — `chat._excerpt` can exceed the limit and mangles long tokens
- **Where:** `src/backend/tutor/chat.py:72-76`
- **Severity:** LOW
- **What:** no space in the prefix → `rsplit` returns the whole prefix (601 chars);
  `_CITATIONS`'s `\s*` prefix can delete word-separating spaces.
- **Fix:** hard slice fallback and non-consuming citation strip.

### C-75 — `chat` rolling summary truncates mid-word
- **Where:** `src/backend/tutor/chat.py:136`
- **Severity:** LOW
- **What:** `[:SUMMARY_MAX_CHARS]` can end mid-token; the stored summary is
  presented as authoritative.
- **Fix:** truncate at a word boundary.

### C-76 — Office graded-work classifier false-positives on document text
- **Where:** `src/backend/tutor/office.py:115-122`, `:141-145`
- **Severity:** HIGH
- **What:** `is_graded_request` concatenates `instruction\ncontext` and runs a
  loose regex whose `[^.]{0,40}` windows cross newlines, matching ordinary prose
  ("The answer to the exam is..."). The whole 8 KB selection is probed, so the
  pane can refuse legitimate explain/summarize requests on innocent slide text.
- **Fix:** scan only `instruction`, anchor to imperative/second-person forms, and
  exclude already-refused intents.

### C-77 — Two divergent graded-work classifiers
- **Where:** `src/backend/tutor/office.py:115-122` vs `src/backend/tutor/compose.py:54-62`
- **Severity:** MEDIUM
- **What:** `_GRADED` and `_GRADED_WORK` encode the same policy differently; the
  tutor and Office pane will disagree about the same request.
- **Fix:** consolidate into one classifier.

### C-78 — Office answers skip reranking, diverging from the tutor
- **Where:** `src/backend/tutor/office.py:203-215`
- **Severity:** MEDIUM
- **What:** the top `MATERIAL_LIMIT` fused candidates are used directly; the
  built-in tutor calls `rerank.select_for_generation`.
- **Fix:** pass through `rerank.select_for_generation`.

### C-79 — Office `_context` computed twice; retrieval/embedding strings differ
- **Where:** `src/backend/tutor/office.py:132-138,202,221`; `api/office.py:247-249`
- **Severity:** LOW
- **What:** `_context(context)` runs twice, and the embedded text
  (`context[:600]` whitespace-collapsed) differs from the raw retrieval string.
- **Fix:** compute the cleaned context once, derive both from it.

### C-80 — Office read path holds a SQLite connection across a network OCR call
- **Where:** `src/backend/api/office.py:342-343`, `src/backend/office_reader/screens.py:46`
- **Severity:** MEDIUM
- **What:** `read_screens` discards `conn`, yet the caller wraps a minutes-long
  model call in `with connection()`, pinning the DB.
- **Fix:** drop the connection wrapper and the dead parameter.

### C-81 — `office_reader.package` sorts slide/notes parts lexicographically
- **Where:** `src/backend/office_reader/package.py:141-145`, `:157-161`, `:94-102`
- **Severity:** HIGH
- **What:** `sorted` yields `slide1, slide10, slide11, ..., slide2`, so for decks
  with ≥10 slides the labels and unit order are wrong. Worksheet order should come
  from `xl/workbook.xml`, not filenames.
- **Fix:** sort by extracted integer index; read workbook sheet order.

### C-82 — DOCX reader silently misses large classes of content
- **Where:** `src/backend/office_reader/package.py:54-82`
- **Severity:** MEDIUM
- **What:** only direct children of `w:body` are walked, so paragraphs inside
  `w:sdt`/content controls and smart tags, headers/footers, footnotes/endnotes,
  comments, and text boxes are dropped with no warning.
- **Fix:** walk descendant `w:p`/`w:tbl` in document order, or warn.

### C-83 — Negative shared-string index accepted
- **Where:** `src/backend/office_reader/package.py:113-116`
- **Severity:** LOW
- **What:** `shared[-1]` returns the wrong string for a malformed cell.
- **Fix:** reject `< 0`.

### C-84 — Formula count misses `<f t="shared">`, re-reads every sheet
- **Where:** `src/backend/office_reader/package.py:131-135`
- **Severity:** LOW
- **What:** counts only literal `b"<f>"` and re-decompresses each part.
- **Fix:** parse elements from already-read bytes.

### C-85 — `office_reader.merge` is O(units² · text-length)
- **Where:** `src/backend/office_reader/merge.py:86-99`
- **Severity:** MEDIUM
- **What:** for every unit it loops all merged keys with substring `in`; large
  docs make this quadratic. When a fuller unit replaces one, `merged_keys` is not
  updated (stale key).
- **Fix:** index by normalized first-token shingles; update the key on replace;
  require token-boundary containment.

### C-86 — `merge` counts same-method duplicates as cross-method agreement
- **Where:** `src/backend/office_reader/merge.py:83-100`
- **Severity:** LOW
- **What:** a method matching its own duplicate inflates `matched`.
- **Fix:** exclude same-method matches from the agreement metric.

### C-87 — `office_reader.package` zip-bomb: decompression unbounded
- **Where:** `src/backend/office_reader/package.py:186-190`, `:30`
- **Severity:** HIGH
- **What:** `_MAX_PART_BYTES` checks only the *compressed* `data` size;
  `ZipFile.read` then loads each part fully decompressed. A 40 MB `.docx` can
  inflate `sharedStrings.xml` to gigabytes.
- **Fix:** check `ZipInfo.file_size` against a cap, read in bounded chunks, reject
  absurd ratios, cap total decompressed bytes.

### C-88 — `package.read_package` does not catch encrypted-entry errors
- **Where:** `src/backend/office_reader/package.py:57,89,103,150,163`
- **Severity:** LOW
- **What:** `archive.read` raises `RuntimeError` for encrypted members, surfacing
  as 500 rather than `UnreadablePackageError`.
- **Fix:** catch broadly and translate.

### C-89 — `xml.etree.ElementTree` used on untrusted Office files
- **Where:** `src/backend/office_reader/package.py:37-43`
- **Severity:** LOW
- **Fix:** use `defusedxml.ElementTree`.

### C-90 — `_read_manifest` / `read_package` accept declared-size lies
- **Where:** `src/backend/office_reader/package.py:30`, `api/office.py:285-291`
- **Severity:** MEDIUM
- **What:** base64 is fully decoded before the size cap is checked.
- **Fix:** cap before decode (see S-xx).

### C-91 — `data.py` reveals/counts with TOCTOU and silent OSError swallow
- **Where:** `src/backend/api/data.py:57-67`, `:144-161`
- **Severity:** LOW
- **What:** `_tree_bytes` recursively walks the storage/models/runtime roots on
  every call and swallows `OSError`, so totals can be silently wrong; `reveal`
  checks `exists()` then opens.
- **Fix:** cache with a TTL; handle errors explicitly.

### C-92 — `data.py` `explorer /select,<path>` misparses comma-containing paths
- **Where:** `src/backend/api/data.py:167`
- **Severity:** LOW
- **What:** the `explorer` argument itself is comma-delimited.
- **Fix:** quote/escape, or use `SHOpenFolderAndSelectItems`.

### C-93 — `conversations.list_messages` returns unbounded history
- **Where:** `src/backend/api/conversations.py:170-178`
- **Severity:** MEDIUM
- **What:** every message row in one response; long chats produce unbounded
  payloads.
- **Fix:** paginate (`limit`/`before_seq`).

### C-94 — `AnswerView.model_validate` on legacy stored payloads 500s the whole thread
- **Where:** `src/backend/api/conversations.py:128-129`
- **Severity:** MEDIUM
- **What:** any stored assistant payload missing a field raises `ValidationError`
  for the entire conversation.
- **Fix:** tolerate/repair or degrade to `answer=None`.

### C-95 — Retired artifact kinds crash single-artifact routes
- **Where:** `src/backend/api/artifacts.py:169`, `:299-301`, `:304`, `:336`, `:386`
- **Severity:** MEDIUM
- **What:** `list_artifacts` filters retired `word`/`excel`/`powerpoint` rows, but
  `get`/`save`/`rename`/`restore` build `ArtifactView` and raise `ValidationError`
  → 500.
- **Fix:** `_require_artifact` 404s unknown kinds.

### C-96 — `restore_version` can raise uncaught validation errors
- **Where:** `src/backend/api/artifacts.py:402`
- **Severity:** LOW
- **What:** older content no longer valid, or `version()` returned `{}`.
- **Fix:** wrap and return 422.

### C-97 — Artifact `sources` lists are not deduped before persisting
- **Where:** `src/backend/api/artifacts.py:90,309`, `:225`
- **Severity:** LOW
- **What:** duplicates stored, so `/citations` repeats chunk ids.
- **Fix:** dedupe on save/create.

### C-98 — `author:"model"` is client-assertable
- **Where:** `src/backend/api/artifacts.py:91`
- **Severity:** LOW
- **What:** any save can claim model authorship, weakening auditable provenance.
- **Fix:** derive `author` server-side.

### C-99 — `EmptyModelError` unhandled → 500 across tutor/conversations/office
- **Where:** `src/backend/api/tutor.py:108-113`, `conversations.py:287-290`, `office.py:263-270`, `:344`
- **Severity:** MEDIUM
- **What:** `provider.EmptyModelError` is a sibling of `ProviderUnavailableError`,
  not a subclass, and is not caught. `artifacts.py:483-488` *does* catch it, so
  behavior is inconsistent.
- **Fix:** catch it and return 502/503 consistently.

### C-100 — Malformed stored trace id → 500
- **Where:** `src/backend/api/tutor.py:136`
- **Severity:** LOW
- **Fix:** validate/skip, return 404/422.

---

## 2. Security

### S-01 — **CRITICAL: arbitrary file write via artifact export path**
- **Where:** `src/backend/api/artifacts.py:508-531`, `artifacts/export.py:73-79,404-426`
- **Severity:** CRITICAL
- **What:** the client supplies an absolute filesystem `path`. The only check is
  `target.parent.is_dir()`; then `target.write_bytes(data)` writes anywhere the
  process can write (as long as the extension matches or is appended). This
  contradicts the care taken in `data.reveal` (`data.py:152-161`).
- **Fix:** resolve `payload.path` and require it under the export dir (or treat it
  as a bare filename), and refuse to overwrite.

### S-02 — Exported chart HTML sanitization is regex-based and bypassable (XSS)
- **Where:** `src/backend/artifacts/export.py:54-59`, `:391-398`
- **Severity:** HIGH
- **What:** `_SCRIPT` misses `<script src>`, unclosed `<script>`, SVG `<script>`;
  `_HANDLER` misses `<svg/onload=>` and entity-encoded handlers; `_JS_URL` misses
  `data:text/html`, `vbscript:`, `java&#9;script:`. `<iframe srcdoc>`,
  `<object>`, `<embed>`, `<meta http-equiv=refresh>` pass untouched. The `.html`
  export opens in a browser where nothing else sanitizes it.
- **Fix:** use a real HTML sanitizer or emit sanitized static SVG.

### S-03 — API auth fails open when no token is configured
- **Where:** `src/backend/api/deps.py:21-23`
- **Severity:** HIGH
- **What:** empty `api_token` returns success; the entire API is unauthenticated.
  This is the only guard against DNS-rebinding/CSRF. If the shell ever fails to
  set the token, the API silently opens with no warning.
- **Fix:** in production refuse to serve without a token, or bind loopback-only
  and log loudly.

### S-04 — Office bridge fails open by default
- **Where:** `src/backend/api/office.py:63-65`, `common/config.py:54`
- **Severity:** HIGH
- **What:** `office_bridge_token` defaults to `""`; `require_office_token` returns
  immediately. Combined with the fixed loopback HTTPS port, any local process can
  spend cloud tokens and read course-grounded answers via `/assist` and `/read`.
- **Fix:** generate and require a per-install token by default.

### S-05 — `compare_digest` on non-ASCII header raises `TypeError` → 500, not 401
- **Where:** `src/backend/api/deps.py:24`, `api/office.py:66`
- **Severity:** MEDIUM
- **What:** header values are decoded latin-1; a byte >127 yields a non-ASCII
  `str`, which `hmac.compare_digest` rejects.
- **Fix:** compare bytes (`encode("utf-8","surrogateescape")`) or catch
  `TypeError` → 401.

### S-06 — Unauthenticated FastAPI docs/openapi on the mounted `/api` app
- **Where:** `src/backend/main.py:57-61`, `:116`
- **Severity:** HIGH
- **What:** `create_app` disables docs on the parent, but `create_api()` leaves
  defaults on, and app-level `dependencies=[...]` do not cover the auto-generated
  `/docs`, `/redoc`, `/openapi.json` routes. `/api/openapi.json` discloses the
  whole API surface without the token.
- **Fix:** pass `docs_url=None, redoc_url=None, openapi_url=None` to `create_api`.

### S-07 — SSRF via connection test
- **Where:** `src/backend/api/settings.py:295-325`, `:328-333`, `:340-357`
- **Severity:** MEDIUM
- **What:** `_list_models` GETs `<base_url>/models` with a client-controlled
  stored value; any authenticated caller can make the backend hit arbitrary
  hosts/ports.
- **Fix:** validate scheme/host, or accept the risk explicitly.

### S-08 — Arbitrary file launch via Office "open document"
- **Where:** `src/backend/api/office_setup.py:99-103`, `office_addin/service.py:192-207`
- **Severity:** MEDIUM
- **What:** a client-supplied path is `is_file()`-checked then launched with a
  COM/OS Office app — including `.docm` (macro-enabled).
- **Fix:** restrict to data/export dirs or an OS-dialog nonce.

### S-09 — Arbitrary local GGUF path hashed/registered with no cap
- **Where:** `src/backend/api/runtime.py:227`, `runtime/user_models.py:192-213`
- **Severity:** MEDIUM
- **What:** any `.gguf` path is accepted; a multi-GB synchronous hash runs on the
  request thread (DoS) and lets a caller probe arbitrary paths.
- **Fix:** cap size and restrict to known model dirs.

### S-10 — `AddModelRequest` allows ambiguous / injected URL components
- **Where:** `src/backend/api/runtime.py:88-96`, `runtime/config.py:56`
- **Severity:** MEDIUM
- **What:** `url`/`file`/`path` can all be set (silent precedence); `download_url`
  interpolates unquoted `repo`/`revision`/`file`, so a pasted link can inject
  path/query segments.
- **Fix:** `@model_validator` enforcing exactly one source; `urllib.parse.quote`
  each component.

### S-11 — Model download destination keyed only by basename → collisions
- **Where:** `src/backend/runtime/model_store.py:70,161,179`
- **Severity:** HIGH
- **What:** two catalog/user models sharing e.g. `model-Q4_K_M.gguf` share `.part`
  and final paths; `delete_model` deletes the other's file, and the
  `st_size` short-circuit can return the wrong model as verified.
- **Fix:** namespace by sha256 (or sanitized repo + name).

### S-12 — Hash verification bypass for an already-present final file
- **Where:** `src/backend/runtime/downloads.py:49-50`
- **Severity:** HIGH
- **What:** `if dest.exists() and size matches: return` never re-hashes; any
  same-size substitution is trusted forever.
- **Fix:** verify a remembered hash, or hash before returning.

### S-13 — ZIP extraction uses `extractall` without `filter`
- **Where:** `src/backend/runtime/server.py:79-84`
- **Severity:** LOW
- **What:** archive is sha256-pinned, but use `filter="data"` for symmetry with the
  tar path.
- **Fix:** explicit safe extraction.

### S-14 — Local cert private key written world-readable (POSIX)
- **Where:** `src/backend/office_addin/certs.py:115-121`
- **Severity:** MEDIUM
- **What:** no explicit permissions; umask typically 0644. The localhost TLS key
  is readable by any local user.
- **Fix:** `os.open(..., 0o600)` / `os.chmod(0o600)`.

### S-15 — Local TLS key not matched to cert; `not_valid_before` unchecked
- **Where:** `src/backend/office_addin/certs.py:130-142`
- **Severity:** LOW
- **What:** a swapped key file is reported current; a clock skewed before issuance
  passes.
- **Fix:** compare public keys; check `not_valid_before_utc`.

### S-16 — Cert issuance is not atomic
- **Where:** `src/backend/office_addin/certs.py:115-126`
- **Severity:** LOW
- **What:** an interrupt leaves mismatched key+cert.
- **Fix:** temp files + `os.replace`, with a lock.

### S-17 — Leaf cert has no `KeyUsage` extension
- **Where:** `src/backend/office_addin/certs.py:92-106`
- **Severity:** LOW
- **Fix:** add `digitalSignature`/`keyAgreement`.

### S-18 — API token passed via child environment, readable by same-user processes
- **Where:** `src/frontend/src-tauri/src/backend.rs:54-58,193-197`
- **Severity:** MEDIUM
- **What:** same-user processes can read another process's environment/PEB on
  Windows and `/proc/<pid>/environ` elsewhere. The threat model explicitly
  includes local same-user programs.
- **Fix:** pass the secret over the already-piped stdin handshake, or document the
  limitation.

### S-19 — Token kept in a cloned, non-zeroized `String`
- **Where:** `src/frontend/src-tauri/src/backend.rs:31-36,98,193-197`
- **Severity:** LOW
- **Fix:** `secrecy::SecretString`/zeroize; avoid `Clone` on the token field.

### S-20 — Office bridge / pane static assets served with `no-store`
- **Where:** `src/backend/office_addin/app.py:30-38`
- **Severity:** NIT
- **Fix:** scope the header to HTML/bridge responses.

### S-21 — `office_addin.windows.installed_apps` misses 32-bit Office
- **Where:** `src/backend/office_addin/windows.py:40-55`
- **Severity:** MEDIUM
- **What:** doesn't check `WOW6432Node\...\App Paths`, so 32-bit Office is
  reported absent.
- **Fix:** enumerate both hives.

### S-22 — `untrust` ignores failure silently
- **Where:** `src/backend/office_addin/windows.py:82-91`
- **Severity:** LOW
- **What:** a thumbprint mismatch leaves the CA trusted while the caller believes
  it was removed. Return/log success.

### S-23 — Office host shutdown may leave the port held → self-inflicted `PortInUseError`
- **Where:** `src/backend/office_addin/host.py:67-72`
- **Severity:** MEDIUM
- **What:** drops references after a 5s join even if uvicorn is alive.
- **Fix:** wait longer, track/close sockets, or fail loudly.

### S-24 — IPv6 bind failure silently swallowed
- **Where:** `src/backend/office_addin/host.py:84-85`
- **Severity:** LOW
- **Fix:** log at warning.

### S-25 — Manifest URL/template substitution is blind; write not atomic
- **Where:** `src/backend/office_addin/manifest.py:45-58`
- **Severity:** LOW
- **What:** a mismatched `TEMPLATE_ORIGIN` no-ops silently; an interrupted write
  leaves a truncated manifest registered with Office.
- **Fix:** validate the replacement occurred; atomic write.

### S-26 — `office_version` can fail to increase
- **Where:** `src/backend/office_addin/manifest.py:36-41`
- **Severity:** LOW
- **What:** `"1"` and `"1.0"` both map to `1.1.0.0`, so Office won't reload a
  changed add-in.
- **Fix:** pad deterministically and assert growth.

### S-27 — `manifest.render` replaces the first `<Version>` blindly
- **Where:** `src/backend/office_addin/manifest.py:46-51`
- **Severity:** LOW
- **Fix:** parse and set the node explicitly.

### S-28 — `office_addin.service.connect` reports success before the host is ready
- **Where:** `src/backend/office_addin/service.py:167-175`, `host.py:41-61`
- **Severity:** MEDIUM
- **What:** `AddinHost.start` returns after `thread.start()`; a cert/key load
  failure inside the thread is swallowed, `CONNECTED_SETTING=True` is stored, and
  only a later `status()` reveals the problem.
- **Fix:** wait for `server.started`, fail `connect` if it never comes up.

### S-29 — `connect` has no rollback on partial failure
- **Where:** `src/backend/office_addin/service.py:117-129`
- **Severity:** LOW
- **What:** failure after `trust` leaves the CA trusted while `connected` is false.
- **Fix:** track and undo.

### S-30 — `status()` does expensive registry/store/file reads on every poll and can 500
- **Where:** `src/backend/office_addin/service.py:73-104`, `windows.py:58-65,117-127`
- **Severity:** LOW
- **What:** reads `ca_der`, enumerates ROOT, the registry, and `registered_manifest`
  each poll; races a concurrent `disconnect` (`FileNotFoundError` → 500);
  `is_trusted` rescans the whole store.
- **Fix:** cache, broaden OSError handling.

### S-31 — `office_reader`/`package` `_MAX_PART_BYTES` name implies whole-file
- **Where:** `src/backend/office_reader/package.py:30,186`
- **Severity:** NIT
- **Fix:** rename/clarify.

### S-32 — Prompt/implementation mismatch: sheet citations instructed but not gated
- **Where:** `configs/prompts.toml:86-94`, `tutor/workspace.py:176-178`
- **Severity:** MEDIUM
- **Fix:** enforce in the gate or remove the instruction.

---

## 3. Concurrency, lifecycle, resources

### X-01 — Tauri `watch_startup` can deadlock on a full stdout pipe
- **Where:** `src/frontend/src-tauri/src/backend.rs:199-247`
- **Severity:** HIGH
- **What:** after finding `STACKS_PORT=`, it calls `wait_healthy`, which blocks up
  to 180s; the "keep draining stdout" loop only runs afterward. Any backend
  stdout between announcement and readiness (progress prints) accumulates against
  the ~64 KiB pipe buffer; once full the backend blocks in `write`, never becomes
  healthy, and startup reports a false failure.
- **Fix:** drain stdout concurrently with health polling (separate drainer thread
  that parses only the first port line).

### X-02 — Tauri `shutdown()` blocks the event-loop thread up to 20s
- **Where:** `src/frontend/src-tauri/src/backend.rs:105-128`, `lib.rs:44-49`
- **Severity:** HIGH
- **What:** busy-polls `try_wait` with 100ms sleeps on `RunEvent::Exit`, freezing
  quit for up to 20s.
- **Fix:** move the wait to a worker thread, or bound the sync wait to a few
  hundred ms and let the process die asynchronously.

### X-03 — No `Drop`/kill-on-drop; no job object/process group on Unix
- **Where:** `src/frontend/src-tauri/src/backend.rs:105-128`, `:66-71`; `Cargo.toml:30`
- **Severity:** HIGH
- **What:** every non-`RunEvent::Exit` termination (setup panic, `exit()`
  elsewhere) leaves the child relying on stdin EOF. Windows grandchildren are
  job-object-bound by `serve.py`, but the direct child is not; on Unix the
  supervised `llama-server` can be orphaned.
- **Fix:** `Drop for Backend`; assign the direct child to a kill-on-close job on
  Windows and a new process group + group-kill on Unix.

### X-04 — Child leaked if the watcher thread fails to spawn
- **Where:** `src/frontend/src-tauri/src/backend.rs:82-84`
- **Severity:** MEDIUM
- **Fix:** explicit kill/wait on that error path.

### X-05 — `wait_ready` has no independent deadline
- **Where:** `src/frontend/src-tauri/src/backend.rs:93-103`
- **Severity:** MEDIUM
- **What:** if the watcher panics, `wait_ready` blocks forever and the splash hangs.
- **Fix:** timeout of `START_TIMEOUT + slack`.

### X-06 — Spawn failure panics with `panic="abort"` instead of showing the error page
- **Where:** `src/frontend/src-tauri/src/backend.rs:73-75`, `lib.rs:21-26`, `Cargo.toml:30`
- **Severity:** MEDIUM
- **What:** `setup` returns `Err` → Tauri panics → process aborts; the SvelteKit
  `backendError` page is never reached.
- **Fix:** record failure into managed state and let the window render the error.

### X-07 — `runtime/server.start()` holds `_lock` across blocking startup (180s)
- **Where:** `src/backend/runtime/server.py:207-233`, `:276-295`
- **Severity:** HIGH
- **What:** every `status()`/`stop()`/`check_and_restart()`/second `ensure_running`
  blocks for up to three minutes; the Settings/status path hangs.
- **Fix:** set state under lock; launch/health-wait outside a dedicated start lock.

### X-08 — `cleanup_stale_server` on Windows kills by PID after a substring check
- **Where:** `src/backend/runtime/server.py:361-372`
- **Severity:** MEDIUM
- **What:** the docstring claims the executable path is verified; on Windows only
  `"llama-server" in tasklist output` is checked, so a reused PID whose image name
  contains that substring is force-killed.
- **Fix:** query the image path before `taskkill`.

### X-09 — `AssignProcessToJobObject` return unchecked
- **Where:** `src/backend/runtime/server.py:154-156`
- **Severity:** MEDIUM
- **What:** failed assignment means `llama-server` can outlive the app.
- **Fix:** check the return and fall back to a tracked-PID kill.

### X-10 — `Popen` `OSError` not wrapped; ordering leaks a just-spawned process
- **Where:** `src/backend/runtime/server.py:264-275`
- **Severity:** MEDIUM
- **What:** only `RuntimeUnavailableError` is caught, so an exec failure leaves
  `_state=="starting"` and propagates a raw 500 with no CPU fallback. Also
  `_job.assign`/`_pidfile().write_text` run before `self._process = process`, so a
  raise there leaks the process.
- **Fix:** wrap `OSError`; set `_process` immediately after `Popen`.

### X-11 — `check_and_restart` uses a stale model after releasing the lock
- **Where:** `src/backend/runtime/server.py:335-338`
- **Severity:** LOW
- **Fix:** re-check state inside `start`.

### X-12 — `ensure_running` TOCTOU launches twice
- **Where:** `src/backend/runtime/server.py:382-389`
- **Severity:** LOW
- **Fix:** serialize via a start lock.

### X-13 — `_KillOnCloseJob` handle never closed; log unbounded
- **Where:** `src/backend/runtime/server.py:144-152`, `:260`
- **Severity:** LOW
- **Fix:** close on teardown; rotate the log.

### X-14 — Hardcoded llama port duplicated in two configs
- **Where:** `src/backend/runtime/server.py:185`, `configs/runtime.toml:9`, `configs/models.toml:14`
- **Severity:** MEDIUM
- **What:** `llama_cpp.port` and the `local` preset `base_url` can drift, pointing
  the preset at the wrong port.
- **Fix:** derive the preset URL from runtime config or assert equality at load.

### X-15 — `supervisor.run_forever` blocks shutdown for the full model load
- **Where:** `src/backend/runtime/supervisor.py:44-45`
- **Severity:** MEDIUM
- **What:** `finally: if not resume.done(): await resume` waits up to 180s and
  never cancels the task.
- **Fix:** cancel/timeout and stop the server concurrently.

### X-16 — `_stop_without_forgetting` races an explicit `stop()`
- **Where:** `src/backend/runtime/supervisor.py:49-56`
- **Severity:** LOW
- **Fix:** serialize.

### X-17 — `user_models.add_from_file` whole-file sync hash, no cap
- **Where:** `src/backend/runtime/user_models.py:192-213`
- **Severity:** MEDIUM
- **Fix:** stream with progress, bound size, off the request thread.

### X-18 — `user_models._new_id` TOCTOU on concurrent adds
- **Where:** `src/backend/runtime/user_models.py:138-145`
- **Severity:** LOW
- **Fix:** lock.

### X-19 — `model_store` read-modify-write of `VERIFIED_SETTING` with no lock
- **Where:** `src/backend/runtime/model_store.py:73-85`
- **Severity:** LOW
- **Fix:** guard with a module lock.

### X-20 — `model_store._downloads` entries never pruned
- **Where:** `src/backend/runtime/model_store.py:115,152-174`
- **Severity:** LOW
- **Fix:** prune terminal states; clear verified/download state on delete.

### X-21 — `downloads.py` resume does not validate `Content-Range`
- **Where:** `src/backend/runtime/downloads.py:65-67`
- **Severity:** MEDIUM
- **What:** a wrong-range/wrong-remote `206` is appended to `.part`; caught only by
  the final hash, on mismatch the whole `.part` is deleted (wasting the download).
- **Fix:** parse/validate the start offset; reset on mismatch.

### X-22 — `sha256_of` whole-file sync reads block request threads
- **Where:** `src/backend/runtime/downloads.py:28-33`, `model_store.py:82`
- **Severity:** MEDIUM
- **Fix:** chunked progress/cancel or worker.

### X-23 — `_EMBEDDING_BACKEND` / `_RERANKER` lazy globals have no lock
- **Where:** `src/backend/common/provider.py:350-380,427-451`
- **Severity:** MEDIUM
- **What:** two threads can both load large models and one is discarded;
  `_RERANKER, _RERANKER_NAME = ...` is not atomic. Reachable via
  `asyncio.to_thread`.
- **Fix:** a lock around lazy init.

### X-24 — `secrets` set/delete propagate while get swallows
- **Where:** `src/backend/common/secrets.py:20-36`
- **Severity:** MEDIUM
- **What:** a broken keyring is a 500 on write and "no key" on read, and the UI
  tells the user to add a key that was actually stored.
- **Fix:** consistent typed errors distinguishing unavailable vs absent.

### X-25 — `main._lifespan` runs blocking work on the event loop; worker failures can crash shutdown
- **Where:** `src/backend/main.py:83,87,90-104`
- **Severity:** MEDIUM
- **What:** `migrate()` and `office_addin.start_if_connected()` block the loop;
  background tasks have no done-callback, and a task that already failed is
  re-raised by `await task` (not suppressed), turning shutdown into an error.
- **Fix:** `asyncio.to_thread` for the blocking calls; done-callback logging;
  catch/log exceptions when awaiting.

### X-26 — No body-size middleware: uploads spool fully to disk before the cap
- **Where:** `src/backend/api/sources.py:64-101`, `data.py:91-101`
- **Severity:** HIGH
- **What:** Starlette spools the multipart body to a temp file before the handler
  runs; the size ceiling is enforced only while copying *from* that spool. An
  arbitrarily large upload fills the temp dir first. The "reject before storage"
  comment is true only for app storage, not the request body.
- **Fix:** body-size middleware (Content-Length and/or wrapped `receive`) before
  multipart parsing.

### X-27 — Unbounded per-item base64 fields in the Office read request
- **Where:** `src/backend/api/office.py:155-157`
- **Severity:** MEDIUM
- **What:** `images_b64` items have no `max_length` (only the list is capped at
  40); `_decode` materializes full bytes before `read_package` checks its cap.
  40 arbitrarily large strings is a memory-exhaustion vector. `scrape` is 5000
  unbounded strings.
- **Fix:** body-size middleware + per-item `max_length`.

### X-28 — No `async def` handlers: long model calls occupy the AnyIO threadpool
- **Where:** all of `src/backend/api/`
- **Severity:** MEDIUM
- **What:** default ~40 threads; enough concurrent long asks starve unrelated
  endpoints (health, lists).
- **Fix:** make genuinely long routes async with `asyncio.to_thread`, or use a
  dedicated executor.

### X-29 — `wakeup()` TOCTOU / data race on `_LOOP`
- **Where:** `src/backend/ingest/worker.py:149-161`, `:167-168`
- **Severity:** MEDIUM
- **What:** `WAKEUP` set before `_LOOP`; a request thread can observe `WAKEUP` but
  a stale `_LOOP` and skip the wake, delaying an upload by a whole interval.
- **Fix:** assign `_LOOP` first, guard with a lock.

### X-30 — Frontend confirm store hangs on concurrent prompts
- **Where:** `src/frontend/src/lib/stores/confirm.svelte.ts:8-14`
- **Severity:** HIGH
- **What:** a second `confirmDialog` overwrites the pending prompt and the first
  promise never settles.
- **Fix:** queue requests or chain/reject.

### X-31 — Frontend autosave timer can fire after unmount; no `dispose()`
- **Where:** `src/frontend/src/lib/stores/artifact.svelte.ts:176,234,310-316`
- **Severity:** MEDIUM
- **What:** only `flush()`/`remove()` clear the timer; a torn-down page can fire a
  save after unmount, and `remove()` leaves state populated so a late `touch()`
  re-saves a deleted artifact.
- **Fix:** `dispose()` from `PanelState`/`onDestroy`; clear state on remove.

### X-32 — Frontend chat send applies a reply to a switched-away conversation
- **Where:** `src/frontend/src/lib/stores/chat.svelte.ts:171-195`, `components/course/ChatThread.svelte:45-47`
- **Severity:** HIGH
- **What:** `send()` awaits `ensureConversation()` + POST; if the user switches
  chats meanwhile, `applyReply` mutates a turn no longer in `turns`, and the
  caller opens workspace for `turns.length - 1` (the wrong turn).
- **Fix:** stable turn ids; guard updates with the originating conversation id;
  locate the returned turn by id.

### X-33 — Frontend `open()` clears `threadLoading` for the wrong request
- **Where:** `src/frontend/src/lib/stores/chat.svelte.ts:131-149`
- **Severity:** MEDIUM
- **Fix:** generation token.

### X-34 — Frontend `loadCitations` is `void`ed with no catch → unhandled rejection
- **Where:** `src/frontend/src/lib/stores/chat.svelte.ts:203-215`, `ChatThread.svelte:81`
- **Severity:** MEDIUM
- **Fix:** catch and set an error state; toggle retry without spinning.

### X-35 — Frontend systemic: API errors are thrown, so every `error` branch is dead and calls reject
- **Where:** `src/frontend/src/lib/api/client.ts:21-46`
- **Severity:** HIGH
- **What:** `onResponse` converts non-ok responses into a thrown `ApiError`, so all
  `const { data, error }` error branches are unreachable and callers that only
  check `error` get unhandled rejections. ~30 latent sites.
- **Fix:** either return the response and let callers check `error`, or audit every
  caller to `try/catch`.

---

## 4. Performance / optimization

### P-01 — `get_settings()` re-reads `.env` from disk on every call
- **Where:** `src/backend/common/config.py:62-82`
- **Severity:** MEDIUM
- **What:** called from `db.database_path`, `storage.storage_root`, `encoders`,
  every provider resolve, every API request (`deps.py:21`).
- **Fix:** `@cache`/`lru_cache` with explicit reload.

### P-02 — TOML policies re-parsed per request/retrieval
- **Where:** `retrieval/config.py:31-47`, `common/embeddings_config.py:24-38`, `common/lifecycle_config.py:34-51`, `common/prompt_registry.py:100-121`
- **Severity:** MEDIUM
- **Fix:** cache with mtime invalidation; `load_models_config` already is.

### P-03 — `db.connect` re-runs PRAGMAs and re-resolves the path every connection
- **Where:** `src/backend/common/db.py:79-104`
- **Severity:** MEDIUM
- **What:** every repo call opens a fresh connection; `database_path()` calls
  `get_settings()`, and `PRAGMA journal_mode = WAL` writes persistent state.
- **Fix:** cache the path; set WAL once at `migrate()`.

### P-04 — `embed_texts` re-validates every vector's dimension per call
- **Where:** `src/backend/common/provider.py:390-424`
- **Severity:** MEDIUM
- **What:** O(n·d) Python overhead per ingestion batch after the dimension was
  already pinned at load.
- **Fix:** check once.

### P-05 — `encoders` downloads tokenizer files with no hash/size cap
- **Where:** `src/backend/common/encoders.py:55-79`
- **Severity:** MEDIUM (security/perf)
- **What:** `httpx.get(...).content` fully buffered; only revision pinning.
- **Fix:** cap bytes and verify; re-hash existing files rather than size-only.

### P-06 — `funnel.concept_matches` loads all concepts and compiles regexes per query
- **Where:** `src/backend/retrieval/funnel.py:222-232`
- **Severity:** MEDIUM
- **Fix:** tokenized/bounded matcher, precompiled patterns, or FTS.

### P-07 — Embedding seam materializes every vector for the course per query
- **Where:** `src/backend/retrieval/funnel.py:288-291`
- **Severity:** MEDIUM
- **What:** no limit/dimension filter in SQL; Python filters after fetch.
- **Fix:** filter `dimension` in SQL; preallocate a buffer.

### P-08 — `_NARROWED_FETCH_FACTOR = 4` can crowd out selected sources
- **Where:** `src/backend/retrieval/funnel.py:506-526`
- **Severity:** MEDIUM
- **Fix:** filter by `source_ids` in the seam SQL.

### P-09 — Missing index on `chunk_locators(locator_id)`
- **Where:** `src/backend/retrieval/funnel.py:181-184`, `migrations/001_local_baseline.sql:99-103`
- **Severity:** MEDIUM
- **What:** the composite PK `(chunk_id, locator_id)` can't serve
  `WHERE locator_id = ?`; the TOC seam full-scans.
- **Fix:** `CREATE INDEX idx_chunk_locators_locator ON chunk_locators(locator_id)`.

### P-10 — Missing index supporting the claim query
- **Where:** `src/backend/common/queries/ingestion.sql:65-82`, `migrations/001_local_baseline.sql:156-167`
- **Severity:** MEDIUM
- **What:** no index on `(claimed_at, created_at)`; the queue claim is a full scan
  + sort.
- **Fix:** add the index.

### P-11 — Missing index on `toc_entries.source_id`
- **Where:** `migrations/001_local_baseline.sql:236-247`, `ingestion.sql:210-211`
- **Severity:** MEDIUM
- **Fix:** add it.

### P-12 — Missing `(source_id, created_at)` index for `latest_run_for_source`
- **Where:** `migrations/001_local_baseline.sql:117-130`
- **Severity:** LOW
- **Fix:** add it.

### P-13 — `funnel.entry_ids` dedup is O(n²)
- **Where:** `src/backend/retrieval/funnel.py:185-188`
- **Severity:** LOW
- **Fix:** ordered dict/set.

### P-14 — TOC candidates carry a hardcoded `rank=0.0`
- **Where:** `src/backend/retrieval/funnel.py:190-200`
- **Severity:** LOW
- **What:** despite `matched_entries.position` being available, all TOC
  candidates normalize identically, contributing no discriminating signal.
- **Fix:** rank by `-position`.

### P-15 — `settings.py` does N keyring reads per providers/model-options call
- **Where:** `src/backend/api/settings.py:162-172`, `:382-390`
- **Severity:** MEDIUM
- **Fix:** read once per request, cache presence with invalidation.

### P-16 — `runtime._overview` N+1 settings reads + hardware detect per poll
- **Where:** `src/backend/api/runtime.py:111-116`
- **Severity:** MEDIUM
- **What:** per model, `model_store.locate` reads a setting; `hardware.detect()`
  runs on every download-progress poll.
- **Fix:** read the verified cache once; cache hardware.

### P-17 — `office.list_courses` N+1 `list_sources` per course
- **Where:** `src/backend/api/office.py:200`
- **Severity:** MEDIUM
- **Fix:** use `courses_repo.source_stats([...])`.

### P-18 — `data._tree_bytes` walks the whole storage/model trees per request
- **Where:** `src/backend/api/data.py:57-67,138-140`
- **Severity:** MEDIUM
- **Fix:** TTL cache or async/incremental.

### P-19 — `model_store._external_candidates` rglobs the entire HF hub/lmstudio each lookup
- **Where:** `src/backend/runtime/model_store.py:49-59`
- **Severity:** MEDIUM
- **Fix:** cache by directory mtime or index once.

### P-20 — `course_archive.export` and `downloads.sha256_of` whole-file memory/hash
- **Where:** `course_archive.py:106-172`, `downloads.py:28-33`
- **Severity:** MEDIUM
- **Fix:** stream.

### P-21 — `sources.py` re-decodes the PDF and re-renders the page per request
- **Where:** `src/backend/api/sources.py:165-172`
- **Severity:** MEDIUM
- **Fix:** bounded LRU of rendered pages or the opened document.

### P-22 — Frontend `DocEditor` re-evaluates the whole toolbar every transaction
- **Where:** `src/frontend/src/lib/components/artifacts/DocEditor.svelte:70-73,159`
- **Severity:** MEDIUM
- **Fix:** derive per-command state or throttle.

### P-23 — Frontend `citationChips` rebuilds all decorations every change
- **Where:** `src/frontend/src/lib/components/artifacts/citationChips.ts:40`
- **Severity:** MEDIUM
- **Fix:** incremental mapping.

### P-24 — Frontend `CodeView.highlightAuto` runs synchronously in a `$derived`
- **Where:** `src/frontend/src/lib/components/CodeView.svelte:18-27`
- **Severity:** MEDIUM
- **What:** `highlightAuto` on arbitrary model output can be very slow and runs
  during render.
- **Fix:** cap length / skip auto-detect above a threshold.

### P-25 — Frontend `ResizableSplit` updates per pointermove with no rAF, and persists per change
- **Where:** `src/frontend/src/lib/components/ResizableSplit.svelte:49-54`, `routes/(app)/courses/[id]/+page.svelte:396`
- **Severity:** MEDIUM
- **What:** `bind:width` writes `panel.width` directly, so `PanelState.persist()`
  is never called — the width isn't persisted at all despite the comment — while
  drag writes layout per event.
- **Fix:** local width + throttled `setWidth` on drag end.

### P-26 — `RichText` re-parses entire answers on unrelated re-renders
- **Where:** `src/frontend/src/lib/components/RichText.svelte:12,16`
- **Severity:** LOW
- **Fix:** derive on `text` only (it does) but memoize render output.

---

## 5. Frontend correctness (beyond concurrency/perf above)

### F-01 — `ChatList` rename Save button is broken
- **Where:** `src/frontend/src/lib/components/course/ChatList.svelte:106`, `:26-36`
- **Severity:** HIGH
- **What:** the input's `onblur` sets `editingId = null`; mousedown on Save blurs
  the input before `submit` fires, so `saveRename` sees `editingId === null` and
  returns. Only Enter works.
- **Fix:** don't clear on blur, or check `relatedTarget`.

### F-02 — `ChatThread` keys turns by array index
- **Where:** `src/frontend/src/lib/components/course/ChatThread.svelte:130`
- **Severity:** MEDIUM
- **What:** `retry()` filters a turn out, shifting every subsequent key; Svelte
  reuses the wrong DOM and replays animations.
- **Fix:** stable turn id keys.

### F-03 — Course page captures `courseId` once; component reuse binds old course
- **Where:** `src/frontend/src/routes/(app)/courses/[id]/+page.svelte:38`
- **Severity:** HIGH
- **What:** navigating `/courses/a` → `/courses/b` reuses the component, so
  `courseId`, `chats`, `canvas`, and `panel` stay bound to the old course.
- **Fix:** derive reactively from `page.params.id` and recreate stores.

### F-04 — `SlidesView` global arrow keys hijack typing
- **Where:** `src/frontend/src/lib/components/SlidesView.svelte:32-41`
- **Severity:** HIGH
- **What:** no focus guard; arrows typed in the chat textarea step the deck.
  `FlashcardsArtifact.svelte:48` correctly checks `closest('input, textarea')`.
- **Fix:** bail on input/textarea/contenteditable or modifier combos.

### F-05 — `ArtifactContent` renders phantom citation chips
- **Where:** `src/frontend/src/lib/components/artifacts/ArtifactContent.svelte:94,98`
- **Severity:** MEDIUM
- **What:** `<CodeView item={{... sources:[1]}} sources={[]} />` makes
  `SourceChips` show "Based on 1" with no filename.
- **Fix:** `sources: []`.

### F-06 — `LoadVersions` failures are unhandled rejections
- **Where:** `src/frontend/src/lib/stores/artifact.svelte.ts:274-279`, `routes/(app)/courses/[id]/artifacts/[artifactId]/+page.svelte:182`
- **Severity:** MEDIUM
- **Fix:** try/catch and surface an error.

### F-07 — `artifact.save` 409 branch is unreachable
- **Where:** `src/frontend/src/lib/stores/artifact.svelte.ts:216-219`
- **Severity:** MEDIUM
- **What:** the middleware throws on 409 before returning the tuple, so conflicts
  are handled only in the catch; the branch misleads readers.
- **Fix:** delete it.

### F-08 — `chat.setModel`/`setSources` leave an empty conversation on failure
- **Where:** `src/frontend/src/lib/stores/chat.svelte.ts:235-241`
- **Severity:** MEDIUM
- **What:** `ensureConversation()` persists a new empty chat before the patch;
  a failed patch leaves it behind, contradicting "a new chat is a draft".
- **Fix:** patch first / roll back.

### F-09 — `panel.close()` never closes the tab if `flush()` rejects
- **Where:** `src/frontend/src/lib/stores/panel.svelte.ts:63-71`, `components/course/Panel.svelte:79-82`
- **Severity:** MEDIUM
- **Fix:** try/finally around flush, or close regardless.

### F-10 — `LocalModelCard` unhandled rejections and unsafe indexing
- **Where:** `src/frontend/src/lib/components/LocalModelCard.svelte:103-107,142-159,197-198,57-73`
- **Severity:** MEDIUM
- **What:** `cancel`/`remove` have no try/catch; `data.files[0].file` throws on an
  empty list; `refresh()` never clears a stale error.
- **Fix:** try/catch, guard length, clear error on success.

### F-11 — `ConnectionsCard` unhandled rejections and stale test text
- **Where:** `src/frontend/src/lib/components/settings/ConnectionsCard.svelte:150-172,174-187`
- **Severity:** MEDIUM
- **Fix:** try/catch; clear `tests[id]` on failure.

### F-12 — `office` store blindly unwraps with `data!`
- **Where:** `src/frontend/src/lib/stores/office.ts:21-44`
- **Severity:** MEDIUM
- **Fix:** null/error check → typed error.

### F-13 — `workspace.openSession` returns `undefined` for unknown types
- **Where:** `src/frontend/src/lib/stores/workspace.svelte.ts:164-179`
- **Severity:** MEDIUM
- **Fix:** exhaustive `never` check or throw.

### F-14 — Dialog/popover/drawer lack focus traps and initial focus
- **Where:** `ConfirmHost.svelte:12-24`, `Popover.svelte:35-49`, `routes/(app)/+layout.svelte:114-135`, `ResizableSplit.svelte:79-94`
- **Severity:** MEDIUM (a11y)
- **Fix:** focus trap + `role="separator"`/aria values where applicable.

### F-15 — `Card` drops a description-only header
- **Where:** `src/frontend/src/lib/components/Card.svelte:16-24`
- **Severity:** LOW
- **Fix:** `{#if title || description || actions}`.

### F-16 — `CodeView.copy()` unhandled rejection + stacked timers
- **Where:** `src/frontend/src/lib/components/CodeView.svelte:31-35`
- **Severity:** MEDIUM
- **Fix:** try/catch, clear prior timer.

### F-17 — `Select`/`TextInput` derive ids from labels; duplicates break labels
- **Where:** `src/frontend/src/lib/components/Select.svelte:25`, `TextInput.svelte:20`
- **Severity:** LOW (a11y)
- **Fix:** `crypto.randomUUID()`-based ids.

### F-18 — `SourcesPanel` Space triggers page scroll; input has no `accept`
- **Where:** `src/frontend/src/lib/components/course/SourcesPanel.svelte:143-158,172`
- **Severity:** LOW
- **Fix:** `preventDefault()` on Space; add `accept`.

### F-19 — `Quiz`/`QuizArtifact` reset all picks when question count changes; `fromCharCode` breaks past 26
- **Where:** `src/frontend/src/lib/components/QuizArtifact.svelte:20-22`, `Quiz.svelte:92`
- **Severity:** MEDIUM (data loss in UI) / LOW
- **Fix:** key picks by question identity; handle >26 options.

### F-20 — `FlashcardsArtifact` biased shuffle; stale order on content edits
- **Where:** `src/frontend/src/lib/components/FlashcardsArtifact.svelte:41-45,22-27`
- **Severity:** LOW/MEDIUM
- **Fix:** Fisher–Yates; key by card identity or reset on any structural change.

### F-21 — `EditableDocument.download()` revokes the object URL too early
- **Where:** `src/frontend/src/lib/components/EditableDocument.svelte:22-30`
- **Severity:** LOW
- **Fix:** revoke in a `setTimeout(…, 0)`.

### F-22 — `render.ts` enables the SVG DOMPurify profile for model HTML
- **Where:** `src/frontend/src/lib/utils/render.ts:8-11`
- **Severity:** MEDIUM (hardening)
- **Fix:** drop `svg` unless required.

### F-23 — `ArtifactContent` type-cast bypasses validation
- **Where:** `src/frontend/src/lib/components/artifacts/ArtifactContent.svelte:44-46`
- **Severity:** MEDIUM
- **Fix:** validate against generated types.

### F-24 — `toast` dismissal timers never cleared; unbounded list
- **Where:** `src/frontend/src/lib/stores/toast.svelte.ts:7`
- **Severity:** LOW
- **Fix:** track/clear timers; cap length.

### F-25 — `format.timeAgo` NaN for invalid input; `labels.initials` astral hashing
- **Where:** `src/frontend/src/lib/utils/format.ts:15-28`, `labels.ts:16`
- **Severity:** LOW/NIT
- **Fix:** guard; iterate code points.

### F-26 — `+error.svelte` full-reloads the SPA
- **Where:** `src/frontend/src/routes/+error.svelte:13`
- **Severity:** LOW
- **Fix:** `goto('/')`.

### F-27 — `ArtifactsPanel.rename` read-modify-write race
- **Where:** `src/frontend/src/lib/components/course/ArtifactsPanel.svelte:57-72`
- **Severity:** MEDIUM
- **Fix:** optimistic version / `If-Match` semantics.

### F-28 — `panel.setWidth` persists on every move if used
- **Where:** `src/frontend/src/lib/stores/panel.svelte.ts:83-86`
- **Severity:** LOW
- **Fix:** debounce.

---

## 6. Tauri / Rust (misc)

### R-01 — External link opening is broken by an unscoped permission
- **Where:** `src/frontend/src-tauri/capabilities/default.json:8`
- **Severity:** HIGH
- **What:** `opener:allow-open-url` carries no scope; `open_url` requires at least
  one matching allow entry, so every `openUrl` from `routes/+layout.svelte:32`
  returns `ForbiddenUrl`.
- **Fix:** use `opener:default`, or add an explicit `http://*`/`https://*` scope.

### R-02 — Release backend path depends on an out-of-band config override
- **Where:** `src/frontend/src-tauri/src/backend.rs:171-191`, `tauri.bundle.conf.json:4`
- **Severity:** MEDIUM
- **What:** `resources: ["backend/"]` lives only in `tauri.bundle.conf.json`,
  applied only by `scripts/build_desktop.py`. A plain `tauri build` ships no
  backend and fails at runtime.
- **Fix:** move resources into `tauri.conf.json` or guard the missing resource.

### R-03 — Error message points at the wrong log
- **Where:** `src/frontend/src-tauri/src/backend.rs:228-236,61-64`
- **Severity:** MEDIUM
- **What:** `failure()` names `<data>/backend.log`, but the shell captures stderr
  to `<data>/backend-stderr.log`; an early crash lands only in the latter.
- **Fix:** mention both, or name the stderr log on early exit.

### R-04 — Health parsing accepts only literal `HTTP/1.1 200`
- **Where:** `src/frontend/src-tauri/src/backend.rs:238-264`
- **Severity:** LOW
- **Fix:** parse the status code numerically.

### R-05 — `map_while(Result::ok)` reports an I/O error as "exited before it started"
- **Where:** `src/frontend/src-tauri/src/backend.rs:201-205,221-225`
- **Severity:** LOW
- **Fix:** distinguish `Ok(None)` from `Err`.

### R-06 — `panic = "abort"`, `opt-level = "s"`, mobile crate types
- **Where:** `src/frontend/src-tauri/Cargo.toml:13,29,30`
- **Severity:** MEDIUM/LOW
- **What:** `panic="abort"` defeats Tauri's panic handler; `staticlib`/`cdylib`
  only slow a desktop build.
- **Fix:** default unwinding; `["rlib"]`.

### R-07 — Main window hidden with no tray and no guaranteed quit path
- **Where:** `src/frontend/src-tauri/src/lib.rs:34-41`, `tauri.conf.json:22,36`
- **Severity:** MEDIUM
- **What:** closing `main` hides it; with no tray, destroying the undecorated
  companion can leave no visible UI.
- **Fix:** tray icon, or handle companion close.

### R-08 — Capabilities grant all permissions to both windows
- **Where:** `src/frontend/src-tauri/capabilities/default.json:5-12`
- **Severity:** MEDIUM
- **What:** custom commands aren't capability-scoped; both windows get dialogs and
  opener. Split main/companion capabilities and scope `backend_info`.
- **Fix:** per-window capabilities; validate the invoking webview.

### R-09 — CSP may block the inline theme bootstrap; `devCsp: null`
- **Where:** `src/frontend/src-tauri/tauri.conf.json:47,52`
- **Severity:** LOW
- **Fix:** module script/hash the bootstrap; enable a dev CSP.

### R-10 — Version sources: `tauri.conf.json` → package.json vs. hardcoded Cargo version
- **Where:** `src/frontend/src-tauri/tauri.conf.json:4`, `Cargo.toml:3`
- **Severity:** LOW
- **Fix:** single source or assert equality.

### R-11 — `companion.rs` mixed physical/logical math, silent primary fallback, no DPI recompute
- **Where:** `src/frontend/src-tauri/src/companion.rs:6-24`
- **Severity:** LOW
- **Fix:** handle `ScaleFactorChanged`; avoid silent primary fallback.

### R-12 — Duplicated layout constants
- **Where:** `src/frontend/src-tauri/src/companion.rs:3-4`, `tauri.conf.json:29`
- **Severity:** NIT
- **Fix:** derive from config.

### R-13 — `BackendInfo.log_dir` exposed but never read by the frontend
- **Where:** `src/lib/api/backend.ts:19`
- **Severity:** NIT
- **Fix:** use it in errors or drop it.

---

## 7. Tests, CI, packaging

### T-01 — **CRITICAL (build): the new `companion` code is untracked while referenced by tracked files**
- **Where:** `git status`; `src/backend/main.py:25`; `src/frontend/src-tauri/src/lib.rs`; `tauri.conf.json:25-42`; `capabilities/default.json`
- **Severity:** CRITICAL
- **What:** `src/backend/api/companion.py`, `src/frontend/src-tauri/src/companion.rs`,
  and `src/frontend/src/routes/companion/` are untracked, but `main.py`, `lib.rs`,
  `tauri.conf.json`, and `capabilities/default.json` (all modified) reference them.
  Committing the tracked changes without the new files yields an `ImportError` at
  backend startup and a Tauri build failure in CI.
- **Fix:** commit the companion files together (or revert the references); verify
  with a clean checkout.

### T-02 — `set_version.py` does not update `Cargo.lock`; CI `--locked` will break
- **Where:** `scripts/set_version.py:26,48-56`, `.github/workflows/ci.yml:89`, `Cargo.lock:3241-3242`
- **Severity:** HIGH
- **What:** the first version bump leaves `Cargo.lock` stale; `cargo clippy
  --all-targets --locked` fails before the release build. `test_version.py` does
  not check `Cargo.lock`, so drift is invisible locally.
- **Fix:** update `Cargo.lock` in `set_version.py`; assert it in `test_version.py`;
  add a "lockfile in sync" CI step.

### T-03 — No Python lockfile; unbounded `>=` deps
- **Where:** `pyproject.toml:10-34,46-51`, `.github/workflows/ci.yml:31,67`
- **Severity:** HIGH
- **What:** backend installs drift between CI and dev; no `pip check`.
- **Fix:** add a lock/constraints file and install from it.

### T-04 — `setuptools.find` with no `__init__.py` builds an empty distribution
- **Where:** `pyproject.toml:53-54`
- **Severity:** HIGH
- **What:** `where=["src"]` only discovers regular packages; there is no
  `src/backend/__init__.py`, so the wheel is empty. `[project.scripts]` is absent,
  so `python -m scripts.*` only works from the repo root.
- **Fix:** `namespaces=true` (or add `__init__.py`), package-data for
  `configs`/`migrations`/`queries`, and entry points.

### T-05 — `lxml` is imported in production but undeclared
- **Where:** `pyproject.toml:46-51`, `src/backend/office_addin/manifest.py:14`
- **Severity:** HIGH
- **What:** `lxml` arrives transitively via `python-docx`; `mypy --strict` fails on
  a clean install, and `lxml-stubs` is undeclared.
- **Fix:** declare `lxml` and `lxml-stubs`, or add a mypy override.

### T-06 — `test_storage.test_remove_course_directory` is vacuous
- **Where:** `tests/test_storage.py:136-139`
- **Severity:** HIGH
- **What:** it monkeypatches `config.get_settings`, but `storage.py` bound
  `get_settings` at import, so the patch has no effect; the assertion
  (`not os.path.exists(sandbox/...)`) is vacuously true. The test always passes.
- **Fix:** patch `storage.get_settings`.

### T-07 — `_temp_uploads` mutates the global `tempfile.tempdir` and never restores it
- **Where:** `tests/test_storage.py:10-20`
- **Severity:** HIGH
- **What:** leaks state into every subsequent test; ignores `tmp_path_factory`;
  `/tmp/course-proj-uploads` is a fixed shared path on Linux.
- **Fix:** `monkeypatch.setattr(tempfile, "tempdir", ...)`.

### T-08 — `conftest` only pins a subset of env keys
- **Where:** `tests/conftest.py:15-17`, `src/backend/common/config.py:19-31`
- **Severity:** HIGH
- **What:** `_load_dotenv` writes any unset key from `.env` into `os.environ`
  permanently; an `APP_OFFICE_PORT` there breaks `test_office_addin_setup.py`
  (hard-asserts 47831) silently.
- **Fix:** pin every config key or no-op `_load_dotenv` in an autouse fixture.

### T-09 — `test_app.py` blocks forever if the subprocess never prints
- **Where:** `tests/test_app.py:76-80`
- **Severity:** HIGH
- **What:** `readline()` has no timeout; the 60s deadline starts only after the
  first line. A bad import hangs CI.
- **Fix:** bounded wait (`selectors`/thread+queue) or `communicate(timeout=...)`.

### T-10 — `test_app.py` uses the real `data/` dir and a real socket
- **Where:** `tests/test_app.py:65-95`
- **Severity:** MEDIUM
- **What:** `APP_DATA_DIR` is not set for the subprocess.
- **Fix:** set a temp data dir; mark `@pytest.mark.integration`.

### T-11 — Tests that assert nothing / tautological tests
- **Where:** `tests/test_retrieval.py:314-321,324-340`, `tests/test_imports.py:1-8`, `tests/test_schemas.py:60-280`
- **Severity:** MEDIUM
- **What:** `assert candidates is not None` (always true); a test with no
  assertions; many schema tests assert Pydantic passthrough.
- **Fix:** assert the actual property or delete.

### T-12 — `test_toc.test_reingesting_replaces_a_sources_entries` is self-contradictory
- **Where:** `tests/test_toc.py:106-122`
- **Severity:** MEDIUM
- **What:** asserts `count == 2` after re-ingesting the same source twice, proving
  additive behavior while the name claims replacement.
- **Fix:** record the count after the first run, assert unchanged after re-ingest.

### T-13 — Wall-clock / port / host-environment dependent tests
- **Where:** `tests/test_ingestion_worker.py:188-218`, `tests/test_office_addin_setup.py:343-383`, `tests/test_runtime.py:81-82`
- **Severity:** MEDIUM
- **What:** `assert elapsed < 2.0`, a bind/close "free port" TOCTOU plus TLS
  polling, and a test asserting real host RAM > 1 GiB.
- **Fix:** inject a clock / bind port 0 / stub the OS probe; mark timing-sensitive.

### T-14 — `eval_models.py` uses `model.replace("/", "_")` for the run dir
- **Where:** `scripts/eval_models.py:142`, `:27`
- **Severity:** MEDIUM
- **What:** the documented cloud example contains `:`, illegal on Windows — the
  script crashes following its own docstring.
- **Fix:** whitelist-sanitize.

### T-15 — Production scripts import from `tests.factories`
- **Where:** `scripts/eval_models.py:70-105`
- **Severity:** MEDIUM
- **What:** architectural inversion; breaks if tests move.
- **Fix:** move seeding into `src/backend/evals/`.

### T-16 — `eval_models.py` aborts the whole bake-off on a per-case provider error
- **Where:** `scripts/eval_models.py:129-135`
- **Severity:** MEDIUM
- **What:** only `ProviderUnavailableError` is caught; rate-limit/budget errors
  kill the run and lose the report. Exit code also ignores failed cases.
- **Fix:** catch per case, record, continue; exit non-zero on failures.

### T-17 — `set_version.py` silently skips a missing `package-lock.json`
- **Where:** `scripts/set_version.py:51-56`
- **Severity:** MEDIUM
- **What:** leaves package.json/lock inconsistent, which `npm ci` rejects.
- **Fix:** fail loudly.

### T-18 — `build_desktop.py` reports success when no installer is produced
- **Where:** `scripts/build_desktop.py:95-107`
- **Severity:** LOW
- **What:** `rglob` returns `[]`, `main` prints nothing and exits 0.
- **Fix:** raise `SystemExit`.

### T-19 — `build_desktop.py` swallows `rmtree` errors
- **Where:** `scripts/build_desktop.py:90`
- **Severity:** LOW
- **Fix:** explicit `OSError` handling.

### T-20 — `dump_openapi.py` doesn't assert a non-empty spec
- **Where:** `scripts/dump_openapi.py:17`
- **Severity:** LOW
- **Fix:** assert `"paths" in spec`.

### T-21 — `check_encoders.py` is never run by CI; hardcodes model ids
- **Where:** `scripts/check_encoders.py:40-42,57`
- **Severity:** MEDIUM
- **What:** golden-rule-3 parity check unenforced; ids duplicate the encoder
  constants.
- **Fix:** add a job with the `parity` extra; import the shared constants.

### T-22 — CI never runs the eval harness or encoder parity
- **Where:** `.github/workflows/ci.yml`
- **Severity:** MEDIUM
- **What:** the stated core invariant ("evaluation is the center") has no CI gate.
- **Fix:** run the scripted answer eval and parity check.

### T-23 — CI actions pinned to mutable tags; no lockfile cache key
- **Where:** `.github/workflows/ci.yml:24,46,59,62`
- **Severity:** LOW
- **Fix:** pin SHAs; cache on the lockfile.

### T-24 — Release workflow regexes `version.py` and builds without `--locked`
- **Where:** `.github/workflows/release.yml:48-63`
- **Severity:** MEDIUM
- **What:** `re.search` raises `AttributeError` if formatting changes; `tauri
  build` without `--locked` can ship a different dependency resolution than CI.
- **Fix:** parse with `ast`/`tomllib`; pass `--locked`.

### T-25 — `conftest` keyring stub depends on the module-attribute import style
- **Where:** `tests/conftest.py:54-67`, `providers.py:48`
- **Severity:** MEDIUM
- **What:** a refactor to `from ... import get_api_key` silently disables the stub
  and tests hit the real OS keychain.
- **Fix:** set a dummy keyring backend, or assert the patch is active.

### T-26 — `test_retrieval` / `test_schemas` pin stub arithmetic rather than semantics
- **Where:** `tests/test_retrieval.py:188-203,514-586`, `tests/test_schemas.py`
- **Severity:** LOW
- **Fix:** property assertions.

### T-27 — `tests/factories.rename_course` bypasses the repo seam
- **Where:** `tests/factories.py:20-25`
- **Severity:** MEDIUM
- **What:** raw SQL `UPDATE` skips the course-memory refresh that production
  `rename_course` triggers.
- **Fix:** call the repo function.

### T-28 — No tests for `sanitize_display_name` truncation, streaming ceiling, archive symlinks
- **Where:** `tests/test_storage.py` (gap)
- **Severity:** MEDIUM
- **Fix:** add adversarial edge tests.

### T-29 — No end-to-end test for `set_version.py`
- **Where:** `tests/test_version.py:13-27` (gap)
- **Severity:** MEDIUM
- **Fix:** run it against a tmp copy and assert every file changed.

### T-30 — `pytest --basetemp` pinned into the repo
- **Where:** `pyproject.toml:59`
- **Severity:** LOW
- **Fix:** per-run temp dir.

### T-31 — `test_imports.py` doesn't import all packages or build the app
- **Where:** `tests/test_imports.py:1-8`
- **Severity:** LOW
- **Fix:** import `api`, `artifacts`, `office_addin`, `runtime`, `scripts`; assert
  `create_app()`.

### T-32 — No coverage for `api/companion.py` or the `student_model` subsystem
- **Where:** `tests/` (gap)
- **Severity:** LOW
- **Fix:** add tests.

---

## 8. Docs and dead code

### D-01 — Docs describe a hosted Postgres, multi-user product that no longer exists
- **Where:** `docs/system.md` throughout (e.g. `:70-140`, `:285-540`, `:1105+`)
- **Severity:** MEDIUM
- **What:** the whole storage/auth/tier/account-deletion narrative is superseded
  by the local-first app, but the doc still presents it as current. Agents told to
  "read system.md before structural changes" will design against a dead system.
- **Fix:** trim to the local-first reality, or clearly quarantine superseded
  sections.

### D-02 — `main.py` imports `companion`; companion files untracked
- **Where:** see T-01
- **Severity:** CRITICAL (duplicate; listed here for the docs/consistency bucket)

### D-03 — Frontend README points at removed `docs/decisions/`
- **Where:** `src/frontend/README.md:164-165`
- **Severity:** MEDIUM
- **Fix:** point at `docs/notes.md`/git history.

### D-04 — README "five checks" and docs list are stale
- **Where:** `README.md:90,108-114`
- **Severity:** LOW
- **Fix:** enumerate the real gates and include `docs/notes.md`.

### D-05 — `.env.example` omits most supported keys
- **Where:** `.env.example` vs `common/config.py:64-81`
- **Severity:** MEDIUM
- **Fix:** document every key.

### D-06 — `schemas/` is full of dead modules and lies
- **Where:** `schemas/student_model.py:16-66`, `schemas/chat.py:15-46`, `schemas/evidence.py:11-24,44-61`, `schemas/identity.py:32-43`
- **Severity:** MEDIUM
- **What:** `student_model` has no tables; `chat.Conversation`/`ConversationTurn`
  are unused duplicates; `RetrievalTrace.retrieved_chunk_ids: list[UUID]` does not
  match the stored JSON object; `evidence.Claim/Citation/Response` are unused, and
  `Citation` collides in name with `archive_notebook.Citation`.
- **Fix:** delete or wire up; fix the type to match storage.

### D-07 — `migrate.RETIRED_VERSIONS` is dead code claiming a hazard it doesn't prevent
- **Where:** `src/backend/common/migrate.py:15`
- **Severity:** MEDIUM
- **Fix:** enforce it or delete it.

### D-08 — `migrate` uses f-string SQL + `executescript` (implicit commit)
- **Where:** `src/backend/common/migrate.py:60-65`
- **Severity:** MEDIUM
- **What:** `executescript` implicitly commits pending work, contradicting the
  docstring's explicit-transaction claim; `{script}` is arbitrary file content
  adjacent to `BEGIN IMMEDIATE`.
- **Fix:** parameterized insert; run statements deliberately.

### D-09 — `chunk_embeddings` schema/comment mismatch kills the model-swap story
- **Where:** `migrations/001_local_baseline.sql:107-115`, `queries/ingestion.sql:144-152`
- **Severity:** MEDIUM
- **What:** `chunk_id` is the PK (one row per chunk) and `replace_chunk_embedding`
  overwrites on conflict, yet the comment and `system.md` claim a model swap
  "orphans old rows filtered by model". Switching models destroys the old vector.
- **Fix:** PK `(chunk_id, model)`, or correct the comment/docs.

### D-10 — `storage.compress_for_storage` and `copy_stored` are test-only/dead
- **Where:** `src/backend/common/storage.py:156-166,233-243`
- **Severity:** LOW
- **What:** `compress_for_storage` is a memory-loading duplicate of the streaming
  path kept alive by tests only; the two implement independent `savings` math.
- **Fix:** delete or unify.

### D-11 — `course_archive._discard` embeds raw SQL outside the query registry
- **Where:** `src/backend/common/course_archive.py:272-274`
- **Severity:** LOW
- **Fix:** move into `queries/*.sql`.

### D-12 — `ingestion.sql insert_toc` hardcodes `version = 1` (versioning is dead)
- **Where:** `src/backend/common/queries/ingestion.sql:206-208`
- **Severity:** LOW
- **Fix:** increment or remove the versioning pretense.

### D-13 — `WorkspaceHtml` is unreachable dead code
- **Where:** `src/backend/tutor/workspace.py:62-66`, `artifacts/content.py:343-344`
- **Severity:** LOW
- **What:** no prompt, no `Intent.HTML`, no `compose.workspace_schema` branch.
- **Fix:** wire it or delete it.

### D-14 — `content.blank()` and several `KNOWN_*`/marker constants are unused
- **Where:** `src/backend/artifacts/content.py:163-164`, `course_memory.py:43`
- **Severity:** NIT
- **Fix:** delete.

### D-15 — `memory/__init__.py` package is empty and collides with two other memory names
- **Where:** `src/backend/memory/__init__.py:1-10`
- **Severity:** LOW
- **Fix:** rename or delete.

### D-16 — `MODEL_TASKS` dead entries; `raw_pdf_bytes` dead parameter; `TYPE_CHECKING: pass`
- **Where:** `src/backend/ingest/orchestrator.py:48-52`, `extract.py:278,330-331`, `extract.py:24-25`
- **Severity:** NIT
- **Fix:** delete.

### D-17 — `prompts.toml` `artifact_generation` text is never sent; version/comment drift
- **Where:** `configs/prompts.toml:130-135`, `:1-2`
- **Severity:** LOW
- **Fix:** use or remove; version the text history.

### D-18 — `queries/course_memory.sql get_memory` and `storage.copy_stored` unused
- **Where:** `queries/course_memory.sql:58-68`
- **Severity:** NIT
- **Fix:** delete.

### D-19 — `_parse_timestamp` raises `ValueError` on corrupt rows
- **Where:** `src/backend/common/db.py:54-56`
- **Severity:** LOW
- **Fix:** typed error.

### D-20 — `CHARS_PER_TOKEN = 4` is the only budget model; `[truncated]` marker unused
- **Where:** `src/backend/common/course_memory.py:38,43`
- **Severity:** NIT
- **Fix:** document or remove.

### D-21 — Two versions of `ExportView`, duplicated `_require_course` ×5, duplicated `require_*_token`
- **Where:** `api/artifacts.py:161-163` vs `api/data.py:29-33`; `courses.py:76`, `sources.py:54`, `tutor.py:85`, `conversations.py:141`, `artifacts.py:186`; `deps.py:12` vs `office.py:55`
- **Severity:** NIT
- **Fix:** consolidate.

### D-22 — `secrets.SERVICE_NAME = "course-assistant"` vs package "stacks"
- **Where:** `src/backend/common/secrets.py:12`
- **Severity:** NIT
- **Fix:** align.

### D-23 — `Icon.svelte` includes unused icons
- **Where:** `src/frontend/src/lib/components/Icon.svelte:82-91`
- **Severity:** NIT
- **Fix:** prune.

### D-24 — `.env` is present in the working tree
- **Where:** repo root
- **Severity:** MEDIUM (verify)
- **What:** `.env` is gitignored, but confirm it contains no real secrets and is not
  in any commit (`git log --all -- .env`). The `.env.example` should be the
  committed template.
- **Fix:** verify history; rotate any leaked key.

---

## 9. Suggested triage order

1. **T-01** (untracked companion breaks clean checkout/build) — blocking.
2. **S-01, S-02** (arbitrary file write, XSS) — security.
3. **S-03, S-04, S-06** (fail-open auth, exposed docs) — security.
4. **C-01, C-02, C-03, C-04, C-05** (data loss / stuck runs / silent loss).
5. **C-25** (eval kill-switch is measuring the wrong thing).
6. **X-01, X-02, X-03, X-07** (startup deadlock, quit freeze, orphaned processes).
7. **C-65, C-66, C-70** (ledger/quota/lost-update concurrency).
8. **T-02, T-03, T-04, T-05** (build reproducibility).
9. **F-01, F-03, F-04, F-35/X-35** (user-visible frontend breakage).
10. Everything MEDIUM, then LOW/NIT as cleanup.

---

## 10. Caveats

- These findings are from a static read; many are not reproduced with a failing
  test. Treat each as a hypothesis until verified.
- A few line numbers may be off by a few lines where the working tree is dirty.
- Some "dead code" calls are deliberate scaffolding for planned work; check
  `docs/plan-notebook.md` before deleting.
- The untracked `companion` feature appears to be mid-landing; several findings
  there (R-11, R-12, C-80) may be moot once finished.
