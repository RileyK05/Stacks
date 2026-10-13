# Stacks — consolidated bug status after round 5 (commit 44503f0 "Fixes done!")

- **Date:** Oct 11–12, 2026. **Tester:** test gimp (Grok Bot) for Riley K.
- **Model:** MiMo `mimo-v2.6-flash`. **Material:** 5 Latino politics PDFs (Week1/2/3/5/6), `riley-doc.docx`, `riley-doc-table.xlsx`.
- **Companion files:** `RETEST-round5.md` (code-level retest, every item with file:line + repro), `RETEST-round4.md`, `RETEST-round3.md`, `RETEST-round2.md`, `DOCKET.md` (round 1, STK-001–048), `report-companion.txt` (round-1 Companion).
- This file adds: (1) which bugs survived multiple rounds, (2) the round-5 **GUI pass** results, which aren't in `RETEST-round5.md`.

---

## 1. Bugs that keep coming back (the tricky ones)

These were patched every round and each time failed in a new way. A narrow patch hasn't worked; each needs a design-level fix.

| Area | IDs | History | State now | Where |
|---|---|---|---|---|
| OCR of scanned pages | STK-003, NEW-1/2/4/10, R3-NEW-1/16, R4-NEW-l, R5-NEW-o/g/r | R1: scans skipped unless whole PDF scanned → R2: one giant request hits output cap, text on wrong page → R3: blank pages break the splitter, batches discarded → R4: refusals drop batches → R5: refusals fixed, but **timeouts / dropped connections still drop a whole 4-page batch** (per-page fallback only after a refusal) | Partial. Live GUI run: Week1 OCR "took too long" twice (12:26, 12:50 ET); raw provider error text reaches the Sources warning; failed pages listed twice | `ingest/orchestrator.py:252–295, 324–353`, `ingest/ocr_pages.py:31–34` |
| Formatting inside generated docs/slides | STK-038, R3-NEW-2, R5-NEW-k/l/e/t/u | R1: strict JSON drops all newlines, decks collapse to 1 slide → R3: sections survive, tables/bullets flatten → R4: "escape newlines" prompt ignored → R5: tables render, but glued bullets collapse, **U+2028 loses the whole study guide**, `<br>` in a cell splits a table, adjacent tables merge, code indentation stripped | Partial | `common/prompt_registry.py:96–101` (`strip_fence_echo`), `tutor/materials.py:21–60`, `common/provider.py:437` (strict schema still unconditional) |
| Short-answer grading | STK-037, R4-NEW-c, R5-NEW-b | R1: grading loses the quiz → R4: keyword match, wrong answers pass → R5: requires claims in original order, **correct reordered/passive answers fail** ("Texas was not annexed until 1845") | Partial. Rule-based matching can't judge meaning; consider model-graded with a rubric | `student_model/grading.py:287` |
| Quiz answer shuffling | R3-NEW-13, R4-NEW-b, R5-NEW-d | R3: every answer = A → R4: shuffle breaks "Both A and B" → R5: "Both of the above", "Neither A nor B", "(A) is right" still break | Partial | `tutor/compose.py:800–810` |
| Garbled Week 3 digits (Alamo) | STK-005, STK-023 | R1: invented "180–200" → R2: said illegible → R3: confident decode "1,800 / 600" → R4: said corrupted → R5: decodes again with a "read from context" note. Behaviour flips run to run because the corrupt page is **never flagged** (`pages_low_quality = 0` for Week3) | Partial | `ingest/extract.py` (`assess_pages`) |
| Search topic words | STK-039, R3-NEW-14, R4-NEW-g, R5-NEW-c | "8-slide", "10", "one-page" leaked into searches → fixed → now **number ranges are dropped** ("Weeks 1-5" → "first exam Weeks") | Partial (regressed for ranges) | `tutor/compose.py:454` |
| Essay critique fallacy check | R4-NEW-n, R5-NEW-a | R4: whole critique rejected unless exact fallacy label word → R5: any 4-letter overlap counts ("determine" ≈ "ad hominem") | Partial (now too loose) | `tutor/critique.py:251, 264` |
| Exam-style practice on MiMo | R4-NEW-o, R5-NEW-s | R4: `stem` vs `prompt` field mismatch → R5: field fixed, but 4/4 live runs fail (output cap on `write_questions`; dropped connection during quiz-image OCR, no retry) | Not working live | `artifacts/exam_style.py:600–613`, `configs/generation.toml:22` |

## 2. Bugs never attempted since round 1 (code untouched)

| Area | IDs | Symptom | Where |
|---|---|---|---|
| Retrieval ranking | STK-025, 044, 032, 026, R5-NEW-m/p | "Reproduce Table 2.2" says the table doesn't exist (now indexed, plain search finds it; retrieval pulls 0 Week1 passages). Week 3 quiz pulls the schedule slide → half the questions are about office hours. Follow-ups get false "not in the material". No relevance floor; duplicate passages; conversation pulls later queries off-topic | `retrieval/funnel.py` |
| Chat memory | STK-028, 030, 031, 029 | Keeps last 4 messages + a short summary; earlier answers cut to 600 chars with citations stripped; artifacts remembered by title only; "what did you quiz me on?" answered from readings; summary fails silently | `tutor/chat.py` (`RECENT_MESSAGES = 4`, `EXCERPT_CHARS = 600`) |
| Companion edit flow | C-1, C-4, C-8, STK-045/C-5, C-3 | Pending request + Retry trap; no Insert/Replace (Copy only); everything "Partial or unverified capture"; xlsx shown as `A1=…; B1=…` with a "no shared strings part" warning | `WorkCompanion.svelte`, `tutor/work.py:398–411` |
| Auto source type | STK-018 | Every PDF typed "Notes" (again in R5 GUI) | — |
| Smaller | STK-024, 033, 046, 042, 027, 047, 036 | Citation markers not clickable; no edit intent for an existing table; course export says "Downloads" but falls back to `$HOME`; Office export only on the saved-artifact page; no streaming; slide viewer gaps; "from Qn" label (last four reclassified as enhancements) | `api/data.py:81`, `common/config.py:113–115` |

## 3. Round-5 GUI pass (Oct 11, 2026, app built from 44503f0, MiMo, no OS keyring)

### 3a. Settings, course, upload
| # | Finding | Severity |
|---|---|---|
| G-1 | **Keyring fix confirmed:** Settings loads with no keychain; providers and model cards listed (NEW-9 fixed in GUI). | ✅ |
| G-2 | Default models card says Answers: "Choose a model" (nothing selected), yet Background work says "Same as answers (mimo-v2.6-fla…" (text truncated) and the course page shows "mimo-v2.6-flash · Default". Contradictory, and the dropdown value is cut off. | medium |
| G-3 | "Your data" shows "Local models 666 MB", but all six local models show only a Download button and "Not running"; no indication any model is installed. | low |
| G-4 | Local model card renders as an empty grey box (~100 px) on first load in the default window size; fills in only after a resize. | low |
| G-5 | Sizes are MiB labelled "MB": Week1 shows 9.1 MB (file is 9.5 MB), Week2 15.3 MB (16.0 MB), total 58.7 MB. File dialog and app disagree. | low |
| G-6 | No upload indicator: after picking files the page stays "No sources yet / 0" for 1–2 s, then rows appear. | low |
| G-7 | No per-file progress: only "Queued" / "Reading scans" with a spinner; no page count, %, or ETA. Sources-tab dot has no tooltip. | low (STK-017) |
| G-8 | All 5 PDFs auto-typed "Notes" (STK-018 still). Type never shows that Auto chose it. | medium |
| G-9 | List order = upload order (Week1…Week6), correct (STK-019 confirmed as by design). | ✅ |
| G-10 | Rename (inside course header): the field isn't auto-focused after clicking Rename; header shifts ~7 px; the "LP" avatar colour changes from pink to blue after a rename. | low |
| G-11 | No rename on the My courses card; right-click shows a browser-style link menu ("Open Link in New Window / Download Linked File / Inspect Element"). | low |
| G-12 | Settings page wording: near-duplicate "connections are optional" text; course page uses "Sources" and "Materials" interchangeably. | trivial |
| G-13 | Indexing is very slow on MiMo: Week1 needed ~2 h (two OCR timeouts), Week3 OCR still running hours later. (Slowness itself isn't a bug, but the lost pages are — see §1 OCR.) | info |

(The course saving as "Latino Politics -" without "R5" was dropped keystrokes during the test, not an app bug: renaming saved the full name.)

### 3b. Companion (riley-doc.docx, then riley-doc-table.xlsx)
| # | Finding | Severity |
|---|---|---|
| C5-1 | **Improved:** docx edits now go through; "Rewrite the introduction to be more concise" edited the real intro (paragraph 19). xlsx Summarize correctly describes the spreadsheet (C-2 not reproduced). Nothing written back to either file (hashes/mtimes unchanged). | ✅ |
| C5-2 | **Only 4 of 31 sections are sent per request, a different 4 each time** (Summarize: 1, 2, 3, 28; rewrite: 1, 4, 6, 7; tone: 4, 8, 20, 28). The model then says the paper is "missing" sections or "cuts off paragraph 19 mid-word at 'nat'", although "Inspect connected text" shows the full 54,913 characters were captured. Summaries are partial; edits claim text is missing when it isn't. | high |
| C5-3 | **"Add a total row to this table" on the xlsx fails every time**: "The proposed edit did not replace an exact passage from the reviewed draft. Try again or select a passage." Spreadsheets have no passage to select; Retry fails identically; request stays pending, all action buttons disabled until cleared. | high |
| C5-4 | First Summarize on the docx failed: "The answer contained an unsupported source reference. Try again." + "This request was not confirmed…". Retry worked (~1.5 min total). | medium (C-4) |
| C5-5 | "Saving this request and its response…" (with Retry / Clear pending) is shown for the entire 30–70 s generation, so a working request looks stuck. | medium (C-1) |
| C5-6 | No send button; Enter inserts a newline, Ctrl+Enter does nothing. Free text only goes out via the action buttons. First "make the tone more formal" attempt went out as a bare "Suggest an edit" (typed text not used) and returned an unrelated edit. | medium |
| C5-7 | Still Copy only ("Copy response", "Copy proposed replacement"); no Insert / Replace / Apply. | medium (C-8) |
| C5-8 | Both files labelled "Partial or unverified capture"; xlsx also gets "no shared strings part; only inline cell values are read" — alarming for a normal complete sheet. Sheet name "Doc table" not shown. | low (C-5, C-3) |
| C5-9 | "Close document connection" only hides the connect panel; the file stays attached. No real detach. Panel says "No document connected" while that link is shown. | low |
| C5-10 | Companion is a separate 286×530 floating window (not docked), cramped, scrolls internally; maximizing gives a second title bar. Pin and book icons have no tooltips. | low (C-6/C-7) |
| C5-11 | Window often doesn't repaint until the mouse moves, so states look frozen. | medium |
| C5-12 | Red error banner renders at the top of the scroll area, far from the pending-request bar at the bottom. | low |
| C5-13 | Essay kind / Critic score controls still shown with a spreadsheet attached; old docx conversation stays in the transcript under the newly attached xlsx. | low |
| C5-14 | Internal name `course_evidence` leaks into replies ("`course_evidence` is empty"). | low |
| C5-15 | Minor rendering: "Formal list (primary)" shown as "Formal list — primary". | trivial |

### 3c. Not yet done in the GUI
Waiting for indexing to finish: chat checks (Alamo, Table 2.2, Reséndez, "Sources used (n)"), quiz (answer positions, Week 3 quiz, short-answer grading), study guide (table + bullets, "Weeks 1-5"), 8-slide deck, export save dialog ("week3", "week3.final", "notes.txt"), OCR warning text in the Sources panel, polling through a long upload, exam-style practice, critique.

## 4. Round-5 code-level new bugs (full detail in `RETEST-round5.md` §4)

| ID | Sev | Summary | Where |
|---|---|---|---|
| R5-NEW-l | high | U+2028 line separators → `strip_fence_echo` makes invalid JSON → whole study guide withheld | `common/prompt_registry.py:96–101` |
| R5-NEW-o | medium | Transient OCR failure drops a whole 4-page batch; raw provider error shown to student | `ingest/orchestrator.py:252–295` |
| R5-NEW-s | medium | Exam-style practice never completes on MiMo (output cap; no retry on dropped connection) | `artifacts/exam_style.py:600–613` |
| R5-NEW-a | medium | Fallacy check accepts any 4-char overlap | `tutor/critique.py:264` |
| R5-NEW-b | medium | Grading fails correct reordered/passive answers | `student_model/grading.py:287` |
| R5-NEW-c | medium | "Weeks 1-5" range dropped from search topic | `tutor/compose.py:454` |
| R5-NEW-d | medium | Shuffle gaps: "Both of the above", "Neither A nor B", "(A) is right" | `tutor/compose.py:803–810` |
| R5-NEW-k | medium | Glued bullets collapse to one | `tutor/materials.py:21–45` |
| R5-NEW-e | low | `_reflowed` strips indentation (code blocks, nested lists) | `tutor/materials.py:36` |
| R5-NEW-f | low | `has_body` rejects short key-term paragraphs ("Manifest Destiny") | `tutor/materials.py:48–60` |
| R5-NEW-g | low | Leading + trailing OCR separator still fails split | `ingest/ocr_pages.py:31–34` |
| R5-NEW-h | low | Refusal regex anchored to whole reply; variants missed | `common/provider.py:137` |
| R5-NEW-i | low | Rewrite guard lets question-phrased rewrite requests through | `tutor/critique.py:86` |
| R5-NEW-j | low | OCR warning no longer length-capped | `ingest/orchestrator.py` |
| R5-NEW-m | low | Table 2.2 chunked into title / table / note pieces | ingest segmentation |
| R5-NEW-n | low | Critique can lead with raw `unsupported_claim:` label | `tutor/critique.py` |
| R5-NEW-p | low | Conversation context pulls "Reproduce Table 2.2" off-topic | `retrieval/funnel.py` |
| R5-NEW-q | low | Windows: failed upload may leave temp file (unverified here) | `common/storage.py:117–136` |
| R5-NEW-r | low | Failed OCR pages listed twice in warning | `ingest/orchestrator.py:324–353` |
| R5-NEW-t | low | `<br>` in a table cell splits the table | `tutor/materials.py:21–45` |
| R5-NEW-u | low | Two adjacent tables merged into one | `tutor/materials.py:21–45` |

Also open: NEW-6 (shell `LLM_API_KEY` overrides `.env`, by design); R3-NEW-10 (OCR usage rows with 0 tokens); R3-NEW-15 (`docs/docket.md` gone while `notes.md` still cites it).

## 5. What got better in round 5
- Refusals no longer cost OCR pages; refusal check no longer fires on normal history text.
- Essay critique completes (5/5 on MiMo, was 0/2).
- Companion "rewrite the introduction" targets the real introduction; xlsx Summarize reads the xlsx.
- Study-guide tables render as tables; quiz answer positions vary.
- Settings works with no OS keyring; course-page polling no longer capped; dropped connections retried for chat.
- OCR warnings in plain sentences; text cleanup complete; export filename handling fixed.

## 6. Suggested priorities
1. **Retrieval ranking** (`funnel.py`): never touched, causes the most wrong answers (Table 2.2, Week-scoped quizzes, false refusals).
2. **OCR resilience:** per-page fallback after *any* batch failure, not just refusals; keep raw provider errors out of student-facing text.
3. **Companion context:** send the whole captured document (or a coverage-aware selection the model is told about), and give spreadsheets an edit path; fix the pending/Retry trap.
4. **Generated-doc formatting:** drop strict `json_schema` for long text fields (or per-model `json_object`), and normalize U+2028/U+2029 before parsing.
5. **Chat memory** (`chat.py`): longer recent window, keep citations, remember artifact content.
6. **Grading:** model-graded short answers against the key instead of word/order rules.
