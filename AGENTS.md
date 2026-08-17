# AGENTS.md

This file is the working contract for contributors and AI agents on this project.
It is deliberately kept short and enforced. If it conflicts with a task, the task
should be questioned, not the file ignored.

## Project

Local-first academic assistant that accumulates a source-grounded course memory
and a student error model, then recommends what to study next. See `project.md`
for the full plan. Read it before making structural decisions.

## Golden rules

1. **Source grounding is sacred.** Every substantive answer, claim, or memory
   object must retain evidence links (source ID, page/slide, section). Never
   answer an uploaded-material question without showing sources.
2. **Inspectable over impressive.** Show what was retrieved, what was inferred,
   and why a concept is flagged weak. No opaque black-box scores.
3. **Evaluation is the center, not an afterthought.** No feature ships without a
   way to measure whether it regressed. Prefer boring, verifiable baselines over
   clever-but-unverifiable ones.
4. **Local-first by default.** Course data and study history live in local/owned
   storage (Postgres). Inference uses a hosted model API that does not retain
   data. No auto-solving graded work.
5. **ML earns its role.** Begin with retrieval, structure, and simple baselines.
   Add fine-tuning only for a documented, versioned baseline failure.

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
    ingest/        # parse, chunk, provenance
    retrieval/     # vector index + metadata filters
    memory/        # concept/formula/dependency schemas + store
    student_model/ # attempts, mastery, error model
    tutor/         # source-grounded answers + cold probes
    evals/         # retrieval/answer/probe/student-model evaluation
    common/        # shared schema/validation, logging, config loading
  frontend/        # web UI; talks to backend via API
tests/           # pytest; mirrors src/ backend layout
runs/            # experiment + eval logs — GITIGNORED
docs/            # design notes, decisions, runbooks
```

The six subsystems map 1:1 to `src/backend/<package>`. Put cross-cutting code
(Pydantic schemas, logging, config) in `src/backend/common/` to avoid circular
imports. Keep packages cohesive and imports acyclic. Backend and frontend are
separate codebases under `src/`; frontend talks to backend only via its API.

## Conventions

- **Code style:** no comments unless they explain a non-obvious decision. Prefer
  self-documenting names. Follow existing patterns; match surrounding code.
- **Language:** Python. Use Pydantic for validated schema objects, especially
  anything persisted or crossing a boundary.
- **Config:** put tunable/versioned parameters in `configs/`, not hardcoded.
- **No secrets:** never log or commit keys, tokens, or course materials with
  classmates' work.
- **Commits:** concise messages matching repo style; only commit when asked.
- **Lint/typecheck:** run the project's lint and typecheck commands before
  declaring work done.

## Workflow expectations for agents

- Read `project.md` before making structural changes.
- Before writing code, look at existing patterns and reuse `src/common/`.
- Verify changes run and, where possible, pass tests. Ask for the exact lint/test
  command if it is not discoverable.
- Never commit unless explicitly requested.
