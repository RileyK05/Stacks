# AGENTS.md

This file is the working contract for contributors and AI agents on this project.
It is deliberately kept short and enforced. If it conflicts with a task, the task
should be questioned, not the file ignored.

## Project

Academic assistant that accumulates a source-grounded course memory and a student
error model, then recommends what to study next. Deployed for a small user base;
data is owned by the operator, inference uses hosted model APIs that do not
retain data. See `project.md` for the plan, `system.md` for architecture. Read
both before making structural decisions.

## Golden rules

1. **Source grounding is sacred.** Every substantive answer, claim, or memory
   object must retain evidence links (source, locator). Never answer an
   uploaded-material question without showing sources.
2. **Inspectable over impressive.** Show what was retrieved, what was inferred,
   and why a concept is flagged weak. No opaque black-box scores.
3. **Evaluation is the center, not an afterthought.** No feature ships without a
   way to measure whether it regressed. Prefer boring, verifiable baselines over
   clever-but-unverifiable ones.
4. **Data ownership.** Course data and study history live in our own Postgres.
   Inference goes to a hosted model API that does not retain data. No
   auto-solving graded work.
5. **ML earns its role.** Begin with retrieval, structure, and simple baselines.
   Add models/fine-tuning only for a documented, versioned baseline failure.
6. **Destruction leaves a distilled record.** Deletes archive a compressed
   summary first (course memory, citation snapshot); account deletion has a
   7-day grace period. Never silently destroy evidence.

## Engineering tradeoff

Code is cheap to write (LLMs generate it); rework and brittleness are expensive.
When a better engineering decision costs slightly more code, prefer the better
decision. Don't gold-plate — but don't pick a fragile shortcut just to save lines.
Prioritize correctness, clear seams, and future extensibility over brevity.

## Structure

```
configs/         # ingestion/retrieval/tutor configs (versioned)
data/
  raw/           # original course files — GITIGNORED
  processed/     # extracted text, chunks — GITIGNORED
  eval/          # eval questions + held-out sets (committed)
src/
  backend/
    ingest/        # parse, locators, token-bounded chunks
    retrieval/     # TOC-guided retrieval + metadata filters
    memory/        # concept/dependency store + table of contents
    student_model/ # attempts, mastery, error model
    tutor/         # source-grounded answers + cold probes
    evals/         # retrieval/answer/probe/student-model evaluation
    common/
      schemas/       # Pydantic models, one module per storage layer
      config.py      # .env loading + settings
      db.py          # the single Postgres connection seam
      migrate.py     # versioned migration runner
      migrations/    # 00X_*.sql, append-only, applied in order
  frontend/        # web UI; talks to backend only via its API
tests/           # pytest; mirrors src/backend/ layout
runs/            # experiment + eval logs — GITIGNORED
docs/
  notes.md       # append-only decision log (never delete entries)
  decisions/     # resolved design decisions
```

The six subsystems map 1:1 to `src/backend/<package>`. Cross-cutting code
(Pydantic schemas, logging, config, DB access) lives in `src/backend/common/` to
avoid circular imports. Keep packages cohesive and imports acyclic. Backend and
frontend are separate codebases; frontend talks to backend only via its API.

## Conventions

- **Code style:** no comments unless they explain a non-obvious decision. Prefer
  self-documenting names. Follow existing patterns; match surrounding code.
- **Language:** Python. Use Pydantic for validated schema objects, especially
  anything persisted or crossing a boundary.
- **Database:** Postgres via raw SQL (no ORM). Queries live in
  `common/queries/*.sql`; schema changes are new numbered files in
  `common/migrations/` — never edit an applied migration.
- **Config:** tunable/versioned parameters in `configs/`, not hardcoded.
  Credentials in `.env` (gitignored), loaded via `common/config.py`.
- **Extensibility:** `kind`, `locator_type`, `content_type`, `claim_type`, and
  `target_type` are free strings so new types need no schema change. Known
  values are documented in `schemas/base.py` (`KNOWN_*` constants).
- **No secrets:** never log or commit keys, tokens, or course materials with
  classmates' work.
- **Commits:** concise messages matching repo style; only commit when asked.
- **Design log:** record schema/design concerns and decisions in `docs/notes.md`
  (append-only; resolved items move to Closed with a date).

## Commands

Run from the project root, using the venv:

```
.venv/Scripts/python -m pytest                        # tests
.venv/Scripts/python -m ruff check .                  # lint
.venv/Scripts/python -m mypy src                      # typecheck
.venv/Scripts/python -m src.backend.common.migrate    # apply DB migrations
```

All three checks must pass before declaring work done. `.env` must exist with
Postgres credentials for DB work (see `config.py` for expected keys).

## Workflow expectations for agents

- Read `project.md` and `system.md` before making structural changes.
- Before writing code, look at existing patterns and reuse `src/backend/common/`.
- Verify changes run and, where possible, pass tests + lint + typecheck.
- Never commit unless explicitly requested.
