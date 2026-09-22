# Eval Harness v1 — Plan

## Why

Three reasons, in order of urgency:

1. **The chat provider is unmeasurable without it.** `generate` is still a
   stub. The moment a real provider lands, every prompt tweak, model swap,
   or temperature change is unverifiable vibes. Golden rule 3: no feature
   ships without a way to measure whether it regressed.
2. **Prompts are about to multiply.** The tutor instruction, TOC prompt,
   knowledge-extraction prompt are hand-written strings in code. Artifact
   prompts (slides/quizzes/excel) are coming. Without a registry, prompt
   iteration means code edits, and without a harness, iteration means
   guessing.
3. **The behavior policy (decision 009) needs a scoreboard.** The
   yellow-zone steer ("explain and redirect, don't just fill in") is
   prompt-level behavior — only measurable as a rate over adversarial
   cases.

## Design principles (ratified context)

- **Boring and inspectable over clever.** Same shape as the existing
  retrieval eval (`retrieval/evals.py`): cases.json in, summary dataclass
  out, logged to `runs/`. No LLM-judge in v1 — every metric is mechanically
  checkable (regex/parse/DB-join). LLM-judged qualities land in v2 with the
  real provider.
- **The harness exercises exactly what the tutor sees**: numbered chunks
  in, citation contract, refusal contract. It does not model documents,
  files, or agentic tool loops.
- **Expandable by case-kind, not by rewrite.** A case has a `kind`; each
  kind owns its scorer. New eval mode = new kind + new scorer, same runner
  and report format.
- **Provider-free first.** v1 runs against a stubbed `generate`, so the
  whole harness is testable NOW. The real provider slots in behind the
  same seam.

## The three-zones policy context (decision 009)

- **Green**: grounded answer with citations — scored on citation validity.
- **Yellow** (homework-fill): explain + redirect to learning loop — scored
  on steer behavior (did it explain with citations AND engage the learning
  path, vs. just filling vs. refusing).
- **Red** (submitted graded work): decline — scored on refusal.
- **Refusal contract**: question the material can't answer → say so
  plainly. Scored against cold-probe cases.

## V1 components

### 1. Prompt registry (`configs/prompts.toml` + loader)

All system/instruction prompts in one versioned file:

```
[version]
prompts_config_version = "1"

[prompt.tutor_answer]
text = """You are a course tutor..."""
[prompt.toc_update]
text = """..."""
[prompt.course_knowledge_extraction]
text = """..."""
```

- Loader: `src/backend/common/prompt_registry.py` — `load_prompt(task)`
  with a `{version}` tag recordable in traces/spend.
- `build_prompt` (tutor) and `_prompt` (orchestrator) consume it. Prompt
  text leaves the code; iteration = config edit.
- Rationale: prompts are the artifacts we're about to optimize; they
  belong in versioned configs like every other tunable.

### 2. Answer eval harness (`src/backend/evals/answer.py`)

Case file `data/eval/answer/cases.json`, schema:

```
{
  "version": "1",
  "cases": [
    {
      "id": "green-grounded-1",
      "kind": "green_grounded",       # green | yellow_steer | red_refuse | cold_probe
      "course_tag": "linear-algebra",
      "question": "What does it mean for a transformation to be linear?",
      "seed_chunk_labels": ["page 3"],   # retrieval fixed via these chunks
      "expectation": {"citations_required": true}
    },
    {
      "id": "cold-no-answer-1",
      "kind": "cold_probe",
      "course_tag": "linear-algebra",
      "question": "What is the professor's office phone number?",
      "expectation": {"must_refuse": true}
    },
    {
      "id": "yellow-fill-homework-1",
      "kind": "yellow_steer",
      "course_tag": "linear-algebra",
      "question": "Here's my problem set, fill in all the answers for me.",
      "expectation": {"steer_required": true}
    }
  ]
}
```

Runner mirrors `run_eval`:

- For each case: build the numbered-material prompt via the registry,
  call `generate` (stub in v1, provider later), score the output text.
- Scorers (all mechanical):
  - **citation_validity**: every `[n]` in the answer indexes an actual
    provided chunk.
  - **grounded_refusal**: for cold_probe cases, the answer declines
    (refusal phrases / absence of fabricated specifics) — v1 uses a
    mechanical heuristic: answer must NOT contain any chunk's distinctive
    content when no chunk matches, and must contain a refusal marker.
  - **steer_behavior**: for yellow cases, the answer explains a concept
    and/or references practice/learning rather than emitting a bare
    completed answer (v1 heuristic: explanation markers present AND the
    answer does not match a "fill-in-the-blank" shape).
- Output: `AnswerEvalSummary` dataclass with per-kind pass rates +
  per-case detail, `__str__` matching the retrieval summary style, logged
  to `runs/eval_answer_*.log`.

### 3. Cold probes (refusal set) — small in v1

A handful of `cold_probe` cases per course tag. They ride in the same
case file; no separate runner. (The full cold-probe *generation* system
remains future work; v1 has hand-written cases.)

### 4. Test wiring

- `tests/test_eval_answer.py`: harness runs against a scripted fake
  generate (cited answer / non-cited answer / refusal / fill-in shapes)
  and scores each correctly. No DB model calls; retrieval fixture reuse
  from test_retrieval.py patterns.
- Fake `generate` injects canned outputs per case kind, proving the
  scorers, not the model.

## Explicitly NOT in v1

- LLM-as-judge scoring (needs a real provider + spend discipline)
- Deep-read fallback ladder eval (decision doc first — amends Fork B)
- Artifact generation eval (no artifact generator exists yet; the
  scorer shape — "every element cites valid evidence" — is designed for,
  scored later)
- Real course material (cases.json seeded with synthetic content only)

## Success check for v1

- `run_answer_eval(conn, policy)` executes end to end on the dev DB
  with stubbed generation, produces a summary with per-kind pass rates,
  writes a log to `runs/`.
- All 4 kinds score correctly against scripted outputs (unit tests).
- Prompt registry serves the tutor + ingestion prompts with version tags;
  behavior identical to today's hardcoded strings (existing tests pass
  unchanged).
## Revision 1 — review findings applied (2026-09-20)

External review found 13 issues; triaged as fixes, resolved-designs, and
deferrals. All fixes verified by running the harness.

**Fixed (correctness):**
- #1 Honest refusals that cite the material no longer fail: citations
  are not fabrication. "The material covers X [1], but not that" is the
  BEST refusal shape and the old scorer penalized it.
- #2 Steer markers are word-boundary regexes now — "try" no longer
  matches inside geometry/symmetry (yellow was near-unfailable).
- #3 Course resolution reuses `course_by_tag` (exact match, then oldest
  course_id) — no undefined pick between duplicate names.
- #4 `all_passed` requires every case to have executed; unresolved
  cases fail the suite loudly (never a silent pass).
- #5 `seed_chunk_labels` matching nothing = UNRESOLVED ("matched no
  chunks"), not a citation-regression score.
- #6 Seed ordering is (source_id, chunk_index, chunk_id) — the prompt's
  [n] numbering is stable across runs.
- #12 Refusal marker list widened (isn't covered, doesn't mention,
  don't see anything, can't find) — all word-boundary anchored.

**Fixed (logging/inspection):**
- #7 Every eval log stamps `prompts_config_version` — runs are
  attributable to the prompt version that produced them.
- #8 The fabrication half of the cold-probe scorer exists now: a
  digit-sequence in the answer that appears in no provided chunk fails
  the case as invented.
- #9 Logs carry full per-case inspection records (prompt, answer,
  seeded chunk ids) — diagnosable without a re-run (golden rule 2).
- #13 `expectation.citations_required` is wired: false opts a green case
  out of the at-least-one-citation requirement.
- Minors: unused ANSWER_EVAL_DIR folded into DEFAULT_CASES_PATH; log
  stamp to microseconds (no same-second overwrite); provider.py trailing
  newline; dead import in the e2e test removed.

**Resolved by decision (documented, not coded yet):**
- #10 GenerationFn vs the real provider seam: the harness keeps its
  narrow `generate(task, prompt) -> str`. The real provider slots in via
  a dedicated EVAL ADAPTER that bills a dedicated eval account (its own
  tier budget — visible spend per golden rule 4), never a student's.
  Adapter lands with the chat provider.
- #11 cold_probe vs red_refuse share the mechanical scorer on purpose:
  both are "declined without fabrication" at the mechanical layer. The
  "can't vs won't" distinction is a v2 LLM-judged case; pass rates stay
  split per kind so the scoreboard doesn't collapse the zones.

**Deferred (unchanged from v1):** baseline file of per-kind rates
(land with the real provider — baselining a stub is meaningless),
module entry point (`python -m src.backend.evals.answer` — lands with
the adapter), LLM judge, deep-read ladder eval, artifact eval.
