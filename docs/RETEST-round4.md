# Stacks: round-4 retest (d98d365..7b29e3d)

- **Date:** Thu Oct 8, 2026, from 03:22 ET (code-level + scratch replays; no GUI driven).
- **Tester:** Grok Bot (executor) for Riley K.
- **Commits:** f595461 "Fix 17 round-3 retest bugs across OCR, citations, quiz, intent, and export" (Oct 5 21:31 ET), 59729bb "Fixed some bugs" (Oct 6 09:38), 03a9f99 "fix bugs" (Oct 6 20:47), 7b29e3d "bugs bugs bugs" (Oct 8 03:21, HEAD of origin/main). 100 files, +6407/−2028 vs d98d365. Riley's remote was not touched.
- **Worktree:** `/workspace/Stacks-r4`, detached at 7b29e3d, own `.venv` / `node_modules` / `target/`. Stacks-r2 and the running r2 app untouched.
- **LLM:** `.env` copied from r3 (MiMo `mimo-v2.6-flash`, `https://token-plan-sgp.xiaomimimo.com/v1`, key = `$XIAOMI_API_KEY`, mode 600); every MiMo run also sets `LLM_API_KEY="$XIAOMI_API_KEY"` explicitly.
- **Scratch:** `/workspace/stacks-test/r4-scratch/` (course `fc3f138e-…`, same 5 PDFs, ingestion started 03:23 ET).

> **Status:** complete (04:59 ET). Code-level + API/scratch replays; nothing in the GUI was driven.

## 1. Check results

| Check | Result |
|---|---|
| `pip install -e ".[desktop,dev]" -c constraints.txt` (new `.venv`) | OK |
| `npm ci` | OK (EBADENGINE warning only, node v20.19.2) |
| `pytest` (`env -u LLM_API_KEY python -m pytest -q`) | **1109 passed**, 0 failed, 1 warning (102 s); r3: 1026. (Bare `.venv/bin/pytest` fails collection with 69 `No module named 'src'` errors because `pyproject` sets `pythonpath = ["src"]`, not the repo root; `python -m pytest` adds the cwd. Usage note only.) |
| `ruff check` / `ruff format --check` | pass / 243 files formatted |
| `mypy src` | no issues (151 files) |
| API types regen (`dump_openapi` → `OPENAPI_FILE=runs/openapi.json npm run gen:api`) | OK; no git diff (committed `schema.d.ts` is current). Without `OPENAPI_FILE` the script fetches `localhost:8000` and fails (dev-tool note). |
| `npm run check` (svelte-check) | 0 errors, 0 warnings (a first run during parallel setup reported 61 errors; did not reproduce on a clean rerun, see end of §1) |
| `npm test` | **36/36** (r3: 31; new `critique.test.ts`) |
| `npm run build` | OK |
| `cargo check` / `clippy --all-targets -D warnings` / `cargo test` | OK / OK, 0 warnings / **3/3** (unchanged count; no test covers the new `with_extension` path). The box had lost its Rust toolchain *and* the Tauri system libraries since r3: installed `rustup default stable` and, via apt, `pkg-config libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev libssl-dev libsoup-3.0-dev libjavascriptcoregtk-4.1-dev libxdo-dev` (apt reported one dpkg error on a portal package; the build was unaffected). |
| Scratch ingestion (5 PDFs, MiMo OCR) | All 5 indexed, 80 min (03:23–04:43 ET), 937 chunks; details §3a |

**Environment notes:** since round 3 the box was reset in places: `/workspace/Stacks-r3/.venv` is gone, the Rust toolchain was gone, and **the r2 app is no longer running** (no `tauri dev` / `stacks` / backend processes). I did not stop it.

## 2. What the diff changes (by docket ID)

| Area | IDs | Change |
|---|---|---|
| OCR | R3-NEW-1, NEW-10 | Prompt asks for `[blank]` on empty pages; splitter regex `(?:^|(?:\r?\n)+)[ \t]*---[ \t]*(?=\r?\n|$)` keeps empty parts; on a boundary mismatch a multi-page batch is retried one page per call (`orchestrator.py:276–279`). `configs/generation.toml` OCR `desired_output_tokens` 16384 → 2048 (MiMo reasoning ⇒ asks 8192). |
| OCR retry | R3-NEW-16 | `ProviderUnavailableError.transient` set at raise sites; `pipeline.is_transient_error` uses it (`pipeline.py:121–125`). |
| Refusals | R3-NEW-17 | `ModelRefusalError` when visible text matches `request was rejected|considered high risk` (`provider.py:133, 576`), not transient. |
| Generation | R3-NEW-4, R3-NEW-5 | Post-success deadline check removed; reasoning models ask `min(preferred, desired×4)` (`generation.py:76–82`). |
| Citations | R3-NEW-6 | Reversed ranges invalid again (`[5-3]` → `{0}` = invalid sentinel). |
| Drafts | R3-NEW-7, R3-NEW-2 | `has_body` counts heading text; heading cleanup `^#{1,6}\s+`; title truncated to 120; prompts ask the model to escape `\n` inside strings (strict `json_schema` still unconditional). |
| Slides / quiz | R3-NEW-9, R3-NEW-13, R3-NEW-8 | Slide cap 1–50; seeded option shuffle `_shuffle_quiz_options` (`compose.py:917`); quiz repair stops (keeps accepted questions) on error. |
| Intent / topic | R3-NEW-11, R3-NEW-14, STK-039 | "the/my/our notes" → ANSWER unless another artifact word is present (`compose.py:151–160`); `retrieval_topic` drops count tokens unless the previous token is capitalized (`compose.py:361–383`). |
| UI warning | R3-NEW-3, NEW-4 | `sources.sql` exposes the latest run's `warning:` stage message as `SourceView.warning`; `SourcesPanel.svelte` shows it. |
| Export | R3-NEW-12 | `exports.rs:211–219` appends the extension (`with_extension`) instead of erroring. |
| Polling / keyring | NEW-8, NEW-9 | Course page polls `while (anyPending && !destroyed)`, stops after 5 consecutive failures; `secrets.get_api_key` returns `None` on `NoKeyringError`/import failure. |
| Answers | – | Withheld answers clear `chunk_ids` and are not cached. |
| Runtime | – | `stop(forget=False)` on shutdown; delete-model refuses before stopping; activation honours custom `DATABASE_PATH` / storage root. |
| **New features** | – | Exam-style practice from an uploaded quiz (`artifacts/exam_style.py`, 664 lines, `/artifacts/exam-style`); essay critique (`tutor/critique.py`, `CriticPanel.svelte` 507 lines, migration 023, Office `/critique`); short-answer questions with mechanical grading (`student_model/grading.py`). |
| Docs | R3-NEW-15 | **7b29e3d deletes `docs/docket.md`, `docs/review.md`, `docs/plan-notebook.md`** (and the `docs/RETEST-round3.md` copy 59729bb had added); `docs/notes.md` / `DECISIONS.md` / `system.md` gain prose. The issue ledger is no longer in the repo. |
| **Unchanged** | 011, 017–020, 024–028, 030–032, 036, 042, 044–047, NEW-6 | `rag/funnel.py`, `tutor/chat.py`, `ingest/labels.py`, source-type detection, `SlidesView`, `EditableDocument`, `SheetView`, `export.ts`, `chat.svelte.ts`, `common/config.py`, `api/data.py` untouched. `extract.py` only gains `pdf_page_plain_text` / `rasterize_pdf_bytes(pages=…)` for exam-style. |

### 3a. Scratch ingestion detail (MiMo OCR, 03:23–04:43 ET, 80 min; r3 58 min)

`process_batch` → `(5, 5)` in 4,810 s; all 5 sources indexed; all auto-typed **notes** (STK-018).

| Source | pages | empty | low-q | OCR'd r3 → **r4** | unresolved r3 → **r4** | Why unresolved (r4) |
|---|---|---|---|---|---|---|
| Week1 | 82 | 11 | 2 | 6 → **11** | 17 → **13** | 2 batches refused (p14/80/21/22, p23–26; both succeed on resend), 5 short photo/cover pages |
| Week2 | 150 | 12 | 6 | 20 → **25** | 19 → **18** | 1 batch refused (p95–98, Reséndez intro); rest short/photo pages |
| Week3 | 104 | 20 | 3 | 0 → **7** | 27 → **23** | 2 batches refused (p58/59/61/62, p96/98/102); rest came back short; digit-glyph corruption untouched (3 low-q only) |
| Week5 | 191 | 36 | **0** (r3 6) | 40 → **47** | 44 → 36 | 50-page OCR cap; **Sánchez cipher pages all repaired**; 0 chunks with C0 controls (r3 15) |
| Week6 | 74 | 0 | 0 | 1 → 1 | 0 | – |

- Chunks: 149 / 193 / 165 / 287 / 143 = 937. U+FFFE 0, `\r` 0, NBSP 0, soft hyphen 0, blank 0. Week3 still has `18!1` ×3, `1&!4` ×1, `!()!` ×22, and the Alamo sentence `In late February of 1$3,, some 1-. Anglo-Texans … approximately 1,$.. Mexican army troops … su/ered ,.. casualties` (STK-005/023).
- Ledger: 58 OCR calls, 107,103 in / 235,675 out tokens; **5 rows 0/0 `usage_reported = 0` = the 5 refusals** (03:23:30, 03:23:33, 03:34:44, 04:00:23, 04:16:58 ET); 5 calls hit exactly 8,192 output tokens (the new OCR cap; truncation then recovery).
- The `RemoteProtocolError` at 03:33:40 ET was retried (R3-NEW-16 ✓).

### 3b. MiMo replays

Run with `r4-scratch/ask.py` (`api.tutor.ask`, raw provider output captured).

**On a Week1+Week2 copy (`r4-scratch/w12/`, 04:12 ET, while Week3/5/6 were still ingesting):**
- "What does Reséndez argue about the other slavery?" → correct, structured answer (double meaning of "other slavery", encomienda/repartimiento/debt peonage…), **7 Week2 citations**, 37 s. Week2 index has "Reséndez" ×3 / "Resendez" ×3 (r3: ×5) — Reséndez scan pages 95–98 were lost to the refusal (R4-NEW-l) but enough survived.
- "Reproduce Table 2.2" → full table reproduced, 2 Week1 citations, 55 s (material: Week2 11, Week1 9). One cell lost its `%` ("4,737 (0.3)" for Salvadoran/Asian; the OCR text has "(.3%)"). Full-corpus retrieval is the real STK-025/044 test — see below.

**Week1/Week2 ingestion (vs r3):** Week1 `pages_ocr` 11 (r3 6), 13 "unresolved" (r3 17) — 8 of them refusals, 5 short/photo pages; Week2 `pages_ocr` 25 (r3 20), 18 unresolved (r3 19) — 4 refusals (p95–98, Reséndez). Text hygiene: U+FFFE 0, `\r` 0, NBSP 0, soft hyphen 0, blank 0 (149 + 193 chunks). The 03:33 `RemoteProtocolError` on a Week2 batch was retried this time (R3-NEW-16 fix working: no failure note for it).
- **Follow-up chat on the W1+W2 copy** (`r4-scratch/chat.py`, conversations API, 04:16 ET):
  1. "Make a table of the forms of Indian slavery Reséndez describes…" → SHEET workspace item, 7 rows × 2 columns, 27 s ✓.
  2. "Add a column for dates to that table" → classified ANSWER (no EDIT intent, STK-033): a **chat Markdown table, not an edit of the sheet**, and it has **5 rows — two of the 7 rows were silently dropped** ("Enslavement of indigenous women and children", "Captivity among Native peoples before European arrival"). Dates column honest ("Not specified" where undated). 45 s.
  3. "give me the notes" → ANSWER (R3-NEW-11 fixed): bullet summary of the Week1/Week2 notes with citations, 107 s. No pointer to the uploaded source files themselves.


**Full 5-PDF corpus (04:45–04:53 ET):**

| Request | Time | Result |
|---|---|---|
| "Reproduce Table 2.2" | 38 s | ✗ **"I can't reproduce Table 2.2 — the course material provided here does not contain it… no passage in the assigned material refers to a Table 2.2"**; lists Table 2.7 / Table 4. Material: Week5 7, Week6 6, Week2 4, Week3 2, **Week1 0** (the table is in Week1, and the W1+W2 copy reproduced it). STK-025/044 not fixed. |
| "How much did the United States pay Mexico under the Treaty of Guadalupe Hidalgo?" | 6.5 s | ✓ "$15 million", 3 Week3 citations + a direct quote. |
| "How many Mexican troops fought at the Alamo?" | **239 s** | ✓ content: now says the digits are corrupted ("approximately 1,$.. Mexican army troops"… "I can't give you a precise troop count") instead of silently decoding (r3). ✗ time: the first `tutor_answer` call burned **8,192 output tokens** (the new reasoning cap = 2,048 × 4) and was thrown away as truncated; the second call answered with 488 tokens (R4-NEW-q). |
| "What does Reséndez argue about the other slavery?" | 19 s | ✓ 8 Week2 citations. |
| "Make a 10-question multiple-choice quiz on Week 3" | 153 s | Count ✓ (10). **Answer key now varied: `[1, 2, 0, 0, 0, 1, 0, 1, 1, 1]`** (r3: all 0) — R3-NEW-13 fixed; no "all/none of the above" in this run, explanations quote the option text rather than a letter. ✗ Retrieval: material Week6 5, Week5 4, Week2 4, Week1 2, **Week3 1** (the "Coming Up" slide); the first 3 questions are about office hours / exam date / where readings are posted, the rest are Reséndez (Week2) and immigration (Week6). STK-039 not fixed. |
| "Create a study guide for the first exam covering Weeks 1-5" | **238 s** (r3 85 s) | Document, 4,669 chars, citations Week5 6 / Week1 3 / Week3 1. ✗ Still mostly exam logistics (039). ✗ **R3-NEW-2 not fixed**: raw strict-JSON reply has 0 newlines and 0 escaped `\n`; MiMo ignored the new "escape each line break as \n" instruction and joined bullets with `  <br>- `. `marked` (app options `breaks: true, gfm: true`) renders `- Format…  <br>- Conditions…  <br>- Attendance…` as **one `<li>`** with literal "- " after each break. |
| "Make an 8-slide deck on Week 3" | 52 s | 8 slides ✓, bullets survive (one bullet per paragraph). ✗ Retrieval: 1 Week3 passage (the schedule slide), Week2 8, Week5 4 → the deck says **"The material for Week 3 is limited to a single schedule slide"** although Week3 has 165 indexed chunks (Gutiérrez Ch1, Valerio-Jiménez); slides 2–8 are padding ("Context note on coverage", "Office hours timing", "Course framing"…). |
| "Create a study guide on the US-Mexico War with a table of key dates and a bulleted list of key terms" | **453 s** (one call, 7,976 in / 5,113 out; the HTTP body took ~7.5 min, so mostly MiMo latency) | Content good (Week3 lecture + Valerio-Jiménez, citations). Bullets OK (each bullet its own paragraph → 22 `<li>`). ✗ **The table renders as 13 paragraphs of literal pipes, 0 `<table>`**: each row is a separate array paragraph (`| Date | Event | Source |`, `|---|---|---|`, …) joined with blank lines. Raw reply: 0 newlines, 0 escaped `\n`. R3-NEW-2 not fixed. |

## 3. Per-item status

| STK | R3 | R4 status | Evidence (R4) |
|---|---|---|---|
| 001 | Fixed | Fixed (carried) | Segmentation unchanged. |
| 002 | Fixed | Fixed (carried) | `labels.py` unchanged. |
| 003 | Partial | **Partial (improved)** | `pages_ocr` W1 11 / W2 25 / **W3 7** / W5 47 (r3 6/20/0/40); per-page fallback works. But 5 batches (19 pages, incl. Table 2.2's p14 and Reséndez p95–98) were dropped on a MiMo refusal that succeeds on resend (R4-NEW-l); W3 still 23/27 unresolved. |
| 004 | Fixed | Fixed (verified) | All artifacts completed; no `length` failure surfaced (but see R4-NEW-q: silent truncate-and-retry on answers). |
| 005 | Partial | **Partial** | Week5 cipher fully repaired (`pages_low_quality` 0, 0 control-char chunks; r3 6 / 15). Week3 glyph digits still corrupt and undetected (`1$!4`, `18!1` ×3, `!()!` ×22, Alamo `1,$..`; W3 low-q 3). |
| 006 | Fixed | Fixed (verified) | Treaty: "$15 million", 3 Week3 citations, 6.5 s. |
| 007 | Fixed in code, needs GUI | Fixed in code, needs GUI | Withheld answers now also clear `chunk_ids` (answer.py). |
| 008 | Fixed | Fixed (carried) | – |
| 009 | Fixed | Fixed (verified) | 0 blank chunks in 937. |
| 010 | Fixed | Fixed (verified) | "disparaged" ×2, no U+FFFE. |
| 011 | Not fixed | Not fixed | No change. |
| 012 | Fixed | Fixed (carried) | – |
| 013 | Fixed in code, needs GUI | Fixed in code, needs GUI | `SourcesPanel` only gains the warning line. |
| 014 | Fixed | Fixed (carried) | All PDFs typed "notes" again (018). |
| 015 | Fixed | Fixed (carried) | Keyring-less boxes now work (NEW-9). |
| 016 | Fixed | Fixed (carried) | – |
| 017 | Partial | **Fixed in code, needs GUI** | Poll loop no longer capped (NEW-8); OCR warning shown (R3-NEW-3). |
| 018 | Partial | **Partial (verified)** | All 5 PDFs auto-typed "notes" in R4 scratch. |
| 019 | Partial | Partial | Unchanged. |
| 020 | Fixed | Fixed (carried) | – |
| 021 | Fixed | Fixed (carried) | Coverage line unchanged, warning shown separately. |
| 022 | Fixed | Fixed (carried) | – |
| 023 | Partial | **Partial (better answer)** | MiMo now says the digits are corrupted instead of decoding them silently (r3), but the text layer is still corrupt and unflagged, and the answer took 239 s (R4-NEW-q). |
| 024 | Partial | Partial | Unchanged. |
| 025 | Not fixed | **Not fixed (verified)** | Full corpus "Reproduce Table 2.2": 19 material passages, **0 from Week1**; works on a W1+W2 copy. `funnel.py` untouched. |
| 026 | Not fixed | Not fixed | `funnel.py` untouched. |
| 027 | Not fixed | Not fixed | No streaming. |
| 028 | Not fixed | Not fixed (verified) | `RECENT_MESSAGES = 4`, `FOLLOW_UP_LOOKBACK = 2` (import). |
| 029 | Partial | **Partial (improved)** | Summary now asks 4,096 (not 16,384) on reasoning models (R3-NEW-5). |
| 030 | Not fixed | Not fixed (verified) | `EXCERPT_CHARS = 600`. |
| 031 | Not fixed | Not fixed | – |
| 032 | Not fixed | Not fixed | – |
| 033 | Partial | **Partial** | Essay+table → DOCUMENT ✓; "Give me the notes" → ANSWER ✓. "Add a column for dates to that table" → ANSWER: a new chat table instead of an edited sheet, and it dropped 2 of the 7 rows (§3b). |
| 034 | Fixed | Fixed (verified) | 0 NBSP chunks. |
| 035 | Fixed | Fixed (carried) | – |
| 036 | Not fixed | Not fixed | – |
| 037 | Not fixed | **Partial (new feature)** | Short-answer grading exists for practice quizzes, but it is bag-of-words (R4-NEW-c); no essay grading. |
| 038 | Partial | **Partial** | Deck 8/8 slides ✓; study guides complete ✓. Tables inside paragraphs still render as literal pipes and bullets inside one paragraph collapse to one `<li>` (R3-NEW-2 not fixed); study guides took 238 s / 453 s on MiMo. |
| 039 | Not fixed | **Not fixed (verified)** | Topic is now `'Week 3'`, but retrieval still finds 1 Week3 passage (the schedule slide): quiz = logistics + Week2/Week6 questions; the 8-slide deck claims "the material for Week 3 is limited to a single schedule slide" (165 Week3 chunks exist). "Week 3" is matched lexically, not against the Week3 source. Also R4-NEW-g. |
| 040 | Fixed | Fixed (verified) | 10-question request → exactly 10. |
| 041 | Fixed in code, needs GUI | Fixed in code, needs GUI | Extension now appended (R4-NEW-j oddity). |
| 042 | Not fixed | Not fixed | `EditableDocument`/`SheetView` untouched. |
| 043 | Fixed in code, needs GUI | Fixed in code, needs GUI | – |
| 044 | Not fixed | **Not fixed (verified)** | Full corpus: "the course material provided here does not contain it… no passage… refers to a Table 2.2" (025). |
| 045 | Not fixed | Not fixed | Paste still sends `coverage: 'unknown'` (`WorkCompanion.svelte:464`). |
| 046 | Partial | Partial | `config.py:114` unchanged. |
| 047 | Not fixed | Not fixed | `SlidesView` untouched. |
| 048 | Fixed in code, needs GUI | Fixed in code, needs GUI | – |


### NEW items from round 2

| ID | R3 | R4 status | Evidence |
|---|---|---|---|
| NEW-1 | Fixed | Fixed (verified) | All sources indexed despite refused batches. |
| NEW-2 | Fixed | Fixed (verified) | Splitter keeps empties; no misattribution seen; p14 probe split 4/4. |
| NEW-3 | Fixed | Fixed (verified) | 0 U+FFFE / `\r` / NBSP / soft hyphen in W1–W3 (507 chunks). Lone `\r` in `clean_text` still survives (R4-NEW-k). |
| NEW-4 | Partial | **Partial (improved)** | Warning now reaches the UI (`SourceView.warning`), but it is the raw developer string cut at 450 chars and counts short/blank pages as "unresolved" (R4-NEW-m). |
| NEW-5 | Partial | **Fixed (verified)** | `_workspace_response` now accepts the flattened legacy doc `"# Study Guide ## Exam Essentials - **Date:** …"` and a `### …` paragraph; title >120 accepted (truncated). Title-only `"# Study Guide"` still rejected ✓. Side effect R4-NEW-i. |
| NEW-6 | Not fixed (by design) | Not fixed (by design) | `.env` still doesn't override the shell. |
| NEW-7 | Fixed | Fixed (carried) | MiMo profile ships. (MiMo moderation still refuses some pages: R4-NEW-l.) |
| NEW-8 | Not fixed | **Fixed in code, needs GUI** | `courses/[id]/+page.svelte:306–322`: `while (anyPending && !destroyed)`, stops after 5 consecutive fetch failures. |
| NEW-9 | Not fixed | **Fixed (verified)** | `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring` → `GET /api/settings/providers` **200** (r3: 503). Saving a key on such a box still fails with "Unlock or enable your system keychain… Your saved keys have not been reported as missing." (odd wording; `secrets.py:14–20`). |
| NEW-10 | Partial | **Partial (improved)** | `pages_ocr`: Week1 11 (r3 6), Week2 25 (20), **Week3 7 (0)**; still lost: 23 of 27 Week3 pages unresolved, 5 batches (19 pages) lost to refusals across W1–W3. |
| NEW-11 | Fixed in code, needs GUI | Fixed in code, needs GUI | Unchanged. |

### Round-3 new items

| ID | R4 status | Evidence |
|---|---|---|
| R3-NEW-1 (blank-page split) | **Fixed (verified) for the reported shapes**; residual edge cases | `split_ocr_pages("A\n---\n---\nC\n---\nD",4)` → `['A','','C','D']`; `"---\nB…"` (blank first) ✓; `[blank]` ✓; trailing sep ✓. Still failing: leading separator before page 1, a Markdown rule inside a page, and a single page containing `---` (R4-NEW-d). Per-page fallback works (single-page ledger rows of 477 input tokens in W1/W3). |
| R3-NEW-2 (strict JSON flattens tables/bullets) | **Not fixed (verified)** | Prompts now ask to escape `\n`, but MiMo's strict-schema replies still have 0 newlines and 0 escaped `\n`: the bullets in the exam study guide were joined with `<br>- ` (one `<li>`), and the US-Mexico War table rendered as 13 `<p>` of pipes. Strict `json_schema` still unconditional. |
| R3-NEW-3 (OCR warnings hidden) | **Fixed in code, needs GUI** | `sources.sql` warning subquery + `SourcesPanel.svelte` line; oddities R4-NEW-m and raw text. |
| R3-NEW-4 (deadline discards success) | Fixed (code) | `generation.py:258–260` no post-success check. |
| R3-NEW-5 (reasoning ignores task sizes) | Fixed (code) | `min(preferred, desired×4)`; OCR now asks 8,192 — ledger shows several 8,192-token OCR replies (W1 p27/28/33/46 batch, W3 single page), i.e. truncation + recovery instead of 16,384 runaways. |
| R3-NEW-6 (reversed ranges valid) | Fixed (verified) | `cited_numbers("see [5-3]")` → `{0}` (invalid). |
| R3-NEW-7 (`has_body`/headings/title) | Fixed (verified) | See NEW-5; "#1 Priority" kept. Side effect R4-NEW-i. |
| R3-NEW-8 (quiz repair aborts) | Fixed (code) | Repair `break`s keeping accepted questions. |
| R3-NEW-9 (200-slide cap) | Fixed (code) | 1–50 (`compose.py` schema `maxItems 50`); `DeckDraft.slides max_length` still 200 (inconsistent, harmless). |
| R3-NEW-10 (OCR runaway / 0-0 rows) | Partial | Runaway now capped at 8,192; 0/0 rows still written for refusals (`usage_reported = 0`). A 538-char page batch still cost 6,718 output tokens (probe). |
| R3-NEW-11 ("give me the notes" → DOCUMENT) | Fixed (verified) | `classify_intent` → ANSWER; live replay answered from the notes. "Make a deck from my notes" → ANSWER (R4-NEW-g). |
| R3-NEW-12 (export extension) | Fixed in code, needs GUI | `exports.rs:211–219`; new oddity R4-NEW-j. |
| R3-NEW-13 (answer always A) | **Fixed (verified)** | Live 10-question quiz key `[1,2,0,0,0,1,0,1,1,1]` (r3 all 0); 400 synthetic prompts → 107/104/92/97. New: R4-NEW-b. |
| R3-NEW-14 (`retrieval_topic` count words) | **Partial** | "Make an 8-slide deck on Week 2" → `'Week 2'` ✓, "10-question quiz on Week 3" → `'Week 3'` ✓; but "quiz on week 3" → `'week'`, "about the 1848 treaty" → `'treaty'`, "Table 2.2" → `'reproducing 2'` (R4-NEW-g). |
| R3-NEW-15 (NEW-8..11 missing from docket) | **Superseded / worse** | NEW-8/9 are now addressed in `docs/notes.md`, but 7b29e3d **deleted `docs/docket.md`, `review.md`, `plan-notebook.md`** and the committed `docs/RETEST-round3.md`. `notes.md` still cites docket rows SW-01…SW-20, F-20, F-21, NEW-8/9 that no longer exist in the repo. |
| R3-NEW-16 (transient by message text) | Fixed (verified live) | `transient` flag; the 03:33 ET `RemoteProtocolError` on a Week2 batch was retried and left no failure note. Over-broad catch-all (R4-NEW-f). |
| R3-NEW-17 (refusal treated as text) | **Fixed but over-corrected** | `ModelRefusalError` exists, but the regex matches ordinary prose (R4-NEW-a) and, being non-transient, it permanently drops OCR batches that succeed on resend (R4-NEW-l: 5 batches, 19 pages in W1–W3). |

### Companion bugs (report-companion.txt), code level + MiMo API repro

| ID | Bug | R4 status | Evidence |
|---|---|---|---|
| C-1 | Custom prompts / quick actions stuck at "Saving this request and its response…" or "This request was not confirmed"; Retry doesn't recover | **Not fixed** | `WorkCompanion.svelte:495` shows "Saving this request and its response…" for the *whole* generation (52–157 s per action in the repro), so a normal wait looks stuck. Any non-2xx leaves `pending` set → "not confirmed"; **Retry (`ask()`) resends the identical pending request** (same `request_id`, `expected_revision`, selection; skips `refreshDocument`), so deterministic 422s repeat forever. Live 422s that hit this path: selection pasted from Calc (`tutor/work.py:104`, instant), and essay critique (`critique.py` all-or-nothing, 2/2 after 145–157 s, R4-NEW-n). Only "Clear pending request" escapes. |
| C-2 | XLSX Summarize answered from the DOCX | **Not reproduced on MiMo (code unchanged)** | Same session: docx summarize → xlsx connect → Summarize answered correctly from the xlsx (28 s). History still carries earlier docx replies (`_history`, `work.py:71–88`, with a snapshot number), so the model-dependent risk remains; GUI recheck with the user's model. |
| C-3 | XLSX extracted 177 chars + "no shared strings part" warning | Not fixed (cosmetic) | Warning still shown for inline-string workbooks, where it is accurate but alarming; snapshot rendered as `A1=…; B1=…` cell dumps. |
| C-4 | "The answer contained an unsupported source reference. Try again." | Not fixed (code unchanged) | Citation guard unchanged; not hit in this repro. Critique path skips it (`if request.action != "critique"`). |
| C-5 | Capture always "Partial or unverified" | **Not fixed (verified)** | File connect always appends two generic warnings → `coverage: "partial"` for a plain docx (`office_reader/work_files.py:16–40`); paste still `coverage: 'unknown'`. |
| C-6 | No docking; title-bar drag unreliable | Not fixed (no window code changed) | Needs GUI. |
| C-7 | Controls visible during error/pending | Partial | Action buttons/textarea are `disabled` while pending; critique controls too. They are still shown. Needs GUI. |
| C-8 | Copy only, no Insert/Replace | **Not fixed** | Desktop companion still only "Copy response" / "Copy proposed replacement" (`WorkCompanion.svelte:479–480`); Insert/Replace exists only in the Word add-in (and is hidden for critiques). |
| C-new-1 | Custom instruction targets the wrong section | New (R4-NEW-p) | `document_context` keyword-overlap picks sections; "Rewrite the introduction paragraph…" got sections 3/9/10/20 without the Introduction. |
| C-new-2 | Suggested edit covers 1 of 4 selected sentences | New (low) | Passive-voice request on a 4-sentence selection returned a replacement for sentence 1 only. |

### Companion repro detail

Paper work session → connect `riley-doc.docx` (54,913 chars, 31 sections) → actions → connect `riley-doc-table.xlsx` → actions. Results in `r4-scratch/companion/results.json`.

| Step | HTTP | Time | Result |
|---|---|---|---|
| Connect docx | 200 | 0.1 s | `coverage: "partial"` with the two fixed warnings ("headers, footers, notes and comments are not included…", "Text extraction does not include every image…") — **every** file connect is labelled partial (C-5). |
| Summarize docx | 200 | 55 s | Good, honest scope note (sections 1, 2, 3, 24 of 31 supplied). |
| Suggest an edit, selection = the 4-sentence LBJ paragraph from the report ("we" → passive) | 200 | 53 s | Selection matched the snapshot exactly. **Proposed edit covers only the first sentence**; the other three are described in prose ("would need the same treatment") — the user asked for the whole passage. |
| Custom: "Rewrite the introduction paragraph so it is clearer and more formal, preserving all numbers." | 200 | 98 s | **Wrong passage**: `document_context` (`tutor/work.py:41–68`) ranks 2,000-char slices by 3+-letter word overlap with the instruction and picked sections 3, 9, 10, 20; the Introduction (D2) was not supplied, so MiMo rewrote the Corpus overview and said "I could not locate an introduction paragraph". |
| Critique (score 50, research) | **422** | **145 s** | "The critique named a fallacy it did not explain." |
| Critique again, unchanged draft | **422** | **157 s** | Same error. 0 of 2 critiques succeeded; ~5 min of generation discarded. |
| Critique with instruction "How should I write my conclusion section?" | 422 | 0 s | "The critic comments on your draft. It will not write or rewrite the essay." (R4-NEW-h) |
| Connect xlsx | 200 | 0 s | Snapshot text is `row 1\nA1=Classification; B1=Formal list (primary); C1=…\n\nrow 2\nA2=MALE; B2=13; C2=84…` plus the "no shared strings part" warning (C-3). |
| Summarize xlsx | 200 | 28 s | **Answered from the xlsx** (table rebuilt correctly). C-2 did not reproduce on this run. |
| Explain, selection = the same cells pasted as tab-separated text (as copied from Calc) | **422** | 0 s | "The selected passage is not in the connected document snapshot." — a selection copied from the spreadsheet can never match because the snapshot is rendered as `A2=MALE; B2=13` (`tutor/work.py:104`). |

## 4. New bugs and oddities introduced by f595461..7b29e3d

Index by severity — **high:** R4-NEW-l (refusal drops OCR pages), R4-NEW-n (critique fails whole; 0/2 on MiMo), R4-NEW-o (exam-style returns nothing on MiMo) · **medium:** R4-NEW-a (refusal regex false positives), -b (shuffle vs "Both A and B"/letter explanations), -c (bag-of-words short-answer grading), -p (companion section picking), -q (×4 reasoning cap truncates answers) · **low:** -d, -e, -f, -g, -h, -i, -j, -k, -m, plus C-new-2 and the docket deletion (R3-NEW-15).

Scratch repros (no LLM) run with `cd /workspace/Stacks-r4 && env -u LLM_API_KEY PYTHONPATH=. .venv/bin/python`.

- **R4-NEW-a (medium): refusal detector matches ordinary prose.** `_REFUSAL_RE = re.compile(r"request was rejected|considered high risk", re.I)` (`common/provider.py:133`) is applied to the visible text of *every* completion (`provider.py:576`), including OCR and tutor answers. `_REFUSAL_RE.search("The 1836 request was rejected by the Mexican Congress.")` → match; also "…considered high risk by insurers". A history answer or an OCR'd page containing either phrase raises `ModelRefusalError` ("refused to answer… pick another model"), not transient — the OCR page is lost / the answer fails. Anchor it to the whole reply (e.g. `^\s*the request was rejected because it was considered high risk\.?\s*$`) or use `finish_reason == "content_filter"`.
- **R4-NEW-b (medium): option shuffle breaks positional options and explanations.** `_shuffle_quiz_options` (`compose.py:917`) permutes options but nothing forbids or pins "Both A and B" / "None of the above" / "All of the above" (`_PLACEHOLDER_OPTION`, `compose.py:711`, does not cover them; prompts don't ban them), and explanations that name a letter are not rewritten. Repro: options `["Guadalupe Hidalgo","Adams-Onís","Both A and B","None of the above"]`, explanation "Option A is correct." → `['None of the above','Adams-Onís','Guadalupe Hidalgo','Both A and B']`, answer 2, explanation still "Option A is correct.". Distribution itself is fine (400 seeded prompts: 107/104/92/97).
- **R4-NEW-c (medium): short-answer grading is bag-of-words.** `grading.short_answer_correct` (`student_model/grading.py:95–123`): point "The United States paid Mexico $15 million" — answer "Mexico paid the United States 15 million" (meaning reversed) → **correct**; "united states mexico paid 15 million" → correct; "The U.S. paid Mexico fifteen million dollars" → **wrong**; "The US paid Mexico $15M" → wrong. Word order, abbreviations and number words are not handled, so both false passes and false fails.
- **R4-NEW-d (low): OCR splitter edge cases still fall to per-page or lose the page.** `split_ocr_pages` (`ingest/ocr_pages.py:15–30`): `"---\nA\n---\nB\n---\nC\n---\nD"` (leading separator before page 1) → ValueError (N+1 parts; only a trailing empty part is dropped); a Markdown rule inside a page → ValueError; **a single page whose text contains `---` → ValueError even when called alone** (`split_ocr_pages("Title\n\n---\n\nBody",1)`), so the per-page fallback cannot recover it and the page is unresolved. With `expected == 1` the whole text should be the page.
- **R4-NEW-e (low): per-page OCR fallback shares the batch budget.** `orchestrator.py:276–279` calls `_recognize_bounded_batch([page])` inside the batch's `generation.operation()` (8 calls / 16 HTTP / 600 s), so a slow 4-page batch plus 4 single-page retries can exhaust the operation and leave the later pages unresolved with a budget error.
- **R4-NEW-f (low): generic provider errors are now "transient".** The catch-all `except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError)` in `provider.py` raises `ProviderUnavailableError(transient=True)`, so a deterministic malformed reply (`TypeError("reply has no completion choice")`) is retried with backoff and billed again.
- **R4-NEW-g (low): intent / topic misses.**
  - "Make a deck from my notes" → ANSWER (`_OTHER_ARTIFACT`, `compose.py:155`, lacks "deck") ("Turn my notes into a presentation" → SLIDES works because "presentation" is listed).
  - `retrieval_topic`: "Make a quiz on week 3" → `'week'` (lower-case "week" so "3" dropped); "Make a quiz about the 1848 treaty" → `'treaty'` (year dropped); "Make a table reproducing Table 2.2" → `'reproducing 2'`; "Turn my notes into a presentation" / "Make a quiz from my notes" → `''` (whole course, not the notes).
- **R4-NEW-h (low): essay-critique rewrite guard is broad.** `critique._REWRITE` (`tutor/critique.py:47–55`) refuses "How should I write my conclusion section?", "Can you help me write a stronger thesis for this paper?" and "What would make it better?" as rewrite requests.
- **R4-NEW-i (low): heading-only paragraphs count as body.** `has_body("## Overview","Deck")` → True (`materials.py:18`), so a slide/section with only a sub-heading passes the title-only guard (side effect of the R3-NEW-7 fix).
- **R4-NEW-j (low): export `with_extension` replaces dotted names.** `exports.rs:218` `path.with_extension("md")` turns "week3.final" into "week3.md" and "notes.v2" into "notes.md" (and can then hit the replace prompt for a different file). Use `format!("{name}.{ext}")` when the existing suffix isn't a known extension.
- **R4-NEW-k (low): lone `\r` / C0 controls still survive `clean_text`** (`clean_text("a\rb\x0bc\x10d")` unchanged) — carried from r3.
- **R4-NEW-l (high, observed in scratch ingestion): a MiMo moderation refusal now permanently drops OCR pages — no retry.** Week1 (03:23 ET): batches p14/80/21/22 and p23–26 each returned an immediate refusal (ledger rows 0/0, `usage_reported = 0`, 03:23:30 and 03:23:33 ET) → `ModelRefusalError` (non-transient, `provider.py:576–580`) → `"pages 14, 80, 21, 22 OCR failed after 1 attempt(s): Development endpoint (mimo-v2.6-flash) refused to answer this request…"`. **Re-sending the very same two batches at 03:33 ET succeeded both times** (`r4-scratch/probe/ocr_raw.py`; p14 = TABLE 2.2 transcribed as a clean Markdown table, 1,378 chars; p23–26 = campaign-sign photos "Latinos FOR TRUMP 2020…", 538 chars but **6,718 output tokens**). MiMo's moderation is probabilistic, so treating it as final turns a coin-flip into lost pages — including the page that holds Table 2.2 (STK-044). Suggest: treat a refusal as retryable once (or retry per page) for OCR, and keep the non-retry rule for chat answers.
- **R4-NEW-m (low): the student-facing OCR warning is a raw developer string that overstates failures.** `SourcesPanel.svelte:348–349` prints `source.warning` verbatim. Live `GET /sources` on the R4 scratch course, Week1: `warning: unresolved pages 14, 80, 21, 22, 23, 24, 25, 26, 27, 28, 33, 46, 66; pages 14, 80, 21, 22 OCR failed after 1 attempt(s): Development endpoint (mimo-v2.6-flash) refused to answer this request. Try rephrasing or pick another model.; pages 23…` (400 chars, cut mid-sentence; Week3 440). It has the "warning:" prefix, pages out of order (garbled pages first), the endpoint name, doubled `.;` punctuation, and advice to "pick another model" for an ingestion. The "unresolved" list also includes pages OCR did read but that are still short or low-quality after re-assessment (`orchestrator.py:184–188` uses `report.ocr_pages` after `apply_page_ocr`), e.g. Week1 p27/28/33/46/66 (cover/photo pages), with no reason given.

- **R4-NEW-n (high): essay critique fails whole on one imperfect finding; on MiMo 2/2 critiques failed after ~2.5 min each.** `validate_findings` (`tutor/critique.py:243–301`) raises `ValueError` (→ 422) for the entire critique if any single finding breaks a rule, with no repair call and no dropping of the bad finding. The rule that fired, `_names_fallacy` (`critique.py:237–240`), demands the literal label in the feedback, which the prompt never asks for (`configs/prompts.toml:455, 478` only say "say why"): `_names_fallacy("This claim is not supported by any cited evidence.", "unsupported_claim")` → False; "…never addresses a counterargument." / `missing_counterargument` → False; "post-hoc inference" / `post_hoc` → False; "You generalize hastily…" / `hasty_generalization` → False. The other all-or-nothing rules (`original` must be an exact substring of the draft and of the scope; a quote still open from a prior critique rejects everything, `critique.py:266–276`) make it more fragile still. In the desktop UI each failure leaves the request pending (C-1).
- **R4-NEW-o (high): exam-style practice produces nothing on MiMo — the prompt never names the `prompt` field.** Uploaded a 5-question quiz image (`r4-scratch/companion/quiz2.png`, Latino-politics topics that Week1 covers) to `POST /courses/{id}/artifacts/exam-style` on the r4 scratch copy: **422 "No usable new questions could be written from the course material for that quiz's topics." after 162 s** (3 calls: OCR 746/1,493, profile 431/213, questions 6,034/3,296 tokens). A second run with a capture wrapper (`companion/exam_debug.py` → `exam-debug.json`) shows why: MiMo returned 5 well-grounded questions (all points grounded, `expected` covered) but put the question text in `"stem"` and sent **no `"prompt"`**, so every item fails the `key`/length checks in `accept_questions` (`artifacts/exam_style.py:487, 535`, `_usable_short` needs `len(prompt) >= 12`). The prompt (`configs/prompts.toml:579–592`) lists `options/answer/points/expected/stem/part/sources/topic/capability/explanation` but only mentions "prompt" in passing for parts, and `write_questions` (`exam_style.py:596–606`) sends no `response_schema`. Riley's notes say "A live model evaluation … has not been run" (F-20). Fix: define `prompt` explicitly (or a JSON schema) and treat a lone `stem` as the prompt.
  - The same raw reply confirms R4-NEW-b live: explanation "…which matches **option A**. Option B is the definition of national origin… ruling out option C" — after `_shuffle_quiz_options` those letters point at different options.

- **R4-NEW-p (medium): companion picks document sections by word overlap, so "the introduction" can be left out.** `tutor/work.py:41–68` slices the snapshot into fixed 2,000-char sections and keeps the top-N by count of shared 3+-letter words with the instruction; section names/headings get no weight. Repro: `riley-doc.docx` (31 sections), "Rewrite the introduction paragraph so it is clearer and more formal, preserving all numbers." → sections 3, 9, 10, 20 supplied; MiMo revised the Corpus overview instead and said it couldn't find the introduction.

- **R4-NEW-q (medium): the reasoning-model cap (desired × 4) truncates real answers and the truncated reply is thrown away.** `generation.py:76–82` gives MiMo tutor answers 8,192 output tokens. Full-corpus "How many Mexican troops fought at the Alamo?": call 1 = 7,708 in / **8,192 out** (truncated, discarded), call 2 = 488 out → 239 s total (r3: 50 s). The ingestion had 5 OCR calls end at exactly 8,192 as well. The ×4 factor is a guess that a hard question overruns.


## 5. Counts

**STK-001..048**

| Status | Count | IDs |
|---|---|---|
| Fixed (verified this round) | 6 | 004, 006, 009, 010, 034, 040 |
| Fixed (carried, code unchanged) | 11 | 001, 002, 008, 012, 014, 015, 016, 020, 021, 022, 035 |
| Fixed in code, needs GUI check | 6 | 007, 013, **017** (new), 041, 043, 048 |
| Partial | 11 | 003, 005, 018, 019, 023, 024, 029, 033, **037** (new: short-answer grading), 038, 046 |
| Not fixed | 14 | 011, 025, 026, 027, 028, 030, 031, 032, 036, 039, 042, 044, 045, 047 |
| Regressed | 0 | – |

R3 → R4 movement: 017 Partial → Fixed in code/GUI; 037 Not fixed → Partial; 003/029 Partial (improved); nothing regressed.

**NEW-1..11:** Fixed (verified) 5 (NEW-1, 2, 3, **5**, **9**) · Fixed (carried) 1 (NEW-7) · Fixed in code/needs GUI 2 (**NEW-8**, NEW-11) · Partial 2 (NEW-4, NEW-10, both improved) · Not fixed 1 (NEW-6, by design).

**R3-NEW-1..17:** Fixed (verified) 6 (1 for the reported shapes, 6, 7, 11, 13, 16) · Fixed in code 4 (4, 5, 8, 9) · Fixed in code/needs GUI 2 (3, 12) · Partial 2 (10, 14) · Not fixed 1 (**2**, tables/bullets) · Over-corrected / worse 2 (**15** docket deleted, **17** refusals now drop pages).

**Companion (report-companion.txt):** Not fixed 6 (C-1, C-3, C-4, C-5, C-6, C-8) · Partial 1 (C-7) · Not reproduced on MiMo 1 (C-2, code unchanged) · plus 2 new (R4-NEW-p, C-new-2).

**Round-4 new issues:** 17 numbered (R4-NEW-a…q: 3 high, 5 medium, 9 low) + C-new-2 + docket deletion.

## 6. GUI-check list

1. **R3-NEW-3 / R4-NEW-m / STK-017:** Sources panel after the 5-PDF upload: the warning line under Week1/2/3/5 (raw "warning: unresolved pages 14, 80, 21…; …Development endpoint (mimo-v2.6-flash) refused… pick another model" text, 185–440 chars). Is it readable, wrapped, or truncated?
2. **NEW-8:** The same upload (80 min here) — badges keep updating to "indexed" without a reload; leaving and returning to the page restarts polling.
3. **C-1:** Companion → custom instruction / Critique essay: the "Saving this request and its response…" label stays up for the whole 1–3 min generation; after a 422 (paste table cells from Calc into "Focus on a passage", or a critique) the request shows "not confirmed" and **Retry repeats the same failure**; only "Clear pending request" recovers.
4. **R4-NEW-n:** Critic tab + companion "Critique essay" on `riley-doc.docx` with MiMo (expect "named a fallacy it did not explain" after ~2.5 min); score/genre sliders: does a moved but unsaved slider snap back when the work session refreshes (`$effect` in `WorkCompanion.svelte:60–64`)?
5. **R4-NEW-o:** Artifacts → Exam-style practice with a quiz photo/PDF (expect "No usable new questions…" after ~2.5 min on MiMo).
6. **C-2:** Same session, docx → Summarize → connect xlsx → Summarize, on the user's own model (did not reproduce on MiMo).
7. **C-5 / C-7 / C-6 / C-8:** label for a plain docx ("Partial or unverified"), controls during pending/error, docking/drag, and the lack of Insert/Replace on desktop.
8. **R3-NEW-2 / STK-038:** Open the US-Mexico War study guide with a key-dates table → expect lines of pipes instead of a table; the exam study guide bullets show "<br>- " joined items in one bullet.
9. **R3-NEW-13 / R4-NEW-b:** Practice the Week 3 quiz: answer positions vary; check any "Both A and B"/"None of the above" question and explanations naming a letter.
10. **Short answers (STK-037 / R4-NEW-c):** Practice an exam-style or edited quiz with a short-answer item; try a reversed-meaning answer ("Mexico paid the United States 15 million") and a correct paraphrase ("The U.S. paid Mexico fifteen million dollars").
11. **STK-041 / R3-NEW-12 / R4-NEW-j:** Save dialog: type "week3" (expect "week3.md"), "week3.final" (expect it to become "week3.md"), overwrite an existing file (one or two prompts?).
12. **NEW-9:** Settings → Models on this keyring-less box now loads (200); adding a key shows the "Unlock or enable your system keychain…" message.
13. **NEW-11 / STK-007:** "Sources used (n)" in-session and after reopening the chat.
14. **STK-043, 013/018/019/020, 046, 048:** carried from r3.
15. **"Add a column for dates to that table" (STK-033):** In a chat with a sheet, the follow-up answers with a new chat table (not an edit) and may drop rows.

## 7. Repro commands

```bash
cd /workspace/Stacks-r4
# checks
env -u LLM_API_KEY .venv/bin/python -m pytest -q          # 1109 passed
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src
(cd src/frontend && npm run check && npm test && npm run build)
(cd src/frontend/src-tauri && cargo check && cargo clippy --all-targets -- -D warnings && cargo test)
# scratch ingestion (80 min)
env LLM_API_KEY="$XIAOMI_API_KEY" APP_DATA_DIR=/workspace/stacks-test/r4-scratch/data \
  DATABASE_PATH=/workspace/stacks-test/r4-scratch/data/course_assistant.db PYTHONPATH=. \
  .venv/bin/python /workspace/stacks-test/r4-scratch/ingest.py
python3 /workspace/stacks-test/r4-scratch/analyze.py /workspace/stacks-test/r4-scratch/data/course_assistant.db R4
# replays (same env): r4-scratch/ask.py "<question>" …; follow-ups: r4-scratch/chat.py (APP_API_TOKEN=t, header X-App-Token)
# companion: r4-scratch/companion/run.py <course_id>; exam-style: companion/exam.py, companion/exam_debug.py
# raw OCR of a batch with the refusal check disabled: r4-scratch/probe/ocr_raw.py <source_id> 14,80,21,22
# no-LLM repros (split_ocr_pages, _REFUSAL_RE, classify_intent/retrieval_topic, _shuffle_quiz_options,
#   short_answer_correct, _names_fallacy, refuses_rewrite, has_body, cited_numbers, clean_text): see §4 snippets,
#   run with: env -u LLM_API_KEY PYTHONPATH=. .venv/bin/python
# keyring: PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring APP_DATA_DIR=/tmp/kr4 DATABASE_PATH=/tmp/kr4/db.sqlite \
#   APP_API_TOKEN=t → TestClient GET /api/settings/providers with X-App-Token: t → 200
```

Result files: `r4-scratch/ask-results.json` (A: Table 2.2, Treaty, Alamo, Reséndez, quiz), `ask-results-B.json` (study guides, deck), `ask-results-w12.json`, `chat-results-w12.json`, `companion/results.json`, `companion/exam-result.json`, `companion/exam-debug.json`, `probe/ocr_*.json`, `ingest.log`.

---

## 8. Full code review (appended)

Comprehensive review of all backend Python, frontend TS/Svelte, Rust, and Office add-in JS files. Findings below are verified against the source. Items already covered in section 4 (R4-NEW-*) are not repeated.

### High severity

| ID | File:line | Bug | Fix |
|---|---|---|---|
| CR-1 | `common/migrate.py:119-124` | `executescript` issues an implicit COMMIT before running the script. If the migration fails mid-way, the `except BaseException` handler attempts `conn.execute("ROLLBACK")`, but the transaction is already committed. The rollback raises `OperationalError: cannot rollback - no transaction is active`, masking the original error and leaving the database half-migrated. | Use individual `conn.execute()` calls within an explicit transaction, or verify `conn.in_transaction` before attempting rollback. |
| CR-2 | `common/archive_notebook.py:208-209` | `UUID(turn.reply.trace_id)` and `UUID(c.chunk_id)` raise `ValueError` on malformed data, causing the entire archive export to fail with an unhandled exception. | Wrap in `try/except ValueError` or use `contextlib.suppress(ValueError)`. |
| CR-3 | `student_model/archive.py:173` | `next(s for s in archive.suites if s.suite_id == run.suite_id)` raises `StopIteration` if no suite matches, propagating and stopping the import. | Use `next((...), None)` and raise an informative error if `None`. |
| CR-4 | `student_model/learning.py:322` | `rows(...)[0]` raises `IndexError` if the query returns an empty list (e.g., run_id doesn't exist or was deleted). | Add `if not rows: raise ValueError("run not found")`. |
| CR-5 | `artifacts/edit.py:528` | `material.chunk_ids.index(artifact.sources[n - 1])` raises `ValueError` if a cited chunk was removed from the course. | Check `if artifact.sources[n - 1] in material.chunk_ids` before calling `.index()`. |
| CR-6 | `retrieval/trace.py:78` | `UUID(str(entry["chunk_id"]))` raises `ValueError` if the stored chunk_id is not a valid UUID, causing trace recording to fail. | Add `try/except ValueError` or validate UUID format before conversion. |

### Medium severity

| ID | File:line | Bug | Fix |
|---|---|---|---|
| CR-7 | `graph/edges.py:44` | `row[j] >= floor and row[j] > 0` excludes all negative similarities even when `similarity_floor` is configured as a negative value, making the floor meaningless for negative values. | Remove the `row[j] > 0` check or change to `row[j] >= floor` only. |
| CR-8 | `ingest/structure.py:171` | `boundary = r"\b" if title[-1:].isalnum() else ""` — when the title ends with a non-alphanumeric character (e.g., "Chapter 1:"), no boundary is appended, so the regex can match a prefix of a longer title (e.g., "Chapter 1" matches "Chapter 10"). | Use a lookahead `(?![A-Za-z0-9])` instead of `\b`. |
| CR-9 | `rag/segment.py:349` | Similarity indexing assumes `boundary_texts` is ordered as `[block0_first, block0_last, block1_first, block1_last, ...]`. If `windows` returns an empty tuple for a block, `bounded[0]` or `bounded[-1]` raises `IndexError`. | Check that `bounded` is non-empty before accessing elements. |
| CR-10 | `retrieval/rerank.py:119` | `start = 0 if candidate.partial else candidate.window_start` — for non-partial passages with a non-zero `window_start` (e.g., from a previous partial windowing), the text is incorrectly sliced. | Use `start = 0` for non-partial passages regardless of `window_start`. |
| CR-11 | `tutor/compose.py:820` | `if len(selected_phrase) >= 8 and selected_phrase in prompt.casefold(): return False` rejects questions where the correct answer appears in the prompt for legitimate reasons (e.g., "What is the capital of France?" where "France" is the answer). | Only reject if the answer is a substantial portion of the prompt, or use a more nuanced check. |
| CR-12 | `retrieval/funnel.py:753` | `picked.extend(chunks[index * len(chunks) // take] for index in range(take))` — if `len(chunks)` is not evenly divisible by `take`, some chunks are skipped. | Use `round(index * len(chunks) / take)` or ensure all chunks are covered. |
| CR-13 | `student_model/practice_support.py:37` | `run.correct_answers[index]` raises `IndexError` if `index` is out of range (e.g., suite was modified after the run was created). | Add bounds check or use `run.correct_answers[index] if index < len(run.correct_answers) else None`. |
| CR-14 | `common/body_limits.py:44` | `int(declared)` raises `ValueError` for very long digit strings in Python 3.11+ (4300-digit limit), causing a 500 error instead of a 413. | Wrap in `try/except ValueError` or use a length check before conversion. |
| CR-15 | `common/prompt_registry.py:137` | `section["text"]` raises `KeyError` if a prompt section in `prompts.toml` is missing the `text` key, with a confusing error message. | Use `section.get("text", "")` or wrap in `try/except` with a descriptive error. |
| CR-16 | `common/backups.py:793-794` | `backup_id.isalnum()` allows uppercase and all alphanumeric characters, but the ID is generated as `uuid4().hex` (lowercase hex). The validation is more permissive than necessary. | Use `re.fullmatch(r"[0-9a-f]{32}", backup_id)`. |
| CR-17 | `common/secrets.py:60-61` | TOCTOU race in `delete_api_key`: between `get_api_key` check and `keyring.delete_password`, the key could be deleted by another process, causing `PasswordDeleteError`. | Catch `keyring.errors.PasswordDeleteError` and ignore it (idempotent delete). |

### Low severity

| ID | File:line | Bug | Fix |
|---|---|---|---|
| CR-18 | `common/migrate.py:122` | f-string interpolation of `version` into SQL. Currently safe (regex-validated `\d{3}`), but fragile if the regex is ever relaxed. | Use parameterized query. |
| CR-19 | `common/provider.py:485-518` | Race condition in `_ADAPTATIONS` dict access; potential infinite loop in adaptation retry if the provider keeps returning 400 with the same detail. | Use `threading.Lock` and add a maximum retry count. |
| CR-20 | `common/storage.py:117-118` | `NamedTemporaryFile` creation failure (e.g., disk full) is outside the `try` block, so the file descriptor may not be closed. | Move creation inside the `try` block. |
| CR-21 | `common/encoders.py:128` | `pad_id or 0` defaults to `0` when `pad_id` is `None`, which may not be the correct padding token ID for the tokenizer. | Use `pad_id if pad_id is not None else 0` and log a warning. |
| CR-22 | `ingest/extract.py:272` | NUL byte stripping can silently corrupt UTF-16 content without BOM detection. | Only strip NUL bytes if the encoding is not a wide encoding. |
| CR-23 | `ingest/orchestrator.py:150` | `page_count` can be 0 for a corrupt/empty PDF, producing an empty `texts` list and a misleading "no usable text recognized" error. | Check `page_count == 0` before the loop and raise a specific error. |
| CR-24 | `ingest/extract.py:434` | `page_quality` can return negative values if `glyph_penalty` is large, which could cause issues if used elsewhere. | Clamp the result to `[0, 1]`. |
| CR-25 | `student_model/grading.py:75` | `_negated_before` checks only 3 words before a point; negation scope can be missed in longer sentences. | Increase the window or use clause-level negation detection. |
| CR-26 | `office_addin/service.py:351` | `hashlib.sha1(active_ca, usedforsecurity=False)` raises `TypeError` on Python 3.8. | Use `hashlib.sha1(active_ca)` without the flag. |
| CR-27 | `office_reader/package.py:74` | Off-by-one in read size check: if `_MAX_EXPANDED_BYTES - self._expanded` is 0, `stream.read(1)` could read 1 byte without triggering the overshoot detection. | Check `self._expanded >= _MAX_EXPANDED_BYTES` before reading. |
| CR-28 | `serve.py:63` | `stream.read(4096)` can raise `OSError` or `ValueError` on closed stdin. | Wrap in `try/except` and break on exception. |
| CR-29 | `artifacts/exam_style.py:119` | `Image.MAX_IMAGE_PIXELS` modification is not thread-safe; the `finally` block restores it, but an exception before the `finally` could leave it modified. | Use a context manager for save/restore. |
| CR-30 | `office_addin/host.py:103` | `self._thread.join(_STOP_TIMEOUT)` raises `RuntimeError` if `stop()` is called from within the server thread. | Add `if self._thread is not threading.current_thread()`. |

### Non-bugs (verified, no action needed)

The following were investigated and confirmed NOT to be bugs:

- `api/companion.py:167,244` — Upload size checks exist in called helpers (`office_reader/work_files.py:12`, `work_screenshot.py:12`).
- `api/artifacts.py:288` — Upload size check exists in `exam_style.py:622-623`.
- `api/settings.py:315` — Synchronous `httpx.get` is fine; all callers are sync `def` endpoints run in a threadpool.
- `api/conversations.py:245`, `courses.py:88`, `learning.py:141`, `settings.py:428` — Asserts are redundant type-narrowing; the conditions are unreachable.
- `api/data.py:179` — `subprocess.Popen` with list args and no `shell=True` is safe from injection.
- `api/artifacts.py:620-626` — `unique_path` always returns a fresh name; the loop makes progress and terminates.
- `common/providers.py:236,284-285,317` — Explicit `BEGIN IMMEDIATE` is redundant with `isolation_level="IMMEDIATE"` but not harmful.
- `common/storage.py:175` — `original_size == 0` is checked before division.
- `common/backups.py:450,604,606,676-679,773-775` — Acceptable for a local backup system.
- `common/config.py:28,90,109` — `Path.read_text` uses a context manager internally; `lru_cache` is acceptable for production.
- `common/db.py:74-76,101-103` — `zip(..., strict=True)` is correct; `deterministic=False` is correct for `now_utc()`.
- `common/queries/__init__.py:7,17` — Regex handles `\n`; `Path.read_text` uses a context manager.
- `common/settings_repo.py:16-19` — `get_setting` behavior is correct.
- `common/usage_repo.py:57,62,86` — `assert` usage is acceptable for internal invariants.
- `common/courses_repo.py:48`, `artifacts_repo.py:175,273,315`, `conversations_repo.py:142` — Same `assert` pattern; acceptable for internal invariants.
- `common/work_repo.py` — `WorkSession(**row)` is acceptable; schema mismatch indicates a serious bug.
- `common/course_archive.py:295-297,307-314` — `with` statements handle resource cleanup correctly.
- `common/generation.py:247-277,262-265` — `Operation` creation per `complete()` call is intentional; `except Exception` is appropriate.
- `common/model_profiles.py:57-58` — `raw.get("model", path.stem)` is acceptable.
- `common/lifecycle_config.py:46-48` — `ge=60` constraint is intentional.
- `ingest/worker.py:62,89` — Single-source claim and heartbeat interval are intentional design choices.
- `rag/store.py:196` — Error message could be more helpful but is not a bug.
- `retrieval/labels.py:81` — `int(None)` handling is correct.
- `retrieval/evals.py:294` — `seam_recall` is initialized with `dict.fromkeys`, so never empty.
- `tutor/answer.py:199` — `calls[-1]` is safe because `compose_chat` always calls `generate`.
- `tutor/chat.py:140` — Empty `history` is handled correctly.
- `tutor/quotes.py:58` — `position` exceeding `haystack` length is handled correctly.
- `tutor/workspace.py:90` — `compile()` raising `MemoryError` is acceptable (indicates a serious bug).
- `artifacts/content.py:223` — `int(n)` raising `ValueError` is caught and handled correctly.
- `artifacts/attribution.py:146` — Citation formatting is correct.
- `artifacts/mind_maps.py:101` — Iterating over all nodes is intentional.
- `artifacts/export.py:237` — Column width calculation handles empty rows correctly.
- `office_addin/certs.py:171` — `InvalidSignature` is caught correctly.
- `office_addin/manifest.py:41` — Empty string fallback to `"0"` is correct.
- `office_addin/live.py:187` — `work.revision` being `None` is handled correctly.
- `ingest/config.py:51` — Strict stage order validation is intentional.
- `retrieval/config.py:44` — `KeyError` on missing config key is correct (fail fast).
- `runtime/config.py:73` — `@cache` on config load is intentional.
- `ingest/runs.py:182` — `run.status.value` is safe because `_to_run` converts to enum.
- `ingest/pipeline.py:108` — Retry backoff overflow is intentional.
- `ingest/ocr_pages.py:22` — `parts.pop()` is safe because `len(parts) >= 1`.
- `student_model/inspection.py:125` — `r["correct"] == 1` works for both `True` and `1`.
- `office_reader/merge.py:96` — Word count comparison is a heuristic, not a bug.
- `rag/segment.py:405` — Error message could be more informative but is not a bug.
- `rag/funnel.py:494` — Floating-point precision guard is sufficient.
- `runtime/server.py:291` — `max(1, ...)` guard is sufficient.
- `main.py:108` — `migrate` is synchronous.
- `common/provider.py:341,362-365,372-373,414,475,822,913` — Import inside function is acceptable for circular import avoidance.
- `common/archive_notebook.py:21-25,497-499` — Imports are correctly placed.
- `common/work_archive.py:1-7` — Imports are correctly placed.
- `common/usage_repo.py:1-15` — Imports are correctly placed.
- `common/storage.py:1-30` — Imports are correctly placed.
- `common/sources_repo.py:1-19` — Imports are correctly placed.
- `common/settings_repo.py:1-11` — Imports are correctly placed.
- `common/course_memory_repo.py:1-7` — Imports are correctly placed.
- `common/course_memory.py:1-29` — Imports are correctly placed.
- `common/course_archive.py:1-44` — Imports are correctly placed.
- `common/courses_repo.py:1-22` — Imports are correctly placed.
- `common/conversations_repo.py:1-17` — Imports are correctly placed.
- `common/companion_config.py:1-5` — Imports are correctly placed.
- `common/citations.py:1-7` — Imports are correctly placed.
- `common/body_limits.py:1-13` — Imports are correctly placed.
- `common/backups_config.py:1-8` — Imports are correctly placed.
- `common/backups.py:1-31` — Imports are correctly placed.
- `common/artifacts_repo.py:1-19` — Imports are correctly placed.
- `common/answer_cache.py:1-22` — Imports are correctly placed.
- `common/maintenance.py:1-12` — Imports are correctly placed.
- `common/lifecycle_config.py:1-7` — Imports are correctly placed.
- `common/learning_config.py:1-6` — Imports are correctly placed.
- `common/generation_config.py:1-11` — Imports are correctly placed.
- `common/embeddings_config.py:1-7` — Imports are correctly placed.
- `common/generation.py:1-23` — Imports are correctly placed.
- `common/schemas/__init__.py` — Empty file is correct.
- `common/schemas/work.py` — No imports needed.
- `common/schemas/usage.py` — Imports are correctly placed.
- `common/schemas/tutor.py` — Imports are correctly placed.
- `common/schemas/source_content.py` — Imports are correctly placed.
- `common/schemas/office_live.py` — Imports are correctly placed.
- `common/schemas/mind_map.py` — Imports are correctly placed.
- `common/schemas/map_study.py` — Imports are correctly placed.
- `common/schemas/learning.py` — Imports are correctly placed.
- `common/schemas/ingestion.py` — Imports are correctly placed.
- `common/schemas/identity.py` — Imports are correctly placed.
- `common/schemas/base.py` — Imports are correctly placed.
- `common/queries/__init__.py` — Imports are correctly placed.
- `common/__init__.py` — Empty file is correct.
