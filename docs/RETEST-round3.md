# Stacks: round-3 retest (d98d365 "Bug fix")

- **Date:** Sun Oct 4, 2026, 13:58–15:25 ET (code-level + scratch replays; no GUI driven).
- **Tester:** Grok Bot (executor) for Riley K.
- **Commit:** `d98d365` "Bug fix", Riley Kehoe, 2026-10-04 12:51 ET. 152 files, +9196/−1262. Riley's remote was not touched.
- **Worktree:** `/workspace/Stacks-r3`, detached at d98d365, with its own `.venv`, `node_modules` and `target/`. Stacks-r2 and the running r2 app (PIDs 896146…896406) were left alone.
- **LLM:** `.env` → MiMo `mimo-v2.6-flash` @ `https://token-plan-sgp.xiaomimimo.com/v1`, `LLM_API_KEY` from `$XIAOMI_API_KEY` (mode 600). Every MiMo run also passed `LLM_API_KEY="$XIAOMI_API_KEY"` explicitly (the shell's exported key is LongCat, NEW-6).
- **MiMo profile:** upstream now ships `configs/models/mimo-v2.6-flash.toml` (`reasoning = true`, `max_output_tokens = 16384`), so our untracked profile was **not** copied.
- **Scratch data:** `/workspace/stacks-test/r3-scratch/` — `data/` (course `c3d14934-…`, the same 5 PDFs, MiMo OCR), `ingest.log`, `analyze.py`, `probe/` (raw OCR probes `ocr_*.json`, artifact replays `ask-w1.json`, full-corpus replays `ask-results.json`).

> **Complete** as of 15:25 ET.

**Summary.** All automated checks pass (pytest 1026/1026, npm test 31/31, clippy clean). Of 48 STK items: 17 fixed (4 newly verified, 13 carried), 5 fixed in code awaiting GUI, 11 partial, 15 not fixed, 0 regressed. NEW-1/2/3/7 are fixed; NEW-8 (poll cap) and NEW-9 (keyring 503) are untouched and missing from Riley's docket. The biggest new problem is OCR: the prompt tells the model to leave blank pages empty, the splitter rejects exactly that, and a rejected batch is never retried, so Week3 got **0 of 27** pages OCR'd (R3-NEW-1). Documents/decks now generate on MiMo, but tables and bullets inside them break (R3-NEW-2), and the 10-question quiz had every answer = A (R3-NEW-13).

## 1. Check results (Stacks-r3)

| Check | Result |
|---|---|
| `pip install -e ".[desktop,dev]" -c constraints.txt` (new `.venv`) | OK |
| `npm ci` | OK (EBADENGINE warning only: node v20.19.2) |
| Regenerate API types (`dump_openapi` → `npm run gen:api`) | OK; regenerated `schema.d.ts` is identical to the committed one (no git diff) |
| `pytest` (`env -u LLM_API_KEY`) | **1026 passed**, 0 failed, 1 warning (97 s) — r2: 845 |
| `ruff check` / `ruff format --check` | pass / 239 files formatted |
| `mypy src` | no issues (148 files) |
| `npm run check` (svelte-check) | 0 errors, 0 warnings |
| `npm test` | **31/31** (r2: 19) |
| `npm run build` | OK |
| `cargo check` | OK (50 s) |
| `cargo clippy --all-targets -- -D warnings` | OK, 0 warnings |
| `cargo test` | 3/3 (new `exports.rs` tests) |
| Scratch ingestion, 5 PDFs with MiMo OCR | **All 5 indexed** (no source failed; r2: Week5 failed). 58 min total (14:04–15:02 ET). Every OCR stage except Week6 "succeeded" with a `warning:`; see §3a. |

All automated checks pass.

## 2. What the diff changes (by docket ID)

| Area | IDs | Change |
|---|---|---|
| OCR | 003, NEW-1/2/4/10 | `ingestion.toml` pipeline v6: `batch_pages = 4`, `max_image_pixels = 8e6`, `max_request_image_bytes = 12e6`, transient-only retry with backoff, `max_pages` still 50. Per-batch `generation.operation()`. A boundary mismatch becomes a failure note instead of failing the source; incomplete OCR raises `StageWarning` (stage "succeeded", `error_message = "warning: …"`). Garbled pages queued before blank ones. Tolerant separator regex `(?:\r?\n)+[ \t]*---[ \t]*(?:\r?\n)+`. |
| Text cleanup | NEW-3, 009 | `clean_text` maps CRLF→LF and drops U+FFFE / U+00AD; blank passages are not stored (`rag/store.py`). `structured-v3`. |
| Output control | 004, 029, 038, NEW-5, NEW-7 | New `common/generation.py` + `configs/generation.toml`: one budget per operation (8 calls, 16 HTTP requests, 600 s, 262k requested tokens), empty/length recovery moved from `answer._generate` into the controller. Documents/decks are generated as arrays (`sections[{heading, paragraphs[]}]`, `slides[{title, paragraphs[]}]`, `tutor/materials.py`) and assembled into Markdown. Slide count parsed (1–200, schema min = max = N). MiMo profile shipped. Usage rows get `usage_reported`. |
| Answers / citations | 007, NEW-11 | `Answer.chunk_ids` = cited only (no fallback to all candidates); new `material_chunk_ids` for workspace `[n]`; workspace item sources count as cited. Frontend `materialSources()`; `loadCitations` now iterates the reactive `this.turns`. Reversed ranges `[5-3]` now expand; `arr[0]` is not a citation. |
| Intent | 033 | `_DOCUMENT_REQUEST`: an explicit essay/paper/document/study guide/sheet/notes/outline request wins over a later "table"/"slides". |
| Export | 041, 043 | Workspace doc/sheet export renders through the backend exporter (`/artifacts/export-from-message`) and a native Save dialog (`src-tauri/src/exports.rs`: extension whitelist, replace confirmation, temp + rename). Sheet cells / quiz options are auto-grow textareas. |
| Settings | – | `add_connection` stores the key with rollback; blank key → 422; `.env` quote parsing fixed; `APP_OFFICE_PORT` validated. |
| Other | – | Backend restart button on the startup-error screen, Office add-in hardening (≈600 lines), archive/notebook, downloads, supervisor. |
| **Unchanged** | 001-area, 017–021, 024–028, 030–032, 036, 037, 039, 042, 044–047, NEW-8, NEW-9 | `SourcesPanel.svelte`, `ChatThread`, `tutor/chat.py` limits, `funnel.py` ranking, `secrets.py`, the course-page poll loop and `SlidesView` are untouched (apart from type changes). |

Riley's `docs/docket.md` reconciles round-2 NEW-1..7 as R2-NEW-*; **NEW-8..NEW-11 are not mentioned anywhere in the docket or notes.** Reclassified as enhancements/capabilities: 011, 024, 027, 032, 035, 036, 042, 045, 046, 047, NEW-6.

### 3a. Scratch ingestion detail (MiMo OCR)

| Source | pages | empty | low-quality | OCR'd (r2 scratch → r3) | unresolved | Why unresolved |
|---|---|---|---|---|---|---|
| Week1 | 82 | 15 | 2 | 1 (misattributed) → 6 | 17 | 4 of 5 batches: boundary mismatch (R3-NEW-1) |
| Week2 | 150 | 16 | 3 | 0 (413) → 20 | 19 | 4 batches: boundary mismatch. Reséndez p92–102 **recovered** |
| Week3 | 104 | 27 | 0 | 1 (misattributed) → **0** | 27 | every batch: boundary mismatch; one batch hit 16,384 output tokens |
| Week5 | 191 | 38 | 6 | failed source → 40 | 44 | 2 batches: dropped connection, no retry (R3-NEW-16); 1 mismatch; 50-page cap |
| Week6 | 74 | 0 | 0 | 1 → 1 | 0 | – |

- Text hygiene across 917 chunks: U+FFFE 0, NBSP 0, soft hyphen 0, blank 0. **15 Week5 chunks still contain lone `\r` and C0 controls** (`\x10\x17\x18\x17\r…` inside the cipher text) because `clean_text` only maps `\r\n` (extract.py:409–416).
- OCR ledger: 28+ calls; 4 rows 0/0 with `usage_reported = 0`.
- The Week5 warning string in the stage row is cut at 450 chars; the log line has the rest.

## 3. Per-item status

**Counts (48 STK)** — see the table; recount at the end of §3.

| STK | R2 | R3 status | Evidence (R3) |
|---|---|---|---|
| 001 | Fixed | **Fixed (verified)** | Scratch R3 index: Week1/2/3 max chunk 2,463 / 2,473 / 3,585 chars; segmentation unchanged. |
| 002 | Fixed | Fixed (carried) | `labels.py` unchanged. |
| 003 | Regressed | **Partial** | Batching works: Week2's scanned Reséndez intro (p92–102) is now recovered ("Reséndez" ×5, "THE VERY WORD" ×1; r2: 0), no 413, no source failed. But a 4-page batch whose reply doesn't split into exactly 4 parts is dropped whole, with no retry/split (R3-NEW-1): Week1 17 pages unresolved (4 of 5 batches rejected), Week2 19 unresolved (4 batches rejected), **Week3 27 of 27 unresolved, `pages_ocr = 0`**. |
| 004 | Partial | **Fixed (verified)** | Upstream MiMo profile (16384). Deck/study guide/quiz on MiMo all completed without `length` (55–69 s). |
| 005 | Partial | **Partial** | Garbled pages are now queued first (`extract.assess_pages`, extract.py:478). Week3 glyph digits still corrupt **and undetected**: `independence in 18!1`, `1&!4`, `!()!`, `ba(le`, `o$en`, `A'er`, Alamo `approximately 1,$..`; Week3 `pages_low_quality = 0`. **Week5 Sánchez cipher: mostly repaired** — `pages_ocr = 40` (r2: 0), `pages_low_quality` 38 → 6. The 6 left (p23, 25, 42, 47, 49, 51) are exactly the first two OCR batches, lost to a dropped connection that was not retried (R3-NEW-16); 15 cipher chunks (`,N>KMH.B<:GL;>@…`) are still indexed and retrievable. |
| 006 | Fixed | Fixed (carried) | Treaty replay: "$15 million", 3 Week3 citations, 8.9 s (backend). |
| 007 | Partial | **Fixed in code, needs GUI** | Backend: `chunk_ids` = cited only (answer.py:319–326; Table 2.2 replay: 14 material, 3 cited). The remaining r2 defect was the empty "Sources used" list (NEW-11). |
| 008 | Fixed | Fixed (carried) | – |
| 009 | Partial | **Fixed (verified)** | 0 blank chunks in Week1/2/3 (r2: 79 `"\n"` chunks); thin (<40 alnum) chunks 10/7/8. |
| 010 | Fixed | Fixed (carried) | "disparaged" intact (×2), no U+FFFE. |
| 011 | Not fixed | Not fixed | No change; Riley reclassified it (B-07). |
| 012 | Fixed | Fixed (carried) | – |
| 013 | Code/GUI | Fixed in code, needs GUI | `SourcesPanel` unchanged. |
| 014 | Fixed | Fixed (carried) | Caveat stands: all PDFs typed "notes" (018). |
| 015 | Fixed | Fixed (carried) | (bigger-model resolution is still broken by NEW-9 on keyring-less Linux) |
| 016 | Fixed | Fixed (carried) | – |
| 017 | Partial | **Partial** | No UI change. Poll cap still 600 × 1.5 s (`routes/(app)/courses/[id]/+page.svelte:302`, NEW-8). OCR warnings are not shown (R3-NEW-3). |
| 018 | Partial | **Partial** | All 5 PDFs auto-typed **"notes"** again in R3 scratch. |
| 019 | Partial | Partial | Unchanged (upload order). |
| 020 | Fixed | Fixed (carried) | – |
| 021 | Fixed | Fixed (carried) | Coverage line unchanged; does not mention failed OCR (R3-NEW-3). |
| 022 | Fixed | Fixed (carried) | – |
| 023 | Partial | **Partial (worse behaviour on this run)** | Full corpus, "How many Mexican troops fought at the Alamo?" (49.8 s): the only cited passage reads `In late February of 1$3,, some 1-. Anglo-Texans … against approximately 1,$.. Mexican army troops … su/ered ,.. casualties`. MiMo answered **"some 180 … approximately 1,800 Mexican army troops … about 600 casualties [3]"** as if quoting the reading, with no hint that the digits were decoded from a corrupted text layer (r2: it said the digits were illegible). The decoding is plausible, but nothing in the app flags it; Week3 p40 still has 0 low-quality pages and wasn't OCR'd. |
| 024 | Partial | Partial | Unchanged; Riley calls clickable markers an enhancement. |
| 025 | Not fixed | **Not fixed (verified)** | Full 5-PDF R3 index, "Reproduce Table 2.2": 19 material passages (Week6 6, Week5 6, Week2 5, Week3 2), **none from Week1**, where the table is indexed ("TABLE 2.2" ×1). `funnel.py` only adds an embedding-dimension filter (funnel.py:382, 673); no relevance floor. |
| 026 | Not fixed | Not fixed | No dedup code in `funnel.py`. |
| 027 | Not fixed | Not fixed | No streaming (reclassified). MiMo artifacts now 55–69 s (r2: 28–199 s). |
| 028 | Not fixed | Not fixed | `tutor/chat.py`: `RECENT_MESSAGES = 4`, `FOLLOW_UP_LOOKBACK = 2` unchanged (verified by import). |
| 029 | Partial | Partial | Summary now passes through `strip_fence_echo`; `usage_reported` flag added; summary runaway not re-measured; for reasoning models every task (summary included) now asks for the full 16384 (R3-NEW-7). |
| 030 | Not fixed | Not fixed | `EXCERPT_CHARS = 600` unchanged. |
| 031 | Not fixed | Not fixed | No meta-routing. |
| 032 | Not fixed | Not fixed | Reclassified; no change. |
| 033 | Partial | **Partial** | `classify_intent` replay: "Write a 2-page essay … with a table of key dates" → DOCUMENT ✓ (was SHEET). "Add a column for dates to that table" → ANSWER ✗ (no EDIT intent). New false positive: "Give me the notes from Week 3" → DOCUMENT (R3-NEW-11). |
| 034 | Fixed | Fixed (carried) | 0 NBSP chunks. |
| 035 | Fixed | Fixed (carried) | – |
| 036 | Not fixed | Not fixed | Reclassified. |
| 037 | Not fixed | Not fixed | No grading path. |
| 038 | Not fixed | **Partial** | Real path on MiMo (Week1 index copy): 8-slide deck ✓ (8 slides, 55 s); study guide ✓ (2,692 chars, 69 s). Full corpus: "study guide for the first exam covering Weeks 1-5" ✓ (2,937 chars, 85 s) but content is again exam logistics (039), and it says "four components" then lists three. Section/slide boundaries survive because they are arrays. **But the strict-schema raw reply still has 0 newlines** (`provider.py:437–438` still always `json_schema` + `strict`), so anything multi-line *inside* one paragraph is flattened: bullets become one list item ("- Attend class.  - Read the readings.  - …") and a table becomes one paragraph per row, which `marked` renders as literal pipes (R3-NEW-2). |
| 039 | Not fixed | **Not fixed (verified)** | Full corpus, "Make a 10-question multiple-choice quiz on Week 3": material Week5 6, Week6 5, Week2 4, Week1 2 — **zero Week3 passages** (same as r2); quiz titled "Latinx Politics: Exams and Course Readings", first questions about exam logistics and Reséndez (Week2). `retrieval_topic` still keeps request words: "Make an 8-slide deck on Week 2" → `'8-slide Week 2'`; "Quiz me with 10 questions on Week 3" → `'10 Week 3'`; "Can you make me a one-page cheat sheet?" → `'one-page'`; "Make a 300 slide deck" → `'300'`. The Week1 deck and study guide were mostly syllabus logistics (attendance, grade allocation, office hours). |
| 040 | Fixed | Fixed (verified) | 5-question quiz → exactly 5 (67 s); full-corpus 10-question quiz → exactly 10 (397 s, 2 calls). Counts 0 / 25 return the 1–20 message. |
| 041 | Not fixed | **Fixed in code, needs GUI** | Native Save dialog via `save_export` (`exports.rs:193–240`); browser fallback still `<a download>` (`export.ts:85–92`). See R3-NEW-12 for small oddities. |
| 042 | Not fixed | Not fixed | Pane still exports only `.md` (`EditableDocument.svelte:34,70`) / `.csv` (`SheetView.svelte:28,94`). Reclassified. |
| 043 | Not fixed | **Fixed in code, needs GUI** | `autoGrowTextarea.ts` used by SheetView/SheetEditor/Quiz. |
| 044 | Not fixed | **Not fixed (verified)** | Full corpus: MiMo again says *"The course material provided here does not include Table 2.2 — no passage contains that table"* and lists Table 2.7 instead (16.6 s). With only Week1 indexed (copy DB) the same question reproduced the table perfectly — so this is purely the retrieval miss (025). |
| 045 | Not fixed | Not fixed | `WorkCompanion.svelte` still sends `coverage: 'unknown'` for pastes. Reclassified. |
| 046 | Partial | Partial | `common/config.py:113–115` still falls back to `$HOME` when `~/Downloads` is missing; course export (`api/data.py:81`) has no chooser. |
| 047 | Not fixed | Not fixed | `SlidesView.svelte` only a type change. Reclassified. |
| 048 | Code/GUI | Fixed in code, needs GUI | Unchanged since r2. |

### NEW items from round 2

| ID | R3 status | Evidence |
|---|---|---|
| NEW-1 (OCR error fails source) | **Fixed (verified)** | Week1/2/3 all indexed despite 12+ rejected batches; failure recorded as a stage warning (`orchestrator.py:273–278`). |
| NEW-2 (OCR text on wrong page) | **Fixed (verified)** | Boundaries now either split exactly or the batch is rejected; `\n---\n`, `\n\n---\n\n`, trailing separator all split correctly (scratch repro). No misattribution seen. The price is R3-NEW-1. |
| NEW-3 (U+FFFE / CRLF) | **Fixed (verified)** | R3 index: 0 chunks with U+FFFE, `\r`, NBSP or soft hyphen (r2: 159 / 400 / – ). `clean_text` repro: `"dispar\ufffeaged line1\r\nline2"` → `"disparaged line1\nline2"`. Lone `\r` (CR-only) and C0 controls such as `\x0b`, `\x02` survive (extract.py:409–416) — minor. |
| NEW-4 (unbounded OCR) | **Partial** | Bounded: 4 pages / 12 MB per request, garbled first, incomplete coverage → `warning:`. Still not surfaced to the student (R3-NEW-3); the warning text is cut at 450 chars (`orchestrator.py:299`), so later batch failures disappear from the row. |
| NEW-5 (title-only false positive) | **Partial** | Sections/slides path avoids it. Legacy `content` path still rejects a flattened doc: `_workspace_response({… "content": "# Study Guide ## Exam Essentials - **Date:** …"})` → `None` (compose.py:907, materials.py:17–27). New variant: a section whose only paragraph starts with `### ` ("### Manifest Destiny - the belief that [1]") rejects the whole draft. |
| NEW-6 (shell key overrides .env) | Not fixed (by design) | `_load_dotenv` still doesn't override; Riley lists it as an observation. |
| NEW-7 (no MiMo profile) | **Fixed (verified)** | Profile ships; no `content_filter` seen in R3 (Week1 p21–26 OCR'd fine in probes). |
| NEW-8 (poll cap ~15 min) | **Not fixed** | `routes/(app)/courses/[id]/+page.svelte:302` `attempt < 600`. Week5 OCR alone ran >17 min in R3 scratch, so a 5-PDF upload will again freeze on a stale stage. |
| NEW-9 (no keyring → 503) | **Not fixed (verified)** | `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`: `secrets.get_api_key` logs a full traceback and raises (`secrets.py:28–30`); `GET /api/settings/providers` → **503** (`api/settings.py:177`). New: `providers.add_connection` / `remove_connection` now call `get_api_key` first for rollback (providers.py:253, 334), so they also fail before doing anything. |
| NEW-10 (MiMo OCR did nothing) | **Partial** | Week2 now gets 20 pages OCR'd (incl. Reséndez); full-corpus "What does Reséndez argue about the other slavery?" → correct, 9 Week2 citations (15.6 s; the GUI found nothing in r2). 0/0 rows are now flagged `usage_reported = 0` (4 of 28 OCR rows). But see R3-NEW-1: Week3 0/27 pages, and one Week3 4-page batch burned the full 16,384 output tokens. |
| NEW-11 ("Sources used" empty) | **Fixed in code, needs GUI** | `chat.svelte.ts` `openConversation` now calls `loadCitations` on `this.turns` (reactive proxies) instead of the raw array — fixes the reopen path. The in-session `send()` path already used the proxy, so if the r2 failure was in-session it is not explained by this change. |

## 4. New bugs and oddities introduced by d98d365

1. **R3-NEW-1 (high): the OCR prompt and the splitter disagree about blank pages, so most OCR batches are thrown away.**
   - The prompt says *"If a page has no legible text, emit nothing for it between the separators"* (`configs/prompts.toml:307–308`). That produces `---\n---\n…`, which `split_ocr_pages` cannot split: the first match consumes the shared newline (`ingest/ocr_pages.py:15`).
   - Captured from MiMo on Week1 p27, 28, 33, 34 (twice, `probe/ocr_27_28_33_34_*.json`): `'---\n---\nCANVAS\n---\nFOURTH EDITION\nLATINO POLITICS IN AMERICA…'` → `ValueError: OCR page boundaries do not match`.
   - Scratch repro (no LLM):
     ```python
     split_ocr_pages("A\n---\n---\nC\n---\nD", 4)      # ValueError (blank page 2)
     split_ocr_pages("---\nB\n---\nC\n---\nD", 4)      # ValueError (blank page 1)
     split_ocr_pages("A\n\nintro\n\n---\n\nmore A\n---\nB\n---\nC\n---\nD", 4)  # ValueError (a Markdown rule inside a page)
     ```
   - Other observed shapes: only 2 separators for 4 pages (Week1 p46/48/59/60), and model-added `**Page 1:**` labels (these split fine but the label is indexed as page text).
   - The rejection is final: no retry, no per-page fallback (`ingest/orchestrator.py:273–278`, by design "no deterministic re-billing"). Yet re-sending the rejected Week1 batches succeeded in 3 of 6 probe calls, so the outcome is a coin flip per batch.
   - **Effect in R3 scratch:** Week1 17 pages unresolved (4/5 batches rejected), Week2 19 (4 batches), **Week3 all 27 unresolved, `pages_ocr = 0`**.
   - **Fix:** accept empty segments (`(?:^|\n)[ \t]*---[ \t]*(?=\n|$)` on a split that keeps empties), tell the model to write `[blank]` for empty pages, and on a mismatch retry the batch one page per request.
2. **R3-NEW-2 (high): structured paragraphs break tables and bullets in generated documents/decks.**
   - MiMo under strict `json_schema` still drops every newline in strings (raw replies: 0 `\n`). Sections/slides survive because they are arrays, but a paragraph that should be a list or a table is flattened or split.
   - Study guide replay: `"- Attend class.  - Read the readings.  - Turn in your name card…"` (one bullet) and a grade table emitted as one paragraph per row, joined with blank lines by `Section.markdown()` (`tutor/materials.py:51–54`).
   - `marked` repro: `'| Component | Weight |\n\n|---|---|\n\n| Attendance | 20% |'` → three `<p>` of literal pipes; the bullets → one `<li>`.
   - Root cause: strict `json_schema` is still unconditional (`common/provider.py:437–438`); no per-model `json_object` / no-schema mode. (In r2, `json_object` on MiMo was 17.5 s with newlines intact.)
3. **R3-NEW-3 (medium): OCR warnings never reach the student.**
   - The warning lives only in `ingestion_stage_runs.error_message` and the log. `source_indexes.warning` is NULL for Week1 despite 17 unresolved pages; `sources.error_message` is NULL; `SourcesPanel.svelte:83–93` `coverage()` doesn't show `pages_ocr` or failures. Week3 reads as "27 pages had no text" whether OCR was tried or failed.
4. **R3-NEW-4 (low): the operation deadline discards a successful result.** `generation.complete` calls `op.remaining_seconds()` *after* a successful `invoke()` (`common/generation.py:255`), so a reply that finishes after 600 s is thrown away as "took too long" even though it was billed.
5. **R3-NEW-5 (low): reasoning models ignore the per-task output sizes.** `desired = preferred if thinking else min(...)` (`generation.py:76`): with the MiMo profile, conversation summaries (1024) and tutor answers (2048) all request 16,384 tokens and reserve that against the 262k budget.
6. **R3-NEW-6 (low): reversed citation ranges are now valid.** `cited_numbers("see [5-3]")` → `{3,4,5}` (`common/citations.py:88–90`); previously rejected. Probably harmless, but it makes an obviously malformed marker pass the out-of-range guard.
7. **R3-NEW-7 (low): `has_body` / heading handling in drafts.**
   - A paragraph that starts with `#`–`######` + space counts as a heading, so a single-line "### Key term – definition [1]" paragraph rejects the whole document (`materials.py:17–27`).
   - `lstrip("# ")` eats leading `#` from real headings: "#1 Priority: land" → "## 1 Priority: land" (`materials.py:53`, `97`).
   - Document title >120 chars rejects the whole draft (`materials.py` `DocumentDraft.title`, strict).
8. **R3-NEW-8 (low): quiz repair aborts instead of degrading.** A non-schema error during a repair call now re-raises (`tutor/compose.py:1055`), so a budget/provider error discards questions already verified (the r2 code fell back to `repaired = ""`).
9. **R3-NEW-9 (low): slide counts up to 200 are accepted** (`compose.py:964`), with schema min = max = N, although 200 slides cannot fit a 16,384-token reply; the user gets a generic failure after the full budget.
10. **R3-NEW-10 (low): OCR cost/runaway.** One Week3 4-page OCR call returned exactly 16,384 output tokens (reasoning runaway) and was then dropped; 4 OCR ledger rows are 0/0 with `usage_reported = 0` (quick failures at 14:04:18, 14:04:22, 14:21:34, 14:30:08 ET).
11. **R3-NEW-11 (low): intent false positive.** "Give me the notes from Week 3" / "give me notes on Week 3" → DOCUMENT (generates a new document instead of pointing at the uploaded notes) (`compose.py:135–143`).
12. **R3-NEW-12 (low): export oddities** (needs GUI to confirm).
    - Typing a filename without the extension in the Linux save dialog gives an error ("Choose a destination ending in .md") instead of appending it (`exports.rs:211–217`).
    - GTK's own overwrite prompt plus the app's "Replace the existing file?" may ask twice (`exports.rs:219–231`).
    - Export bytes cross IPC as a JS `number[]` (`export.ts:104`), ~4–8× the file size in JSON; fine for `.md`/`.csv`, slow for large files.
13. **R3-NEW-13 (medium): quiz answer keys are not shuffled — the full-corpus 10-question quiz has every answer = option A** (`answer` 0 ×10; the Week1 5-question quiz had 0,0,1,0,3). Nothing in `compose.py`/`_usable_quiz_questions` permutes options, so a student can score 100% by always picking A. Also content oddities: The deck contains a malformed marker `[12)` that passes untouched (citation regex doesn't see it) and a sentence cut mid-passage ("…differences and similarities in the [11]"). 
14. **R3-NEW-14 (low): `retrieval_topic` keeps count words** — listed under STK-039.
15. **R3-NEW-15 (low): NEW-8..NEW-11 are absent from `docs/docket.md` / `docs/notes.md`**, so two of them (NEW-8 polling, NEW-9 keyring) have no owner.
16. **R3-NEW-16 (medium): OCR retry decides "transient" by matching English message text.** `ingest/pipeline.py:121–134` only retries `ProviderUnavailableError`s whose message contains "could not reach" / "did not answer in time" / "had a server error" / "could not answer:". A dropped connection (`httpx.RemoteProtocolError`, wrapped as "…sent a reply Stacks could not read…: peer closed connection without sending complete message body", `common/provider.py:607`) is not retried. In R3 scratch this killed **Week5's first two batches — the cipher pages 23, 25, 42, 47, 49, 51** (the very pages the new garbled-first ordering was meant to save) after 1 attempt each. Any rewording of a provider message silently changes retry behaviour.
17. **R3-NEW-17 (low): a provider refusal is treated as model text.** The first full-corpus quiz call returned the content `"The request was rejected because it was considered high risk"` (MiMo moderation) with HTTP 200; Stacks parsed it as a bad draft and spent a repair call (397 s total). In a `tutor_answer` the same string would be shown to the student as the answer. `provider.py` has no check for refusal text (finish_reason was not captured by my wrapper).

## 5. Counts

**STK-001..048**

| Status | Count | IDs |
|---|---|---|
| Fixed (verified this round) | 4 | 001, 004, 009, 040 |
| Fixed (carried from r2, code unchanged) | 13 | 002, 006, 008, 010, 012, 014, 015, 016, 020, 021, 022, 034, 035 |
| Fixed in code, needs GUI check | 5 | 007, 013, 041, 043, 048 |
| Partial | 11 | 003, 005, 017, 018, 019, 023, 024, 029, 033, 038, 046 |
| Not fixed | 15 | 011, 025, 026, 027, 028, 030, 031, 032, 036, 037, 039, 042, 044, 045, 047 |
| Regressed | 0 | (003 moved from Regressed to Partial) |

**NEW-1..11:** Fixed (verified) 4 (NEW-1, 2, 3, 7) · Fixed in code/needs GUI 1 (NEW-11) · Partial 3 (NEW-4, 5, 10) · Not fixed 3 (NEW-6 by design, NEW-8, NEW-9).

**Round-3 new issues:** 15 (2 high, 1 medium, 12 low/oddities), §4.

## 6. GUI-check list

1. **STK-041 / R3-NEW-12:** Workspace document `.md` and sheet `.csv` export → native Save dialog opens; cancel is silent; typing a name without extension; overwriting an existing file (one or two prompts?); the saved path is shown; file contents match the unsaved draft and include the source legend.
2. **STK-043:** Long and multi-line sheet cells wrap and grow (workspace + saved sheet + quiz options); Enter / Shift+Enter / Alt+Arrow behave as documented; narrow companion pane.
3. **NEW-11 / STK-007:** Ask the Alamo question; expand "Sources used (n)" **in the same session** and again after reopening the chat. Both should list the cited passages.
4. **R3-NEW-2:** Generate a study guide with a table on MiMo → check whether the table renders as a table or as lines of pipes; check bullets.
5. **STK-038:** 8-slide deck → 8 slides navigable in `SlidesView`; document opens in `EditableDocument`.
6. **R3-NEW-3 / STK-017 / STK-021:** Upload the 5 PDFs → does anything tell the student that OCR failed for some pages? Coverage line wording for Week3 (27 pages, 0 OCR'd).
7. **NEW-8:** Same upload → after ~15 min does the panel freeze on a stale stage while the backend finishes? (Week5 OCR alone took >17 min here.)
8. **NEW-9:** Course page and Settings → Models on this keyring-less box → model label/picker and providers list (expected: still broken, 503).
9. **STK-013 / 018 / 019 / 020:** pending rows, Auto type (expect "Notes" for every PDF), list order, reindex menu.
10. **STK-048:** chat B's practice quiz doesn't show chat A's teaching event.
11. **STK-046:** course export notice/path; behaviour when `~/Downloads` is missing.
12. Startup-error screen: new "Try again" restarts the backend (`+layout.svelte`), only reachable by forcing a backend failure.

## 7. Repro commands

```bash
cd /workspace/Stacks-r3
# OCR splitter (no LLM)
env -u LLM_API_KEY PYTHONPATH=. .venv/bin/python -c 'from src.backend.ingest.ocr_pages import split_ocr_pages as s; s("A\n---\n---\nC\n---\nD",4)'   # ValueError
# keyring 503
env -u LLM_API_KEY PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring APP_DATA_DIR=/tmp/kr DATABASE_PATH=/tmp/kr/db.sqlite APP_API_TOKEN=t PYTHONPATH=. \
  .venv/bin/python -c 'from fastapi.testclient import TestClient; from src.backend.main import app
with TestClient(app) as c: print(c.get("/api/settings/providers", headers={"Authorization":"Bearer t"}).status_code)'   # 503
# marked rendering of split table rows
cd src/frontend && node --input-type=module -e "import {marked} from 'marked'; console.log(marked.parse('| a | b |\n\n|---|---|\n\n| 1 | 2 |'))"
# MiMo replays (real api.tutor.ask path; results in r3-scratch/ask-results.json)
cd /workspace/Stacks-r3 && env LLM_API_KEY="$XIAOMI_API_KEY" APP_DATA_DIR=/workspace/stacks-test/r3-scratch/data \
  DATABASE_PATH=/workspace/stacks-test/r3-scratch/data/course_assistant.db PYTHONPATH=. .venv/bin/python /workspace/stacks-test/r3-scratch/ask.py "Reproduce Table 2.2"
# raw OCR of one batch (writes r3-scratch/probe/ocr_<pages>_<ts>.json; uses probe/probe.db for the ledger)
env LLM_API_KEY="$XIAOMI_API_KEY" APP_DATA_DIR=/workspace/stacks-test/r3-scratch/data DATABASE_PATH=/workspace/stacks-test/r3-scratch/probe/probe.db PYTHONPATH=. \
  .venv/bin/python /workspace/stacks-test/r3-scratch/probe/ocr_raw.py 16a464db-0d15-4632-a2ea-c821d44d92a3 27,28,33,34
```

Nothing was changed in Riley's remote, in Stacks-r2, or in the running r2 app. `git status` in `/workspace/Stacks-r3` is clean (`.env` and build outputs are gitignored; the regenerated API types matched the commit).
