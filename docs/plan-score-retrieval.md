# Plan: score-based retrieval (route → wide recall → rerank → floor)

Status: **Phases 0–3 implemented and green; Phase 4 (switchover + docs) awaits
the user's calibration/test run.** Phases 0–3 landed with tests; `[rerank]
mode` ships `top_k` and `score` is opt-in. When the default flips: record the
decision in `DECISIONS.md` (B-15, floor values), update `system.md` (already
describes both modes), then delete this file.

Replaces fixed-count retrieval (`final_k = 10` slots split per source, then
`generation_k = 6`) with: parse addresses from the question, filter on them,
pull a wide pool, let the cross-encoder score everything, and keep what clears
a relevance floor. Embeddings, the keyword index and the graph all stay.

Bugs this targets: STK-025/044 (Table 2.2 indexed but not retrieved), STK-039
(Week 3 quiz pulls the schedule slide), R5-NEW-m (table title/body/note split),
R5-NEW-p (follow-up pulled off-topic), STK-026 (no relevance floor), STK-032
(duplicate passages). Evidence for each is in `docs/RETEST-round5.md`.

---

## Rules for the implementer

- Read `docs/AGENTS.md` first. Its conventions are binding: raw SQL in
  `src/backend/common/queries/*.sql`, tunables in `configs/*.toml`, Pydantic
  for config, no comments unless they explain a non-obvious decision, match
  surrounding style.
- **The working tree already has many uncommitted changes from other work.
  Do not revert, reformat, or "clean up" any file you were not told to edit.**
  Do not commit.
- Work one phase at a time. At the end of each phase run, from the repo root:
  `.venv/Scripts/python -m pytest`, `.venv/Scripts/python -m ruff check .`,
  `.venv/Scripts/python -m mypy src`. All three must pass. Then **stop** and
  hand the diff (`git diff` plus new files) back for review. Do not start the
  next phase until the review says so.
- Every behavior change sits behind config so it can be turned off. Phase 3
  ships disabled by default.
- If an instruction here contradicts the code you find, stop and report it.
  Don't guess. Line numbers below are from 2026-10-12 and may drift.

## Root causes (confirmed by reading the code)

1. **Keyword search can't see "Table 2.2".** `funnel._keyword_tokens` drops
   single-character tokens, so "Reproduce Table 2.2" becomes
   `"reproduce" OR "table"`. Every table in the course matches equally. A
   plain FTS phrase query `"table 2.2"` returns exactly the right 3 chunks
   (RETEST-round5 §3b).
2. **"Week 3" has the same problem.** It becomes `"week"`, which matches the
   schedule slide in every lecture. Sources are named per week (`Week1…`,
   `Week3…`), but nothing uses the filename as a filter.
3. **Fusion caps before the reranker sees anything.** `fuse()` keeps 10
   (`final_k`) with a minimum of one slot per source, and the reranker only
   reorders those 10. Anything fusion dropped can't be recovered.
4. **Follow-ups inherit old topics.** `tutor/chat.py::retrieval_query`
   appends previous questions to any topic of 12 words or fewer
   (`FOLLOW_UP_MAX_WORDS`), so "Reproduce Table 2.2" gets searched together
   with three earlier Reséndez questions.
5. **Table captions and notes are separate chunks.** `rag/segment.py::_blocks`
   detects a markdown table but only attaches the preceding block when it
   ends with `:`. A caption line ("TABLE 2.2 Race of …") and a following
   "Source:/Note:" block become their own chunks.

---

## Phase 0: evals on real material (measure before changing)

Goal: a repeatable retrieval eval on the user's course that shows the current
failures as numbers. Nothing in retrieval changes in this phase.

1. Extend `src/backend/retrieval/evals.py` case format (keep old cases valid):
   - `expected_labels` (existing): unchanged.
   - `expected_source` (new, optional): substring of a source filename,
     case-insensitive. The case reports `source_share`, the fraction of
     retrieved passages from matching sources.
   - `min_source_share` (new, optional float, default 0.0): the case hits only
     if `source_share >= min_source_share` (plus the label check when labels
     are given).
   - `expect_empty` (new, optional bool): a question the material can't
     answer. It hits when retrieval returns nothing. Allow
     `expected_labels: []` only when `expect_empty` is true (today's loader
     rejects empty labels; keep that rejection otherwise).
   - Report `mean_source_share` and `empty_correct` in `EvalSummary.__str__`.
2. Add `scripts/eval_retrieval.py`, a CLI that opens a given SQLite database
   path, loads a cases file, runs `run_eval` (read `run_eval`'s signature
   first; it may need a query-embedding function, so pass
   `provider.embed_query`), and prints the summary. Arguments: `--db`,
   `--cases`, `--mode {top_k,score}` (`score` only becomes valid after
   Phase 3). Read-only on the database. Follow the style of
   `scripts/eval_passages.py`.
3. Add `data/eval/retrieval/real_cases.example.json` with the cases below. The
   user fills in exact locator labels from their own database. Course
   content stays out of the repo; the questions and labels are fine.
   - "Reproduce Table 2.2" → `expected_source: "Week1"`, the label of the page
     holding Table 2.2.
   - "Make a 10-question multiple-choice quiz on Week 3" →
     `expected_source: "Week3"`, `min_source_share: 0.8`.
   - "Create a study guide for the first exam covering Weeks 1-5" →
     `min_source_share` against Week1–5 (support a `|`-separated
     `expected_source` list).
   - At least 2 `expect_empty` questions on topics the course doesn't cover.
   - At least 5 ordinary concept questions with known pages.
4. Tests in `tests/test_retrieval.py` (or a new `tests/test_retrieval_evals.py`):
   the new fields load, old `cases.json` still loads, `expect_empty` scoring,
   `source_share` math.

**Acceptance:** the script runs against the user's database and the Table 2.2
and Week 3 cases fail, matching the retest. Save the printed baseline in the
review handoff.

## Phase 1: address routing (no reranker changes)

New module `src/backend/retrieval/route.py`, pure functions with no database
access except `source_weeks`.

```python
@dataclass(frozen=True)
class Addresses:
    labels: tuple[str, ...]   # normalized, e.g. "table 2.2"
    weeks: tuple[int, ...]    # sorted, unique

def parse_addresses(text: str) -> Addresses
def label_phrase(label: str) -> str   # FTS5 phrase, e.g. '"table 2 2"'
def source_weeks(conn, course_id) -> dict[UUID, int | None]
```

1. **Labels.** Case-insensitive match of a kind word followed by a number:
   kinds come from config `[route] label_kinds` (default: `table, figure,
   fig, chart, exhibit, equation, eq, theorem, lemma, definition, example,
   exercise, problem, section, chapter`). The number is
   `\d+(?:\.\d+)*[a-z]?`. Normalize `fig` to `figure` and `eq` to `equation`,
   lowercase. `label_phrase` splits the label with the same tokenization FTS5
   uses (letters and digits, **keeping single characters**) and returns one
   quoted phrase, so "Table 2.2" becomes `"table 2 2"`. It must not match
   "Table 2.20" (test this).
2. **Weeks.** Match `week`, `weeks` or `wk` followed by a number or range:
   "Week 3", "week3", "Weeks 1-5", "weeks 1 to 5", "weeks 1–5" (en dash). A
   range expands to every week in it. Ignore weeks outside 1–52.
3. **`source_weeks`.** Infer a source's week from its filename with
   `(?i)(?<![a-z])(?:week|wk)[\s_-]*0?(\d{1,2})(?!\d)`, so "Week1.pdf" is 1
   and "Week 10 notes" is 10, and "Week1" never matches "Week10". No schema
   change. Put the SQL (`source_id, filename` for a course, live sources
   only) in `retrieval.sql`.
4. **New SQL `label_candidates`** in `retrieval.sql`: a copy of
   `keyword_candidates` taking a phrase `:match`. Same course, status and
   `:source_ids` filters.
5. **Wire into `funnel.retrieve`:**
   - `addresses = route.parse_addresses(query)`, skipped when
     `[route] enabled = false`.
   - Week filter: the sources whose week is in `addresses.weeks`,
     intersected with the caller's `source_ids` (None means all). **Fail
     open:** if the intersection is empty, keep the original `source_ids` and
     record `week_filter: "no_match"`. Then use the narrowed `source_ids` for
     every seam.
   - Label pins: for each label, run `label_candidates` (limit from config
     `[route] label_limit`, default 5) under the same `source_ids`. Give
     those candidates the new layer `LABEL = "label"`.
   - Pinned candidates always go into the final result ahead of fused
     results, deduped by `chunk_id`. In top-k mode they count toward
     `final_k`, and pins win over fused results.
   - Add `route: dict` to `RetrievalResult` (labels, weeks, filtered
     source count, `week_filter` status) and store it in the retrieval
     trace. Read `retrieval/trace.py` and put it under a new `route` key in
     the existing JSON. **No schema change.**
6. **R5-NEW-p.** In `tutor/chat.py::retrieval_query`, when
   `route.parse_addresses(question)` finds any label or week, return the
   topic alone without previous questions.
7. **Rerank must not drop pins.** In `rerank.select_for_generation`,
   candidates whose layers include `LABEL` are always kept, first, before the
   `generation_k` cut. They still go through `bound_passages` and the token
   budget.
8. Config: add a `[route]` section to `configs/retrieval.toml` (`enabled`,
   `label_kinds`, `label_limit`), a matching Pydantic model in
   `retrieval/config.py`, and bump `retrieval_config_version` to "4". Update
   `tests/test_config.py`.
9. Tests (`tests/test_route.py` plus additions to `tests/test_retrieval.py`):
   - Parsing: labels (incl. `Fig. 3`, `Table 2.2a`), weeks (single, range,
     en dash, "weeks 1 to 5", out of range ignored), nothing found.
   - `label_phrase`: "Table 2.2" matches a chunk with "TABLE 2.2 Race …" and
     not one with "Table 2.20".
   - `source_weeks`: Week1 vs Week10, `wk_03`, no week.
   - The funnel with a seeded course of two sources ("Week1 …", "Week3 …"):
     a Week 3 question returns only Week3 chunks; a question naming week 9
     falls open; a Table 2.2 question returns the table chunk first even when
     many other chunks contain "table".
   - `retrieval_query`: a short follow-up naming "Table 2.2" doesn't include
     previous questions; one without an address still does.
   - Rerank: a pinned candidate survives even when the reranker scores it
     last (monkeypatch `provider.rerank_scores`).

**Acceptance:** the Phase 0 Table 2.2 and Week 3 cases now hit on the user's
database. Other cases don't get worse (report before and after).

## Phase 2: keep table captions and notes with the table (R5-NEW-m)

In `src/backend/rag/segment.py::_blocks`:

1. A block that is **only a caption line** (regex
   `(?i)^\s*(table|figure|fig\.?|chart|exhibit)\s+\d+(\.\d+)*[a-z]?\b.*$`,
   one or two lines, under 200 characters) directly before a `table` block
   merges into that table, and the merged kind is `table`.
2. A block directly after a `table` that starts with
   `(?i)^\s*(source|sources|note|notes)\s*[:.]` and is under 600 characters
   merges into the table.
3. Respect the existing token target. `table` is in `_ATOMIC`, so an atomic
   table may exceed it; allow the caption or note merge to exceed it by the
   caption or note size only, like `_absorb_thin` does.
4. Bump the passage policy version in `configs/passages.toml` (`version = "4"`)
   so existing indexes are marked stale and re-segment on reindex. Confirm by
   reading `rag/store.py` how `segmentation_version` drives staleness. If it
   doesn't, report back instead of inventing a mechanism.
5. Tests in `tests/test_segment*.py` (find the existing segment tests):
   caption + table becomes one chunk, table + "Source: …" becomes one chunk,
   a caption followed by prose doesn't merge, and a long note over 600
   characters doesn't merge.

**Acceptance:** after reindexing Week1, Table 2.2 is one chunk. The Phase 0
eval doesn't regress.

## Phase 3: score mode (wide pool, rerank, floor). Ships off.

1. Config in `retrieval.toml`:
   ```toml
   [rerank]
   mode = "top_k"        # "top_k" (today) or "score"
   pool_limit = 60       # max candidates the cross-encoder scores
   min_score = -1000.0   # absolute floor (raw cross-encoder logit); set by calibration
   max_drop = 1000.0     # also drop anything this far below the best score; set by calibration
   [score]
   keyword_limit = 50
   embedding_limit = 50
   graph_limit = 20
   ```
   The sentinel values keep everything until calibrated. Add these to the
   Pydantic models and add a validator that `mode` is one of the two values.
2. `funnel.retrieve`, score mode:
   - Use the `[score]` seam limits.
   - Don't call the slot allocation in `fuse()`. Merge seams exactly as
     `fuse` does (normalize, union layers, max rank), dedupe, order by merged
     rank, and cut to `pool_limit`. Pins go first and don't count toward the
     cut. Factor the merge part out of `fuse()` into a helper both paths
     share. **Don't change top-k behavior.**
   - Still apply `surrounding_context` afterward, exactly as now.
3. **Dedupe (STK-032)** in both modes: candidates whose normalized text
   (casefold, collapse whitespace) has the same SHA-256 count as duplicates.
   Keep the higher-ranked one and union their layers. Test it.
4. `rerank.select_for_generation`, score mode:
   - Score all non-context anchors as now.
   - Keep pins (Phase 1). Keep other anchors with
     `score >= min_score and score >= best - max_drop`.
   - Order by score and apply the existing `_with_context` token budget. No
     `generation_k` cut in score mode, since the token budget is the cap.
   - If the reranker fails, fall back to today's top-k behavior (fused order,
     `generation_k`) and log it, as it does now.
   - Return the scores too, so traces can show them. Extend the trace with
     `rerank: {mode, kept, dropped, min_score, max_drop}`.
5. **Empty after the floor.** `tutor/compose.py::compose_answer` currently
   continues with zero candidates. When `select` returns nothing for a
   non-empty input, raise a new `rerank.NothingAboveFloorError`. Each caller
   of `select_for_generation` must map that to its existing "nothing
   relevant" path: `tutor/answer.py` uses `NothingRelevantFoundError`. Check
   `tutor/work.py`, `tutor/office.py`, `artifacts/edit.py` and
   `evals/answer.py` and report what each does today before changing it.
   `artifacts/exam_style.py::_passages` calls `funnel.retrieve` without
   reranking; leave it on top-k and note it in the handoff.
6. **Calibration:** add `scripts/calibrate_rerank.py`. For each Phase 0 case
   it runs score-mode retrieval with the floor disabled, scores the pool, and
   writes a CSV of `case, chunk_label, source, score, relevant` (relevant =
   the label or source matches the case's expectation). It prints, for a grid
   of `min_score` and `max_drop` values, recall, precision and empty-correct
   across cases, and suggests the pair with the best F1 that keeps recall at
   100% on the label cases. **It doesn't write config.** The human picks the
   values.
7. Tests: score mode keeps exactly the candidates above the floor
   (monkeypatched scores); `max_drop` works; pins survive the floor; a
   reranker exception falls back to top-k; all-below-floor raises
   `NothingAboveFloorError` and `answer.py` turns it into the existing
   refusal; top-k mode output is unchanged against the existing tests.

**Acceptance:** with `mode = "score"` and calibrated values, the Phase 0 eval
on the user's database beats top-k on precision and `empty_correct` without
losing recall on the label cases. Report both runs side by side.

## Phase 4: switch over (after the user tests)

1. The user runs the tester with `mode = "score"` and the calibrated
   `min_score` and `max_drop`.
2. If it holds, set `mode = "score"` as the default, keep `top_k` as the
   fallback path, and bump `retrieval_config_version`.
3. Docs: rewrite the retrieval section of `system.md` (the flow and what is
   tunable), add the decision to `DECISIONS.md` (top-k vs score, with the
   eval numbers), add a lesson to `notes.md` (single-char token drop and
   filename weeks), then delete this file.

---

## Deferred (not in this plan)

- Expanding up the container tree (pull the parent section of a hit).
  `surrounding_context` already covers adjacent passages; revisit if evals
  show missing context.
- A `sources.week` column with user override. Filename inference first; add
  the column only if filenames turn out unreliable.
- A different reranker. Only `cross-encoder/ms-marco-MiniLM-L6-v2` has an ONNX
  spec (`common/encoders.py::RERANKER_SPECS`). A new one needs a pinned spec
  and `scripts/check_encoders.py` parity, and it's a separate change.
- Exam-style practice retrieval (`artifacts/exam_style.py`) moving to score
  mode.

## Notes

- Retrieval, routing and the floor are model-free: they use the in-process
  embedder and cross-encoder only. The chat model choice (MiniCPM or not)
  affects answer quality in end-to-end tests, not these eval numbers.
- Answer-level testing should use the user's chosen non-MiniCPM model. Phase 0
  is the retrieval-only gate; the user's tester covers end to end.

## Review checkpoints

| After | Reviewer checks |
|---|---|
| Phase 0 | eval fields, baseline numbers match the retest failures |
| Phase 1 | regexes and boundary tests, fail-open week filter, pins can't be dropped, trace has `route` |
| Phase 2 | merge rules don't swallow prose, staleness really triggers reindex |
| Phase 3 | top-k path byte-for-byte unchanged, empty handling at every caller, calibration output |
| Phase 4 | numbers in DECISIONS.md, docs updated, this file deleted |
