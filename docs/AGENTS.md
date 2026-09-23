# AGENTS.md

This file is the working contract for contributors and AI agents on this project.
It is deliberately kept short and enforced. If it conflicts with a task, the task
should be questioned, not the file ignored.

## Project

Academic assistant that accumulates a source-grounded course memory and a student
error model, then recommends what to study next. Deployed for a small user base;
data is owned by the operator, inference goes to hosted model APIs that do not
retain data (generation) and a self-hosted in-process embedding model (granite
R2 — course text never leaves the machine). See `docs/project.md` for the plan,
`docs/system.md` for architecture. Read both before making structural decisions.

> All three docs (this file, `docs/project.md`, `docs/system.md`) live in
> `docs/` — paths in code/tests refer to them as `docs/...`.

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
   Generation goes to a hosted model API that does not retain data; embeddings
   are self-hosted in-process (no data leaves). No auto-solving graded work.
5. **ML earns its role.** Begin with retrieval, structure, and simple baselines.
   Add models/fine-tuning only for a documented, versioned baseline failure.
6. **Destruction leaves a distilled record.** Deletes archive a compressed
   summary first (course memory, citation snapshot); account deletion has a
   7-day grace period. Never silently destroy evidence.

## Memory vocabulary (read before touching anything named "memory")

Full definition: `docs/decisions/007_memory_model.md`. That file wins over
any other doc or code name. Summary:

- **User memory (root)** — per-user, lifelong, behavioral ("teach THIS
  person with visuals/analogies") + cross-course history. The ONLY layer
  that may change how the model behaves.
- **Course memory (child)** — per-user per-course focus record ("what THIS
  person struggles with in THIS course"). Main user of the course (its
  owner) only. Facts about understanding; never behavior instructions;
  never shared with other users. Survives course deletion.
- **Course knowledge / TOC** — what the course SAYS (concepts, evidence)
  and the index for FINDING it. Shared per-course state. Not memory.
  Lives in tables like `concepts`/`memory_objects`/`toc_entries` and the
  misleadingly named `schemas/memory.py` and `src/backend/memory/`.
- **Student data** — raw private per-user records (attempts, mastery,
  chat). Separate subsystem.

If a task says "course memory," it means the child node above. The
`course_memories` table IS that node. `MemoryObject` is NOT memory — it is
a course-knowledge note. Do not write course-memory rows for any user
other than the course owner; the only write seam is
`course_memory.refresh_for_owner`.

## Engineering tradeoff

Code is cheap to write (LLMs generate it); rework and brittleness are expensive.
When a better engineering decision costs slightly more code, prefer the better
decision. Don't gold-plate — but don't pick a fragile shortcut just to save lines.
Prioritize correctness, clear seams, and future extensibility over brevity.

## Structure

```
configs/         # ingestion/retrieval/tutor/tiers/prompts/embeddings configs (versioned)
data/
  raw/           # original course files — GITIGNORED
  processed/     # extracted text, chunks — GITIGNORED
  eval/          # eval questions + held-out sets (committed)
src/
  backend/
    ingest/        # parse, locators, token-bounded chunks, embeddings, OCR
    retrieval/     # four-seam funnel + traces
    memory/        # concept/dependency store + table of contents
    student_model/ # attempts, mastery, error model (schema live; subsystem M3-4)
    tutor/         # source-grounded answers + cold probes
    evals/         # answer eval harness (retrieval evals live in retrieval/)
    api/           # FastAPI routers (auth, courses, sources, tutor, archives)
    common/
      schemas/       # Pydantic models, one module per storage layer
      config.py      # .env loading + settings
      db.py          # the single Postgres connection seam
      migrate.py     # versioned migration runner
      migrations/    # 00X_*.sql, append-only, applied in order
      queries/       # named SQL blocks loaded via common.queries.get
      provider.py    # the single model-call seam (generate + embed)
      prompt_registry.py  # prompt loading + untrusted-material fencing
      repos          # per-aggregate SQL callers (courses_repo, sources_repo, ...)
  frontend/        # SvelteKit + TS SPA; talks to backend only via its API
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
  `common/migrations/` — never edit an applied migration (currently 001–032).
- **Config:** tunable/versioned parameters in `configs/`, not hardcoded.
  Credentials in `.env` (gitignored), loaded via `common/config.py`. System
  prompts live in `configs/prompts.toml` (versioned) — never inline prompt
  text in code; uploaded course text must pass through
  `prompt_registry.grounded_prompt` so it is fenced as untrusted data.
- **Models:** every model call goes through `common/provider.py` —
  `generate` (hosted chat APIs, gated + billed) or `embed` (self-hosted,
  in-process). No SDK objects or keys outside that module.
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
.venv/Scripts/python -m pytest                        # tests (needs PYTEST_ALLOW_ANY_DB=1 + dev DB)
.venv/Scripts/python -m ruff check .                  # lint
.venv/Scripts/python -m mypy src                      # typecheck
.venv/Scripts/python -m src.backend.common.migrate    # apply DB migrations
```

All three checks must pass before declaring work done. `.env` must exist with
Postgres credentials for DB work (see `config.py` for expected keys).

Frontend (see `src/frontend/README.md` — separate npm codebase, run from
`src/frontend/`):

```
npm run check    # svelte-check typecheck/diagnostics (must pass)
npm run build    # static SPA into build/
npm run gen:api  # regenerate API types from the backend's OpenAPI schema
```

`src/frontend/src/lib/api/schema.d.ts` is generated from the backend — never
hand-edit it; re-run `npm run gen:api` after backend route/schema changes
(it needs a live backend on `localhost:8000`).

Eval harness (answer-side; `src/backend/evals/answer.py`, cases in
`data/eval/answer/cases.json`): run via tests or in code — cases have five
kinds (green_grounded / cold_probe / yellow_steer / red_refuse /
workspace_grounded), scorers are
mechanical, prompt version is stamped into every run log under `runs/`.

## Workflow expectations for agents

- Read `docs/project.md` and `docs/system.md` before making structural changes.
- Before writing code, look at existing patterns and reuse `src/backend/common/`.
- Verify changes run and, where possible, pass tests + lint + typecheck.
- Never commit unless explicitly requested.
