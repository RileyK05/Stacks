# Stacks: round-5 retest (7b29e3d..44503f0)

- **Date:** Sun Oct 11, 2026, from 09:36 ET (code-level + scratch replays; no GUI driven).
- **Tester:** Grok Bot (executor) for Riley K.
- **Commit:** 44503f0 "Fixes done!" (Oct 8 18:43 ET, HEAD of origin/main). 41 files, +1938/−189 vs 7b29e3d. Riley's remote was not touched.
- **Worktree:** `/workspace/Stacks-r5`, detached at 44503f0, own `.venv` / `node_modules` / `target/`. Stacks-r2 untouched.
- **LLM:** `.env` copied from r4 (MiMo `mimo-v2.6-flash`, `https://token-plan-sgp.xiaomimimo.com/v1`, key = `$XIAOMI_API_KEY`, mode 600); every MiMo run also sets `LLM_API_KEY="$XIAOMI_API_KEY"` explicitly.
- **Scratch:** `/workspace/stacks-test/r5-scratch/` (course `a92fcc58-…`, same 5 PDFs, ingestion started 09:37 ET).
- **Environment:** the box was reset again since r4: Rust toolchain ("no installed toolchains"), `pkg-config` + Tauri dev libraries, and the Stacks-r4 `.venv` / `node_modules` were all gone. Reinstalled: `rustup default stable`, apt `pkg-config libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev libssl-dev libsoup-3.0-dev libjavascriptcoregtk-4.1-dev libxdo-dev` (apt exit 100 only because `fuse3`/`xdg-desktop-portal` hit an interactive conffile prompt; all dev packages installed), fresh `.venv` + `npm ci`.

> **Status:** complete (11:28 ET). Code-level + API/scratch replays; nothing in the GUI was driven. Sections were filled in by two interrupted workers and a third that finished §3a numbers, §3b r5-corpus replays, the rest of §4, and §3/§5/§6/§7.

## 1. Check results

| Check | Result |
|---|---|
| `pip install -e ".[desktop,dev]" -c constraints.txt` (new `.venv`) | OK |
| `npm ci` | OK |
| Keyring-less box (`PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`) → `GET /api/settings/providers` | 200 (NEW-9 still fixed) |
| `pytest` (`env -u LLM_API_KEY python -m pytest -q`) | **1144 passed**, 0 failed, 1 warning (125 s); r4: 1109 |
| `ruff check` / `ruff format --check` | pass / 245 files formatted |
| `mypy src` | no issues (151 files) |
| API types regen (`python -m scripts.dump_openapi runs/openapi.json` → `OPENAPI_FILE=… npm run gen:api`) | OK; no git diff |
| `npm run check` (svelte-check) | 0 errors, 0 warnings |
| `npm test` | **36/36** (unchanged count) |
| `npm run build` | OK (chunk-size advisory only) |
| `cargo check` / `clippy --all-targets -D warnings` / `cargo test` | OK / OK, 0 warnings / **4/4** (r4 3/3; new `export_path` test). Toolchain + Tauri libs had to be reinstalled (see header). |
| Scratch ingestion (5 PDFs, MiMo OCR) | All 5 indexed, 92 min (09:37–11:09 ET), 955 chunks; details §3a |

## 2. What the diff changes (by docket ID)

| Area | IDs | Change |
|---|---|---|
| OCR split | R4-NEW-d, R3-NEW-1 | `split_ocr_pages` returns the whole text when `expected == 1`; drops one leading empty part. |
| OCR refusal | R4-NEW-l, R3-NEW-17 | A refusal is retried within `ocr_max_attempts`, then the batch falls back to `_recognize_single_page` (`@generation.operation(fresh=True)`, own budget, R4-NEW-e). |
| OCR warning | R4-NEW-m, NEW-4 | `_warn_if_incomplete` rewritten: plain sentences ("were declined by the reading model", "could not be read after N attempt(s)", "have only a little text to index", "only the first 50 pages were read"), pages sorted; `sources.sql` strips the `warning: ` prefix. The 450-char cap was removed. |
| Text hygiene | R4-NEW-k | `clean_text`: lone `\r` → `\n`, C0/C1 controls except tab/newline removed; `page_quality` clamped; `read_decoded` keeps `\x00` for UTF-16/32; `structure._heading_start` word boundary. |
| Provider | R4-NEW-a, R4-NEW-f | `_REFUSAL_RE` anchored to the whole reply + `finish_reason == "content_filter"`; malformed replies non-transient, JSON decode errors transient; 400-adaptation loop bounded at 4. |
| Generation | R4-NEW-q | Per-task `reasoning_multiplier` (default 4; `tutor_answer` 6 → 12,288 on MiMo); `operation(fresh=True)`. |
| Intent / topic | R4-NEW-g, R3-NEW-14 | SLIDES matches `\bdeck\b`; `_WORD` keeps "2.2"; `_NUMBERING_HEADS` / `_SIZE_UNITS` decide which numbers to keep. |
| Quiz shuffle | R4-NEW-b | "All/None of the above" → "All/None of these choices"; "Both A and B" → "Both: X and Y"; remaining positional options pin the order; `_relettered` rewrites "Option A" in explanations; prompts ban all/none/both and letter references. `_usable_quiz` answer-in-prompt check uses whole words. |
| Drafts | R3-NEW-2, STK-038, R4-NEW-i | `materials._reflowed` splits paragraphs on `<br>` / newlines, strips each line, rejoins with `\n`, merges consecutive table-row paragraphs into one table; `has_body` treats a <3-word unpunctuated line as a label. |
| Critique | R4-NEW-n, R4-NEW-h | `validate_findings` drops bad findings, raises only if none survive; `_names_fallacy` uses `_related` (4-char overlap); `_ADVICE` exempts questions (how/what/why/"can you help…"). |
| Companion | R4-NEW-p | `document_context` ranks sections with rarity weighting + `_heading_words`. Selection match / `WorkCompanion.svelte` unchanged. |
| Exam-style | R4-NEW-o | Empty `prompt` takes `stem`; prompt defines `prompt`; PIL lock. |
| Grading | R4-NEW-c, STK-037 | Rewritten: order-sensitive claims, number words / `$15M` / `15,000,000` canonicalized, acronyms (U.S./US), clause-scoped negation. |
| Export | R4-NEW-j | `exports.rs` `export_path` appends to unknown dotted names, replaces known extensions; new test. |
| Other | – | graph/edges (drops `row[j] > 0`, floor is 0.78 so harmless), body_limits, migrate, prompt_registry, `secrets.delete` idempotent, storage, segment, serve, trace, archive, rerank `bound_passages`, funnel `overview` spread. |
| Docs | R3-NEW-15 | `docs/RETEST-round4.md` (my r4 report) is now committed; `docs/notes.md` adds round-4 fix notes and "CR-*" items. `docket.md`/`review.md` still absent. |
| **Unchanged** | 025/044, 039, 033, C-1, C-3..C-8, 045, 042, 047… | Retrieval ranking (only `overview`), EDIT intent, `WorkCompanion.svelte`, selection exact-match, `SlidesView`/`EditableDocument`/`SheetView`, `chat.py` constants. |


### 3a. Scratch ingestion detail

MiMo OCR, 09:37–11:09 ET, **92 min** (r4 80). `process_batch` → `(5, 5)` in 5,492 s; all 5 sources indexed; all auto-typed **notes** (STK-018).

| Source | pages | empty | low-q | OCR'd r4 → **r5** | blank-unresolved + thin (r5) | r4 "unresolved" | Why unresolved (r5) |
|---|---|---|---|---|---|---|---|
| Week1 | 82 | 5 | 2 | 11 → **18** | 4 + 3 thin = 7 | 13 | No batch lost. p27/28/46/66 cover/photo pages; p14 (Table 2.2), 34, 80 "only a little text". |
| Week2 | 150 | 8 | 5 | 25 → **30** | 6 + 7 thin = 13 | 18 | No batch lost (Reséndez p95–98 now read: "Reséndez" ×5 / "Resendez" ×3 in the index). |
| Week3 | 104 | 18 | 4 | 7 → **11** | 16 + 6 thin = 22 | 23 | **Batch p58/59/61/62 lost to a `RemoteProtocolError` twice (10:16→10:24 ET), no per-page fallback** (R5-NEW-o). Digit-glyph corruption untouched. |
| Week5 | 191 | 40 | 0 | 47 → **43** | 40 listed (20 shown + "+20 more") | 36 | 50-page cap; **batch p107/108/109/112 lost to the operation deadline ("Preparing this response took too long…") twice, no per-page fallback** (R5-NEW-o) — 4 fewer OCR'd pages than r4. Cipher still repaired (low-q 0). |
| Week6 | 74 | 0 | 0 | 1 → 1 | 0 | 0 | – |

- Chunks: 154 / 200 / 166 / 292 / 143 = **955** (r4 937). U+FFFE 0, `\r` 0, NBSP 0, soft hyphen 0, blank 0, **C0/C1 control chars 0** (R4-NEW-k), U+2028 0. Week3 still has `18!1` ×3, `1&!4` ×1, `!()!` ×22, `1$!4` and the Alamo `1,$..` sentence (STK-005/023).
- **Table 2.2 is now indexed** (Week1: 47-char title chunk "TABLE 2.2 Race of Major Hispanic Ancestries" + 1,506-char Markdown table chunk + source note, R5-NEW-m).
- Ledger: **52 OCR calls**, 125,204 in / 234,667 out tokens. **5 rows 0/0 `usage_reported = 0`** (13:37:37, 13:38:45, 13:50:44, 14:16:31, 14:31:40 UTC = 09:37–10:31 ET) = MiMo refusals — **none of them cost pages this time** (Week1/Week2 have no failure note): R4-NEW-l fixed in practice. 7 calls ended at ≥ 8,192 output tokens (8,192 ×5, 8,260, 9,461 — the per-page fallback runs with its own budget).
- Failures that reached the warning (both are **transient** errors, not refusals, so the new per-page fallback never ran): Week3 `RemoteProtocolError` ×2 (~8 min each), Week5 operation deadline ×2.
- **Student-facing warnings** (`sources.sql` strips `warning: `; `GET /sources` shows the rest):
  - Week1 (82 chars): `unresolved pages 27, 28, 46, 66; pages 14, 34, 80 have only a little text to index`
  - Week2 (117 chars): `unresolved pages 111, 114, 139, 141, 143, 144; pages 1, 110, 120, 121, 123, 127, 146 have only a little text to index`
  - Week3 (364 chars): `unresolved pages 58, 59, 61, 62, 63, … 98; pages 71, … 96 have only a little text to index; pages 58, 59, 61, 62 could not be read after 2 attempt(s): Development endpoint sent a reply Stacks could not read (mimo-v2.6-flash): peer closed connection without sending complete message body (incomplete chunked read)`
  - Week5 (320 chars): `unresolved pages 93, 107, 108, … 151, ... (+20 more); only the first 50 pages were read; pages 107, 108, 109, 112 could not be read after 2 attempt(s): Preparing this response took too long. Try a more focused request or choose a faster model`
  - Better than r4 (no prefix, sorted, short/blank split, no "pick another model" on refusals, page lists capped at 20 + "(+N more)" so R5-NEW-j is bounded in practice). Still: "unresolved" is jargon, failed pages are listed twice (in "unresolved" and in "could not be read"), and the raw endpoint/httpx text and chat-oriented advice ("Try a more focused request or choose a faster model") reach the student (R5-NEW-o, R4-NEW-m partial).

### 3b. MiMo replays

**Generation replays on a copy of the r4 full corpus** (`r5-scratch/r4corpus/`, r5 code, answer cache cleared; started ~10:00 ET while the r5 ingestion ran). Retrieval code is unchanged apart from `overview`, so the r4 corpus is a fair test for generation/rendering; Table 2.2 / Week 3 retrieval are re-run on the r5 corpus below.

| Request | Time | Result |
|---|---|---|
| "How many Mexican troops fought at the Alamo?" | **185 s** (r4 239 s) | One `tutor_answer` call, 7,708 in / **8,052 out** — under the new 12,288 cap, so it was kept (r4: 8,192 truncated + discarded + second call). Answer: "approximately 1,800 Mexican army troops… about 600 casualties [3]" with a note that the digits render as "1,$.." / "1$3,," in the extracted text and were read from context. R4-NEW-q fixed (no discard), but the answer still burns ~8k reasoning tokens and 3 min. |
| "How much did the United States pay Mexico under the Treaty of Guadalupe Hidalgo?" | 8 s | ✓ "$15 million" [1][3] + quote. |
| "Create a study guide on the US-Mexico War with a table of key dates and a bulleted list of key terms" | 264 s (r4 453 s) | **Table fixed:** MiMo again sent each row as its own paragraph; `_reflowed` merged them, `marked` (app options) renders **1 `<table>`, 10 rows**, 0 pipe paragraphs (r4: 13 `<p>` of pipes). **Bullets now broken differently:** the Key Terms paragraph arrives as one string with bullets glued by nothing — `…manifest destiny [10].- **Annexation of Texas** — …[5].- **Rio Grande…` (0 newlines, 0 `<br>`) → renders as **1 `<li>`** (R5-NEW-k). |
| "Create a study guide for the first exam covering Weeks 1-5" | 134 s | ✗ **No document at all**: reply "Here is a study guide for the first exam…" with `withheld = ['workspace block is not valid JSON']`. MiMo's reply was valid JSON (4,082 chars, `json.loads` OK) but used **U+2028 LINE SEPARATOR** between bullets (`…[1][9]. \u2028- Format: … \u2028- Conditions: …`). `strip_fence_echo` (`common/prompt_registry.py:96–101`) does `text.splitlines()` + `"\n".join`, which turns each U+2028 inside the JSON string into a raw newline → invalid JSON → the whole guide is withheld, and the repair path never runs because `_workspace_response` already succeeded (R5-NEW-l, high). Material: Week1 6, Week5 5, Week3 1 (still mostly logistics, STK-039). |
| "Make a 10-question multiple-choice quiz on Week 3" | 193 s | 10 questions ✓. **Answer key `[2,3,3,3,2,1,2,1,3,2]`** (varied ✓). No all/none/both options, no letter references in explanations (they quote the option text) — the prompt change works on this run (R4-NEW-b). ✗ Retrieval unchanged: material Week2 8, Week1 5, Week5 2, **Week3 1** (the "Coming Up" slide) → 5 logistics questions (office hours, exam date, readings) + 5 Week2 Reséndez questions (STK-039). |

**Full r5 corpus (`r5-scratch/data`, 11:17 ET, `r5-scratch/ask.py`, results `r5-scratch/ask-results.json`):**

| Request | Time | Result |
|---|---|---|
| "Reproduce Table 2.2" | 15 s | ✗ **"Table 2.2 is not in the course material… the excerpts here skip past it"**; lists Tables 2.7 / 2.1 / 4. Material: 20 passages = Week5 12, Week6 6, Week3 2, **Week1 0**; none of the 3 Table 2.2 chunks (title, Markdown table, note) was retrieved although the page is now OCR'd and indexed, and a plain FTS phrase query `"table 2.2"` on `chunks_fts` returns exactly those 3 chunks. `retrieval_topic` keeps "Reproduce Table 2.2" whole (R4-NEW-g half fixed), so the loss is in ranking (`retrieval/funnel.py`, unchanged apart from `overview`). STK-025/044 not fixed (verified on the r5 corpus). |
| "Make a 10-question multiple-choice quiz on Week 3" | 210 s | 10 questions ✓, key `[0,2,3,1,1,1,1,2,1,3]` (varied ✓), no all/none/both options, no letter references ✓. ✗ Material Week2 9, Week1 5, Week5 2, **Week3 1** (166 Week3 chunks exist) → 5 logistics questions (schedule date, office hours, exam date/weight, where readings are) + 4 Reséndez (Week2) + 1 Week1. STK-039 not fixed (verified on the r5 corpus). |

**Exam-style practice (R4-NEW-o), live on MiMo** (`r5-scratch/companion/exam*.py`, r5 code on a copy of the r4 companion DB): three earlier attempts in this round all returned **503**:
1. 09:55–09:59 ET, 290 s: OCR 746/808 ✓, profile 444/217 ✓, **question-writing call 6,424 in / 16,384 out = hit the output cap** → "Development endpoint (mimo-v2.6-flash) hit its output limit before finishing. Try one section at a time or pick another model." (R5-NEW-s).
2. 10:10 and 10:18 ET (debug run): the OCR call on the quiz image died with `RemoteProtocolError` (peer closed connection) after ~8 min → 503 with the raw httpx text; exam-style has no retry for a transient error (R5-NEW-s).
3. 10:26 ET, 500 s: same OCR `RemoteProtocolError`.

**Code-level replay (no LLM):** r4's captured MiMo reply (5 questions, question text in `stem`, no `prompt`; `r4-scratch/companion/exam-debug.json`) fed to r5 `accept_questions` with the same profile and `_passages` candidates (18) → **5/5 accepted** (r4: 0). The stem→prompt fallback (`exam_style.py:486–488`) plus the new prompt line fix R4-NEW-o in code; a successful end-to-end run on MiMo was not observed.

**Live rerun (11:18–11:27 ET, `companion/exam3.py` → `exam-result-3.json`):** 503 after **497 s**, the same OCR `RemoteProtocolError` on the quiz image. So 3 of 4 runs this round died on that one OCR call after ~8 min each (the same image OCR'd in 18 s in r4/run 1), and no ledger row is written for the failed calls. Exam-style is 0/4 end-to-end on MiMo this round.

### Companion repro detail (MiMo, r5 code on a copy of the r4 companion DB, `r5-scratch/companion/`)

Same script as r4 plus "Improve my conclusion…", a third critique, and a critique with "Can you help me rewrite this paragraph?". Results in `r5-scratch/companion/results.json`.

| Step | HTTP | Time | Result (r4 → r5) |
|---|---|---|---|
| Connect docx | 200 | 0.1 s | Still `coverage: "partial"` with the two fixed warnings (C-5). |
| Summarize docx | 200 | 21 s | Good; sections 1, 2, 3, 28 of 31, honest scope note. |
| Suggest an edit, selection = 4-sentence LBJ paragraph ("we" → passive) | **422** | 54.5 s | **"The answer contained an unsupported source reference. Try again."** (C-4 reproduced; r4: 200 with 1-of-4-sentence edit). `tutor/work.py:398–411` rejects a revise/explain reply that has course citations available but cites none (`citations and action in {review, revise, explain} and not numbers`) or cites a number outside the list — a pure style edit of the student's own paragraph has nothing to cite. In the desktop UI this leaves the request pending (C-1). |
| Custom "Improve my conclusion so it is more persuasive." | 200 | 58 s | Sections 2, 3, 4, **28** (Conclusion) ✓; bounded edit of one conclusion sentence, honest scope note. |
| Custom "Rewrite the introduction paragraph…, preserving all numbers." | 200 | 27 s | **Fixed (R4-NEW-p):** sections **1**, 6, 20, 27; edited the actual Introduction ("This paper analyzes 87 State of the Union addresses… 1934 to 2024"), numbers preserved. |
| Critique #1 / #2 / #3 (score 50, research), unchanged draft | **200 / 200 / 200** | 83 / 183 / 181 s | **Fixed (R4-NEW-n):** 5 / 5 / 3 findings (r4: 422 twice). Findings are substantive and quote the draft exactly. Each run sees only 4 of 31 sections (1, 10, 20, 31 / 1, 2, 3, 31), so different runs critique different parts. Slow (up to 3 min). |
| Critique "Can you help me rewrite this paragraph?" | 200 | 173 s | Not refused (R5-NEW-i) but the reply is still a critique (4 findings), no rewrite. Harmless here. |
| Critique "How should I write my conclusion section?" | 200 | 112 s | **R4-NEW-h fixed** (accepted). But the findings are not about the conclusion (first one is a Bush/Iraq sentence), and one feedback starts with the raw label **"unsupported_claim: …"** (snake_case leaked to the student, low). |
| Connect xlsx | 200 | 0 s | Unchanged: `A1=…; B1=…` cell dump + "no shared strings part" warning (C-3). |
| Summarize xlsx | 200 | 19 s | Answered from the xlsx ✓ (C-2 not reproduced again). |
| Explain, selection = the same cells pasted tab-separated | **422** | 0 s | Unchanged: "The selected passage is not in the connected document snapshot." (C-1 trigger). |

## 3. Per-item status

Legend: "verified" = observed in this round's scratch run, replay, or a no-LLM repro; "carried" = code unchanged since it was verified; "needs GUI" = only the desktop app can confirm.

| STK | R4 | R5 status | Evidence (R5) |
|---|---|---|---|
| 001 | Fixed | Fixed (carried) | Segmentation unchanged (only an empty-window guard in `segment.py`). |
| 002 | Fixed | Fixed (carried) | `labels.py` unchanged. |
| 003 | Partial | **Partial (improved)** | `pages_ocr` W1 **18** / W2 **30** / W3 **11** / W5 43 (r4 11/25/7/47). 5 MiMo refusals cost **0 pages** (R4-NEW-l fixed). Still lost: 2 batches of 4 to *transient* errors (W3 p58–62 `RemoteProtocolError`, W5 p107–112 deadline), no per-page fallback (R5-NEW-o). |
| 004 | Fixed | Fixed (verified) | All artifacts complete; Alamo answer used 8,052 of 12,288 tokens, no discard. |
| 005 | Partial | Partial | W5 cipher still repaired (low-q 0). W3 glyph digits still corrupt and unflagged (`1$!4`, `18!1` ×3, `!()!` ×22, Alamo `1,$..`). |
| 006 | Fixed | Fixed (verified) | Treaty → "$15 million" [1][3], 8 s. |
| 007 | Fixed in code, needs GUI | Fixed in code, needs GUI | Unchanged. |
| 008 | Fixed | Fixed (carried) | – |
| 009 | Fixed | Fixed (verified) | 0 blank chunks in 955. |
| 010 | Fixed | Fixed (verified) | "disparaged" ×2, U+FFFE 0. |
| 011 | Not fixed | Not fixed | No dedup change. |
| 012 | Fixed | Fixed (carried) | – |
| 013 | Fixed in code, needs GUI | Fixed in code, needs GUI | – |
| 014 | Fixed | Fixed (carried) | – |
| 015 | Fixed | Fixed (verified) | Keyring-less `GET /api/settings/providers` → 200. |
| 016 | Fixed | Fixed (carried) | – |
| 017 | Fixed in code, needs GUI | Fixed in code, needs GUI | Polling unchanged; warning text improved (§3a). |
| 018 | Partial | **Partial (verified)** | All 5 PDFs auto-typed "notes" again. |
| 019 | Partial | Partial | Unchanged (upload-order sort). |
| 020 | Fixed | Fixed (carried) | – |
| 021 | Fixed | Fixed (carried) | – |
| 022 | Fixed | Fixed (carried) | – |
| 023 | Partial | **Partial (mixed)** | Alamo answer now gives "approximately 1,800 … about 600 casualties [3]" again, with a note that the digits render as `1,$..` and were "read from context" — a hedged guess (r4 refused to give a number). Text layer still corrupt. 185 s. |
| 024 | Partial | Partial | Unchanged. |
| 025 | Not fixed | **Not fixed (verified, r5 corpus)** | Table 2.2 is now indexed (3 Week1 chunks; FTS `"table 2.2"` finds them) but "Reproduce Table 2.2" retrieves **0 Week1** passages and says it isn't in the material. |
| 026 | Not fixed | Not fixed | `funnel.py` only changes `overview`. |
| 027 | Not fixed | Not fixed | No streaming. |
| 028 | Not fixed | Not fixed | `chat.py` untouched (`RECENT_MESSAGES = 4`). |
| 029 | Partial | Partial | Unchanged. |
| 030 | Not fixed | Not fixed | `EXCERPT_CHARS = 600` (untouched). |
| 031 | Not fixed | Not fixed | – |
| 032 | Not fixed | Not fixed | – |
| 033 | Partial | Partial | "deck" now → SLIDES ("Make a deck from my notes" ✓); no EDIT intent still. |
| 034 | Fixed | Fixed (verified) | 0 NBSP chunks. |
| 035 | Fixed | Fixed (carried) | – |
| 036 | Not fixed | Not fixed | – |
| 037 | Partial | **Partial** | Grading rewritten: reversed meaning, negation, number words, `$15M`, "U.S." now right; but correct reordered/passive answers are marked wrong (R5-NEW-b). No essay grading. |
| 038 | Partial | **Partial (improved)** | Tables now render (1 `<table>`, 10 rows). Bullets glued with no separator still collapse (R5-NEW-k); a U+2028 reply loses the whole guide (R5-NEW-l); `<br>` in cells / adjacent tables break (R5-NEW-t/u). |
| 039 | Not fixed | **Not fixed (verified)** | Week 3 quiz: 1 Week3 passage (schedule slide), 5 logistics + 5 Week2 questions; "Weeks 1-5" now dropped from the topic (R5-NEW-c). |
| 040 | Fixed | Fixed (verified) | 10-question request → 10. |
| 041 | Fixed in code, needs GUI | Fixed in code, needs GUI | `export_path` + new Rust test (4/4). |
| 042 | Not fixed | Not fixed | Editors untouched. |
| 043 | Fixed in code, needs GUI | Fixed in code, needs GUI | – |
| 044 | Not fixed | **Not fixed (verified, r5 corpus)** | See 025. |
| 045 | Not fixed | Not fixed | `WorkCompanion.svelte` untouched (paste → `coverage: 'unknown'`). |
| 046 | Partial | Partial | `config.py` untouched. |
| 047 | Not fixed | Not fixed | `SlidesView` untouched. |
| 048 | Fixed in code, needs GUI | Fixed in code, needs GUI | – |

### NEW items from round 2

| ID | R4 | R5 status | Evidence |
|---|---|---|---|
| NEW-1 | Fixed | Fixed (verified) | All 5 sources indexed despite lost batches. |
| NEW-2 | Fixed | Fixed (verified) | No misattribution; splitter tests pass. |
| NEW-3 | Fixed | Fixed (verified) | U+FFFE / `\r` / NBSP / soft hyphen / control chars 0 in 955 chunks. |
| NEW-4 | Partial | **Partial (improved)** | Plain sentences, sorted pages, short vs blank split; still "unresolved" jargon, duplicated pages, raw endpoint/httpx text (R5-NEW-o, -r). |
| NEW-5 | Fixed | Fixed (verified) | `has_body("# Study Guide","Study Guide")` → False ✓; side effect R5-NEW-f. |
| NEW-6 | Not fixed (by design) | Not fixed (by design) | – |
| NEW-7 | Fixed | Fixed (carried) | – |
| NEW-8 | Fixed in code, needs GUI | Fixed in code, needs GUI | Unchanged. |
| NEW-9 | Fixed | Fixed (verified) | 200 on a fail-keyring backend; `delete_api_key` now idempotent. |
| NEW-10 | Partial | **Partial (improved)** | W1 18 / W2 30 / W3 11 OCR'd; refusals no longer lose pages; transient losses remain (R5-NEW-o). |
| NEW-11 | Fixed in code, needs GUI | Fixed in code, needs GUI | – |

### Round-3 new items

| ID | R4 | R5 status | Evidence |
|---|---|---|---|
| R3-NEW-1 | Fixed (reported shapes) | Fixed (verified) | Single page with `---` ✓, leading separator ✓; residual leading+trailing (R5-NEW-g, falls back per page). |
| R3-NEW-2 | Not fixed | **Partial (improved)** | Table half fixed live; bullets half still broken (R5-NEW-k) and U+2028 (R5-NEW-l). |
| R3-NEW-3 | Fixed in code, needs GUI | Fixed in code, needs GUI | Warning text improved (§3a). |
| R3-NEW-4 | Fixed (code) | Fixed (carried) | – |
| R3-NEW-5 | Fixed (code) | Fixed (code) | Per-task `reasoning_multiplier`. |
| R3-NEW-6 | Fixed | Fixed (carried) | – |
| R3-NEW-7 | Fixed | Fixed (verified) | Side effect R5-NEW-f. |
| R3-NEW-8 | Fixed (code) | Fixed (carried) | – |
| R3-NEW-9 | Fixed (code) | Fixed (carried) | – |
| R3-NEW-10 | Partial | Partial | 5 0/0 `usage_reported = 0` rows for refusals; 7 OCR calls ≥ 8,192 out. |
| R3-NEW-11 | Fixed | Fixed (carried) | – |
| R3-NEW-12 | Fixed in code, needs GUI | Fixed in code, needs GUI | `export_path`. |
| R3-NEW-13 | Fixed | Fixed (verified) | Live key `[2,3,3,3,2,1,2,1,3,2]`. |
| R3-NEW-14 | Partial | **Partial (improved)** | "week 3" ✓, "1848 treaty" ✓, "Table 2.2" ✓; ranges ("Weeks 1-5", "pages 40-45") now dropped (R5-NEW-c); "from my notes" → whole course. |
| R3-NEW-15 | Superseded / worse | **Partial** | `docs/RETEST-round4.md` committed and `notes.md` updated; `docket.md` still absent while `notes.md` mentions "docket" 25 times. |
| R3-NEW-16 | Fixed | Fixed (verified) | W3 `RemoteProtocolError` retried (2 attempts) — but then dropped (R5-NEW-o). |
| R3-NEW-17 | Over-corrected | **Fixed (verified)** | Anchored regex + `content_filter`; refusals retried, 0 pages lost; residual false negatives (R5-NEW-h). |

### Round-4 new items

| ID | R4 sev. | R5 status | Evidence |
|---|---|---|---|
| R4-NEW-a | medium | **Fixed (verified)** | "The 1836 request was rejected…" → no match; MiMo canned refusal → match. |
| R4-NEW-b | medium | **Partial (improved)** | Prompt bans + pinning + `_relettered`; live quiz clean. Gaps: "Both of the above", "Neither A nor B", "(A) is right" (R5-NEW-d). |
| R4-NEW-c | medium | **Partial** | False passes fixed; false fails on reordered/passive answers (R5-NEW-b). |
| R4-NEW-d | low | Fixed (residual R5-NEW-g) | `expected == 1` returns whole text. |
| R4-NEW-e | low | Fixed (code) | `_recognize_single_page` `operation(fresh=True)`. |
| R4-NEW-f | low | Fixed (code) | Malformed shapes `transient=False`; JSON decode errors transient. |
| R4-NEW-g | low | **Partial** | "deck" ✓, "week 3" ✓, "1848 treaty" ✓, "Table 2.2" ✓; "from my notes" → `''`. |
| R4-NEW-h | low | Fixed (over-relaxed: R5-NEW-i) | "How should I write my conclusion section?" accepted live. |
| R4-NEW-i | low | Fixed (side effect R5-NEW-f) | `has_body("## Overview")` → False. |
| R4-NEW-j | low | Fixed in code, needs GUI | `export_path` + Rust test. |
| R4-NEW-k | low | Fixed (verified) | 0 control-char chunks; `clean_text` repro. |
| R4-NEW-l | high | **Fixed (verified)** | 5 refusals in ingestion, 0 pages lost. |
| R4-NEW-m | low | **Partial (improved)** | See NEW-4. |
| R4-NEW-n | high | **Fixed (verified)** | Critiques 3/3 (+2) succeeded live; but fallacy check now near-meaningless (R5-NEW-a). |
| R4-NEW-o | high | **Fixed in code; not observed live** | r4 reply → 5/5 accepted; live runs fail on the 16k output cap / OCR drop (R5-NEW-s). |
| R4-NEW-p | medium | **Fixed (verified)** | "Rewrite the introduction…" got section 1 and edited the real Introduction. |
| R4-NEW-q | medium | **Fixed (verified)** | Alamo: one call, 8,052 out < 12,288, no discard (still 185 s). |

### Companion bugs

| ID | R4 | R5 status | Evidence |
|---|---|---|---|
| C-1 | Not fixed | **Not fixed** | `WorkCompanion.svelte` untouched; two live 422s this round (suggest-edit citation guard, xlsx paste) would leave the request pending; Retry resends it. |
| C-2 | Not reproduced | Not reproduced (code unchanged) | xlsx Summarize answered from the xlsx. |
| C-3 | Not fixed | Not fixed | `A1=…; B1=…` dump + shared-strings warning. |
| C-4 | Not fixed (not hit) | **Not fixed (reproduced)** | Style-only "Suggest an edit" → 422 "unsupported source reference" (`tutor/work.py:398–411`). |
| C-5 | Not fixed | Not fixed (verified) | Plain docx → `coverage: "partial"`. |
| C-6 | Not fixed | Not fixed (needs GUI) | No window code changed. |
| C-7 | Partial | Partial (needs GUI) | Unchanged. |
| C-8 | Not fixed | Not fixed | Copy only on desktop. |
| C-new-1 (= R4-NEW-p) | New | Fixed (verified) | See R4-NEW-p. |
| C-new-2 | New | Unverified | The suggest-edit request 422'd (C-4), so the 1-of-4-sentences behaviour could not be rechecked. |

## 4. New bugs and oddities introduced by 44503f0

Index by severity — **high:** R5-NEW-l (U+2028 loses the whole document), R5-NEW-o (transient OCR failure still drops a 4-page batch; raw error shown) · **medium:** R5-NEW-a (fallacy check effectively off), -b (grading fails reordered/passive answers), -c ("Weeks 1-5" dropped from the topic), -d (shuffle misses "Both of the above"/"Neither…nor"), -k (glued bullets → one bullet), -s (exam-style still fails live on MiMo: 16k output cap / no retry) · **low:** -e, -f, -g, -h, -i, -j, -m, -n, -p, -q, -r, -t, -u.

Scratch repros (no LLM) run with `cd /workspace/Stacks-r5 && env -u LLM_API_KEY PYTHONPATH=. .venv/bin/python`.

- **R5-NEW-a (medium): the essay-critique fallacy check is now effectively off.** `_names_fallacy` (`tutor/critique.py:264`) accepts a finding if any label word shares *any 4-character substring* with any feedback word (`_related`, `critique.py:251`). `_names_fallacy("You need to determine your thesis more clearly.", "ad_hominem")` → True ("hominem"/"determine" share "mine"); "This strategy section is vague." / `straw_man` → True ("stra"); "The circulation figures are fine." / `circular` → True; "Your slope chart is unclear." / `slippery_slope` → True. Combined with `validate_findings` now dropping bad findings, this makes critiques succeed (R4-NEW-n) but lets a mislabeled fallacy through. Suggest whole-word stems (prefix ≥ 5 chars) instead of any 4-gram.
- **R5-NEW-b (medium): short-answer grading now fails correct reordered / passive answers.** `_claims_in_order` (`student_model/grading.py:287`) requires the point's claims in the same order. Point "The United States paid Mexico $15 million": "Mexico received $15 million from the United States" → **wrong**; "Mexico was paid 15 million by the United States" → **wrong**; point "Texas was annexed in 1845": "In 1845 Texas was annexed" → **wrong**; "Texas joined the US in 1845 when it was annexed" → wrong; "Texas was not annexed until 1845" (true) → wrong (negation). Fixed: reversed meaning now fails, "fifteen million dollars", "$15M", "15,000,000", "U.S."/"US" pass, "did not pay" fails. Still passes: "…paid Mexico $18 million to $15 million", "…15 million, not land" (fine).
- **R5-NEW-c (medium): `retrieval_topic` drops hyphenated ranges — "Weeks 1-5" regressed.** `compose.py:454` `if "-" in token … continue` (meant for "10-question") also drops number ranges: "Create a study guide for the first exam covering Weeks 1-5" → `'first exam Weeks'` (r4: `'first exam Weeks 1-5'`); "Make a quiz on pages 40-45" → `'pages'`; "…on chapters 2-3" → `'chapters'`; "Make a study guide on 1846-1848" → `''` (whole course; same in r4). Only drop a hyphenated count when its tail is a size unit ("10-question", "8-slide").
- **R5-NEW-d (medium): shuffle still breaks some positional options.** `_POSITIONAL_OPTION` (`compose.py:810`) / `_BOTH_OPTIONS` (`:803`) only cover "both|neither|either X and|or Y", "all/none of the above" and "option X". Not covered, so still shuffled out of place: **"Both of the above"** (moved to position 1, where "above" means only the first option), **"Neither A nor B"** ("nor" missing), "A and B only", "(A) is right" in explanations (`_LETTER_REF`, `:800`, needs an option/choice/answer word). The prompt now forbids these, so frequency should drop; a live 10-question quiz is checked in §3b.
- **R5-NEW-e (low): `_reflowed` strips every line, destroying code-block indentation and nested lists.** `materials.py:36` `line.strip()` on every line: a fenced Python block `def f(x):\n    if x:\n        return 1` becomes `def f(x):\nif x:\nreturn 1`; nested bullets `- Causes\n  - Manifest Destiny` become a flat list. Use `rstrip()` and leave lines inside ``` fences alone. (The table/bullets fix itself works: `marked` with the app options renders `Key dates:\n| Date | Event |\n|---|---|…` as `<p>` + `<table>`, and `- a\n- b` as one `<ul>` with separate `<li>`.)
- **R5-NEW-f (low): `has_body` now rejects slides/sections of short key terms.** `materials.py:48–60`: a paragraph of < 3 words without punctuation is a label, so `has_body("Encomienda")` / `has_body("Manifest Destiny")` → False; a vocabulary slide whose paragraphs are bare terms fails the guard (a `- Encomienda` bullet passes). R4-NEW-i fixed (`has_body("## Overview")` → False).
- **R5-NEW-g (low): `split_ocr_pages` with both a leading and a trailing separator still fails.** `ocr_pages.py:31–34` drops one empty end only: `"---\nA\n---\nB\n---\n"` for 2 pages → 4 parts → ValueError (falls to per-page, so cost not loss). Single page with `---` ✓, leading separator ✓, blank middle ✓ (R4-NEW-d mostly fixed).
- **R5-NEW-h (low): refusal regex is now narrow (possible false negatives).** `_REFUSAL_RE` (`common/provider.py:137`) anchors to the whole reply. MiMo's canned "The request was rejected because it was considered high risk" → match ✓, "The 1836 request was rejected by the Mexican Congress." → no match ✓ (R4-NEW-a fixed). Not matched: "Request rejected.", "Your request was rejected as it may contain sensitive content.", "请求被拒绝", or a refusal appended after some OCR'd page text — those would be stored as page text. `finish_reason == "content_filter"` covers providers that set it.
- **R5-NEW-i (low): critique rewrite guard now lets rewrite requests through when phrased as a question.** `_ADVICE` (`critique.py:86`): "Can you help me rewrite this paragraph?", "Why don't you just rewrite my essay for me?", "Could you help me finish my essay?" → `refuses_rewrite` False (the critic prompt still says not to rewrite). R4-NEW-h fixed for "How should I write my conclusion section?" / "What would make it better?".
- **R5-NEW-j (low): the OCR warning is no longer length-capped.** The 450-char truncation was removed from `_warn_if_incomplete`; with many unresolved pages the Sources panel line is unbounded (size checked in §3a).
- `clean_text("a\rb\x0bc\x10d\te\u200bf\x85g")` → `'a\nbcd\te\u200bfg'` (R4-NEW-k fixed; zero-width space kept, fine).
- **R5-NEW-k (medium): study-guide bullets glued with no separator still collapse into one bullet.** On the US-Mexico War guide MiMo sent the Key Terms list as one paragraph string `…manifest destiny [10].- **Annexation of Texas** — …[5].- **Rio Grande…` (no newline, no `<br>`). `_reflowed` (`materials.py:21–45`) only splits on `<br>`/newlines, so `marked` renders 1 `<li>` for ~8 terms. Split on `(?<=[.!?\])])\s*-\s+(?=\*\*)` or ask for one bullet per array element. (The table half of R3-NEW-2 is fixed.)
- **R5-NEW-l (high): a reply that uses U+2028 for line breaks loses the whole document.** "Create a study guide for the first exam covering Weeks 1-5" (134 s) → only "Here is a study guide…", `withheld = ['workspace block is not valid JSON']`. MiMo's JSON was valid but separated bullets with U+2028 (`\u2028- Format: …`). `strip_fence_echo` (`common/prompt_registry.py:96–101`) runs `text.splitlines()` + `"\n".join`, and `splitlines` treats U+2028/U+2029/U+0085/\x1c–\x1e as line breaks, so each one becomes a raw newline inside a JSON string → `json.loads` fails in `extract_workspace_items` (`tutor/workspace.py:177`). Repro: `extract_workspace_items(strip_fence_echo("```workspace\n" + json.dumps({"type":"document","title":"T","content":"- a\u2028- b"}, ensure_ascii=False) + "\n```"), 3).withheld` → `('workspace block is not valid JSON',)` (without `strip_fence_echo`: a schema error only). Pre-existing code, newly triggered (MiMo started emitting U+2028 after the "escape line breaks" prompt). Fix: `re.split(r"\r\n|\r|\n", …)` in `strip_fence_echo`, and treat U+2028/2029 as line breaks in `_reflowed`.
- **R5-NEW-m (low): Table 2.2 is OCR'd now but chunked into three pieces.** Week1 chunk 28 = `"TABLE 2.2 Race of Major Hispanic Ancestries"` (47 chars), chunk 29 = the Markdown table (1,506 chars), chunk 30 = the source note. Retrieval on "Table 2.2" can match the 47-char title chunk without the body (see §3b).
- **R5-NEW-n (low): critique feedback can lead with the raw snake_case label** ("unsupported_claim: this sentence asserts…") — seen once in 4 MiMo critiques.

- **R5-NEW-o (medium, observed in scratch ingestion): a transient OCR failure on a batch still drops all 4 pages, and the raw provider error reaches the student.** `orchestrator.py:252–295`: the per-page fallback (`_recognize_single_page`) runs only for a `ModelRefusalError`; a transient error that persists through `ocr_max_attempts` (2) records `"pages … could not be read after 2 attempt(s): {err}"` and returns. Week3 batch p58/59/61/62 (the same batch MiMo refused in r4) failed twice with `RemoteProtocolError: peer closed connection without sending complete message body` (10:16→10:24 ET, ~8 min per attempt) → 4 pages lost. The Sources warning (364 chars after the `warning: ` prefix is stripped) ends with `pages 58, 59, 61, 62 could not be read after 2 attempt(s): Development endpoint sent a reply Stacks could not read (mimo-v2.6-flash): peer closed connection without sending complete message body (incomplete chunked read)` — endpoint name and httpx text shown to the student (R4-NEW-m only partly fixed). Fall back per page for any final failure, and drop `{err}` from the user string.
- **R5-NEW-p (low): "Reproduce Table 2.2" inside a conversation is pulled off-topic by the conversation.** On the W1+W2 copy, after three Reséndez turns, "Reproduce Table 2.2" retrieved Week2 23 / Week1 1 passages and replied "The course material provided here does not contain Table 2.2" — although the table is now indexed (Week1 chunk 29). Standalone retrieval on the full corpus: §3b.
- **R5-NEW-q (low, Windows only — not verifiable on this box): a failed upload can leave its temp file behind on Windows.** `storage.stream_to_temp` (`common/storage.py:117–136`) now calls `discard_temp(temp_path)` *inside* `with NamedTemporaryFile(delete=False) as handle:`, i.e. while the file is still open. On Linux unlink-while-open works; on Windows (the NSIS target in `tauri.conf.json`) it raises `PermissionError`, which `discard_temp` swallows with a log line, so every over-limit or empty upload leaks an `upload-*.tmp`. r4 closed the handle first. Move the `except` outside the `with`.
- **R5-NEW-r (low): failed OCR pages are listed twice in the Sources warning.** `_warn_if_incomplete` (`ingest/orchestrator.py:324–353`) puts every unrecovered page in "unresolved pages …" and then appends the failure sentence for the same pages: Week3 `unresolved pages 58, 59, 61, 62, 63, …; … pages 58, 59, 61, 62 could not be read after 2 attempt(s): …`, Week5 the same for 107/108/109/112 (§3a).
- **R5-NEW-s (medium, observed live): exam-style practice still never completes on MiMo, for new reasons.** (1) `write_questions` (`artifacts/exam_style.py:600–613`) runs as `artifact_generation`, whose `desired_output_tokens = 16384` (`configs/generation.toml:22`); on a reasoning profile that is the whole budget, and MiMo spent all **16,384** output tokens on a 5-question set → 503 "hit its output limit… Try one section at a time" after 290 s, with advice that makes no sense for a quiz upload. (2) The quiz-image OCR call is a single `provider.generate` with no retry; a `RemoteProtocolError` (transient) fails the whole request after ~8 min with the raw httpx text (3 of 4 runs, incl. the 11:18 ET rerun). The stem→prompt fix itself works (5/5 on the r4 reply, §3b). Give exam-style its own task size and retry transient errors once.
- **R5-NEW-t (low): `<br>` inside a table cell breaks the reflowed table.** `_reflowed` (`tutor/materials.py:21–45`) splits every paragraph on `<br>` before checking for table rows, so `['| Date | Event |','|---|---|','| 1846 | War begins<br>Thornton Affair |','| 1848 | Treaty |']` → `['| Date | Event |\n|---|---|', '| 1846 | War begins\nThornton Affair |', '| 1848 | Treaty |']` — the table is cut into three pieces (header-only table + two pipe paragraphs). `<br>` in a cell is the normal GFM way to put two lines in one cell.
- **R5-NEW-u (low): two adjacent tables are merged into one.** Same function: `['| A | B |','|---|---|','| 1 | 2 |','| C | D | E |','|---|---|---|','| 3 | 4 | 5 |']` → one block, so the second table's header and separator become body rows of the first.
- **C-4 resurfaced (model-dependent, code unchanged):** the Companion "Suggest an edit" on a pure style change returned 422 "unsupported source reference" (`tutor/work.py:398–411` requires a citation when course citations are available). See the Companion table.
- Reviewed and fine (no new issue): `body_limits` (>20-digit Content-Length → 413), `migrate` (version regex, rollback suppression), `secrets.delete_api_key` idempotent, `backups.recover_backup` (ids are `uuid4().hex`, lowercase, so the stricter regex is safe), `serve` stdin watcher, `office_addin/host` self-join guard, `segment`/`rerank` empty-window guards, `trace`/`archive_notebook` UUID tolerance, `student_model/archive` + `learning.submit` + `practice_support` bounds checks, `graph/edges` (`row[j] > 0` drop harmless at floor 0.78), `funnel.overview` spread (first + last chunk, `take == 1` guarded), `extract.read_decoded` keeps `\x00` for UTF-16/32, `page_quality` clamp, `structure._heading_start` (`(?![A-Za-z0-9])`), provider 400-adaptation loop bounded at 4 (falls through to the normal 4xx error), JSON-decode errors transient / malformed shapes non-transient, `exports.rs export_path` (+ test), `prompt_registry` text-body validation.

## 5. Counts

**STK-001..048**

| Status | Count | IDs |
|---|---|---|
| Fixed (verified this round) | 7 | 004, 006, 009, 010, 015, 034, 040 |
| Fixed (carried, code unchanged) | 10 | 001, 002, 008, 012, 014, 016, 020, 021, 022, 035 |
| Fixed in code, needs GUI check | 6 | 007, 013, 017, 041, 043, 048 |
| Partial | 11 | 003 (improved), 005, 018, 019, 023 (mixed), 024, 029, 033, 037, 038 (improved), 046 |
| Not fixed | 14 | 011, 025, 026, 027, 028, 030, 031, 032, 036, 039, 042, 044, 045, 047 |
| Regressed | 0 | – (023's answer is a hedged guess again rather than a refusal; counted as Partial) |

**NEW-1..11:** Fixed (verified) 5 (1, 2, 3, 5, 9) · Fixed (carried) 1 (7) · Fixed in code/needs GUI 2 (8, 11) · Partial 2 (4, 10, both improved) · Not fixed 1 (6, by design).

**R3-NEW-1..17:** Fixed (verified) 5 (1, 7, 13, 16, **17**) · Fixed (code/carried) 6 (4, 5, 6, 8, 9, 11) · Fixed in code/needs GUI 2 (3, 12) · Partial 4 (**2** improved, 10, 14 improved, **15** improved) · Not fixed 0.

**R4-NEW-a..q (17):** Fixed (verified) 6 (a, k, l, n, p, q) · Fixed (code, some with small residuals) 5 (d, e, f, h, i) · Fixed in code/needs GUI 1 (j) · Fixed in code, not observed live 1 (o) · Partial 4 (b, c, g, m) · Not fixed 0. **All 3 round-4 highs are fixed in code; l and n verified live.**

**Companion:** Not fixed 6 (C-1, C-3, C-4 reproduced, C-5, C-6, C-8) · Partial 1 (C-7) · Not reproduced 1 (C-2) · C-new-1 fixed · C-new-2 unverified.

**Round-5 new issues:** 21 (R5-NEW-a…u): **2 high** (l, o), **6 medium** (a, b, c, d, k, s), **13 low** (e, f, g, h, i, j, m, n, p, q, r, t, u). Several are side effects of round-4 fixes (a ← n, b ← c, c ← R3-NEW-14, f ← i, i ← h).

## 6. GUI-check list

1. **R3-NEW-3 / R4-NEW-m / NEW-4 / STK-017:** Sources panel after the 5-PDF upload — the warning lines (Week1 82 chars, Week2 117, Week3 364 with the raw "Development endpoint… peer closed connection…" text, Week5 320 with "(+20 more)" and "choose a faster model"). Readable? Wrapped or cut? Duplicated page numbers visible?
2. **NEW-8:** Same upload (~90 min on MiMo): badges flip to "indexed" without reload; leaving/returning restarts polling.
3. **C-1 / C-4:** Companion → "Suggest an edit" on a style-only change (expect 422 "unsupported source reference"), and paste spreadsheet cells into "Focus on a passage" (expect "not in the connected document snapshot"): does the request stick at "Saving this request…" / "not confirmed", and does Retry repeat the failure?
4. **R4-NEW-n / R5-NEW-a / -n:** Critique essay on `riley-doc.docx`: should now return findings (1.5–3 min). Check for raw labels like "unsupported_claim:" in feedback, and whether a "fallacy" badge matches what the feedback says.
5. **R4-NEW-o / R5-NEW-s:** Artifacts → Exam-style practice with a quiz photo on MiMo (expect "hit its output limit… Try one section at a time" or a connection error after 5–8 min); on another model, check that questions appear.
6. **R3-NEW-2 / STK-038 / R5-NEW-k / -l:** Study guide with a key-dates table and a bulleted key-terms list: table should render as a table; key terms may show as one bullet. "Study guide for the first exam covering Weeks 1-5" may return only the intro sentence with no document.
7. **R3-NEW-13 / R4-NEW-b / R5-NEW-d:** Practice the Week 3 quiz: answer positions vary, no "all/none/both" options, explanations quote option text.
8. **STK-037 / R5-NEW-b:** Short-answer item: "Mexico received $15 million from the United States" (correct, but expect "wrong"), "The U.S. paid Mexico fifteen million dollars" (expect right).
9. **STK-041 / R3-NEW-12 / R4-NEW-j:** Save dialog: "week3" → week3.md, "week3.final" → week3.final.md, "notes.txt" → notes.md; overwrite prompts once or twice?
10. **NEW-9:** Settings → Models on a keyring-less machine loads; adding/removing a key messages.
11. **NEW-11 / STK-007:** "Sources used (n)" in-session and after reopening the chat.
12. **C-2 / C-5 / C-6 / C-7 / C-8:** docx→xlsx Summarize on Riley's model; "Partial or unverified" label on a plain docx; docking/drag; controls during pending/error; no Insert/Replace on desktop.
13. **STK-033:** "Add a column for dates to that table" after a sheet → chat table, not an edit (rows may drop).
14. **STK-043, 013/018/019/020, 046, 048:** carried from r3/r4.
15. **R5-NEW-q (Windows build only):** upload an empty or over-limit file, then check `%TEMP%` for leftover `upload-*.tmp`.

## 7. Repro commands

```bash
cd /workspace/Stacks-r5
# checks
env -u LLM_API_KEY .venv/bin/python -m pytest -q          # 1144 passed
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src
(cd src/frontend && npm run check && npm test && npm run build)
(cd src/frontend/src-tauri && cargo check && cargo clippy --all-targets -- -D warnings && cargo test)
# scratch ingestion (92 min) and its summary
S=/workspace/stacks-test/r5-scratch
env LLM_API_KEY="$XIAOMI_API_KEY" APP_DATA_DIR=$S/data DATABASE_PATH=$S/data/course_assistant.db PYTHONPATH=. \
  .venv/bin/python $S/ingest.py
python3 $S/analyze.py $S/data/course_assistant.db R5
# student-facing warnings: ingestion_stage_runs.error_message LIKE 'warning:%' (what sources.sql serves)
# replays (same env): $S/ask.py "<question>" …  → $S/ask-results.json ; r4-corpus copy: $S/r4corpus/ask.py
# companion: $S/companion/run.py (results.json); exam-style: $S/companion/exam.py / exam3.py (APP_API_TOKEN=t,
#   APP_DATA_DIR/DATABASE_PATH = $S/companion/data); no-LLM exam replay of r4's stem-only reply: $S/exam_replay.py
# no-LLM repros, run with: env -u LLM_API_KEY PYTHONPATH=. .venv/bin/python
#   _REFUSAL_RE.match(...), strip_fence_echo + extract_workspace_items (U+2028), retrieval_topic/classify_intent,
#   short_answer_correct, _names_fallacy, refuses_rewrite, has_body, materials._reflowed, split_ocr_pages, clean_text
#   (snippets in §4; $S/r5chk.py)
# keyring: PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring … GET /api/settings/providers → 200
```

Result files: `r5-scratch/ingest.log`, `data/course_assistant.db`, `ask-results.json` (r5 corpus), `r4corpus/ask-results.json` (generation replays), `chat-results-w12.json`, `companion/results.json`, `companion/exam-result*.json`, `companion/exam_debug.log`.

