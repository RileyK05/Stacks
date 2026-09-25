# AGENTS.md

This file is the working contract for contributors and AI agents on this project.
It is deliberately kept short and enforced. If it conflicts with a task, the task
should be questioned, not the file ignored.

## Project

Stacks is an academic assistant that accumulates a source-grounded course memory and a student
error model, then recommends what to study next. **A local-first desktop tool**
(decision 012, `docs/plan-local-first.md`): one user per SQLite file on their
own machine, a bundled llama.cpp server running a small open model by default,
and optional cloud providers the user chooses. Encoders (embeddings, reranker)
run in-process on ONNX Runtime. See `docs/project.md` for the product plan,
`docs/system.md` for architecture (its hosted-era sections are superseded by
decision 012). Read them before making structural decisions.

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
4. **The user owns their data.** Everything lives in their local database and
   data folder. The default model runs on their machine; a cloud provider is
   used only if they choose one (with a one-time disclosure). No auto-solving
   graded work.
5. **ML earns its role.** Begin with retrieval, structure, and simple baselines.
   Add models/fine-tuning only for a documented, versioned baseline failure.
6. **Destruction leaves a distilled record.** A deleted course sits in the
   trash for 30 days; its course-memory keepsake survives the purge. Never
   silently destroy evidence.

## Memory vocabulary (read before touching anything named "memory")

Full definition: `docs/decisions/007_memory_model.md`. That file wins over
any other doc or code name. Summary:

- **User memory (root)** — per-user, lifelong, behavioral ("teach THIS
  person with visuals/analogies") + cross-course history. The ONLY layer
  that may change how the model behaves.
- **Course memory (child)** — per-course focus record ("what this student
  struggles with in THIS course"). One local user per database. Facts about
  understanding; never behavior instructions. Survives course deletion.
- **Course knowledge / TOC** — what the course SAYS (concepts, evidence)
  and the index for FINDING it. Shared per-course state. Not memory.
  Lives in tables like `concepts`/`memory_objects`/`toc_entries` and the
  misleadingly named `schemas/memory.py` and `src/backend/memory/`.
- **Student data** — raw private per-user records (attempts, mastery,
  chat). Separate subsystem.

If a task says "course memory," it means the child node above. The
`course_memories` table IS that node. `MemoryObject` is NOT memory — it is
a course-knowledge note. The only write seam is `course_memory.refresh`.

## Engineering tradeoff

Code is cheap to write (LLMs generate it); rework and brittleness are expensive.
When a better engineering decision costs slightly more code, prefer the better
decision. Don't gold-plate — but don't pick a fragile shortcut just to save lines.
Prioritize correctness, clear seams, and future extensibility over brevity.

## Structure

```
configs/         # ingestion/retrieval/prompts/models/runtime/lifecycle configs (versioned)
data/
  raw/           # original course files — GITIGNORED
  processed/     # extracted text, chunks — GITIGNORED
  eval/          # eval questions + held-out sets (committed)
src/
  backend/
    ingest/        # parse, locators, token-bounded chunks, embeddings, OCR
    retrieval/     # four-seam funnel + traces
    memory/        # concept/dependency store + table of contents
    artifacts/     # typed content, cited model edits, Office exports
    student_model/ # attempts, mastery, error model (schema live; subsystem M3-4)
    tutor/         # task framing, saved-chat context, grounded answers
    evals/         # answer eval harness (retrieval evals live in retrieval/)
    runtime/       # bundled llama.cpp server, model catalog, user GGUF models
    api/           # FastAPI routers including conversations and artifacts
    main.py        # ASGI app: the API mounted at /api (CORS for the Tauri webview)
    serve.py       # the backend process the desktop shell runs
    version.py     # app name + version (scripts/set_version.py)
    common/
      schemas/       # Pydantic models, one module per storage layer
      config.py      # .env loading + settings
      db.py          # the single SQLite connection seam
      migrate.py     # versioned migration runner
      migrations/    # 00X_*.sql, append-only, applied in order
      queries/       # named SQL blocks loaded via common.queries.get
      provider.py    # the single model-call seam (generate + embed + rerank)
      providers.py   # which endpoint serves which task class (user settings)
      model_profiles.py # per-model runtime and prompt limits
      archive_notebook.py # portable chat/artifact history + cited passages
      encoders.py    # ONNX Runtime embedder + cross-encoder (pinned, verified)
      prompt_registry.py  # prompt loading + untrusted-material fencing
      repos          # per-aggregate SQL callers (courses_repo, sources_repo, ...)
  frontend/        # SvelteKit + TS SPA; talks to backend only via its API
    src-tauri/     # Tauri v2 desktop shell (Rust): window, backend process
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
- **Database:** SQLite via raw SQL (no ORM), `:name` parameters. Queries live
  in `common/queries/*.sql`; schema changes are new numbered files in
  `common/migrations/` — never edit an applied migration (baseline: 001).
  Never hold a write transaction across a slow step (model call, parsing):
  SQLite has one writer.
- **Config:** tunable/versioned parameters in `configs/`, not hardcoded.
  API keys live in the OS keychain (`common/secrets.py`), never in files or
  the database; `.env` holds only optional development settings. System
  prompts live in `configs/prompts.toml` (versioned) — never inline prompt
  text in code; uploaded course text must pass through
  `prompt_registry.grounded_prompt` so it is fenced as untrusted data.
- **Models:** every model call goes through `common/provider.py` —
  `generate` (routed to the user's chosen endpoint, recorded in the usage
  ledger) or the in-process `embed_*` / `rerank_scores` seams. Every prompt
  or model change is measured with `scripts/eval_models.py`.
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
.venv/Scripts/python -m pytest                        # tests (fresh SQLite per test)
.venv/Scripts/python -m ruff check .                  # lint
.venv/Scripts/python -m mypy src                      # typecheck
.venv/Scripts/python -m uvicorn src.backend.main:app  # API only (browser dev, with npm run dev)
.venv/Scripts/python -m scripts.eval_models --help    # model bake-off / eval
.venv/Scripts/python -m scripts.build_desktop         # installer (src-tauri/target/release/bundle)
.venv/Scripts/python -m scripts.set_version X.Y.Z     # bump the version everywhere
```

All three checks must pass before declaring work done. Tests never start
llama-server, download models, or read other apps' model folders.

Frontend (see `src/frontend/README.md` — separate npm codebase, run from
`src/frontend/`):

```
npm run check    # svelte-check typecheck/diagnostics (must pass)
npm run desktop  # the desktop app in dev (tauri dev; starts the backend)
npm run build    # static SPA into build/
npm run gen:api  # regenerate API types from the backend's OpenAPI schema
```

`src/frontend/src/lib/api/schema.d.ts` is generated from the backend — never
hand-edit it; re-run `npm run gen:api` after backend route/schema changes
(from a live backend, or `python -m scripts.dump_openapi` +
`OPENAPI_FILE=...`).

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
