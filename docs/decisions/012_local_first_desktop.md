# 012 — Local-first desktop tool, small local models, SQLite

Date: 2026-09-25
Status: Ratified (owner direction; details in `docs/plan-local-first.md`)
Supersedes: 002 (auth boundary), 003 (public enrollment), 004 (tiers and
spend control), 005 (sharing, archives, support codes), 006 (three course
shapes) — wherever they describe accounts, tiers, sharing or enrollment.
Amends: 007 (memory: one user per database), 008 (retrieval: FTS5 + numpy
seams), 010 (eval: runs the live compose path, endpoint-configurable).
Related: 009 (the three-zone policy now also shapes task framing)

## Context

The hosted, multi-user design needed airbags for other people's data and
the operator's money: accounts, tiers, spend pools, a no-retention vendor
rule, sharing and enrollment. The owner decided to ship a downloadable
tool instead — no server, no hosting bill, the user's data on the user's
machine. The one thing lost is compute: the default model must run on an
ordinary laptop.

## Decision

1. **One user, one database file.** SQLite (WAL, FKs on, FTS5) in the
   per-user app-data directory. No accounts; a per-launch token between the
   desktop shell and the backend is the only auth. Every FK cascades, so a
   purge is one DELETE. Deleted courses go to a 30-day trash; the course-
   memory keepsake survives purge.
2. **No provider restrictions.** The user picks a model per task class
   (answers / background): the bundled local model, OpenRouter, OpenAI, or
   any OpenAI-compatible endpoint. Cloud choices show a one-time disclosure
   and nothing more; keys live in the OS keychain. An optional monthly cloud
   token budget replaces tiers.
3. **A bundled, supervised llama.cpp server** (pinned build b11177) serves
   local models, with reasoning disabled server-side (`--reasoning-budget
   0`), Vulkan first and CPU fallback, checksummed downloads, and reuse of
   verified GGUFs the user already has (LM Studio, HF cache).
4. **Default model: MiniCPM5-2B** (Apache-2.0, 1.56 GB Q4_K_M). Catalog:
   Qwen3.5-2B (starter), Granite 4.1 3B, Qwen3.5-4B, Ling 3.0 Tiny,
   Gemma 4 E2B (standard). K2 Horizon is **not** bundled: its architecture
   is unsupported by upstream llama.cpp at the pinned build; it remains
   reachable through the "custom" preset (e.g. LM Studio).
5. **The harness frames the task before generation** (`tutor/compose.py`):
   plain questions get a lean prompt; graded-work requests get a steer
   prompt; quiz / notes / table / slides / code requests get a narrow
   prompt plus a JSON schema whose citation numbers are bounded to the
   material provided. The citation gate (009/011) still has the last word.

## Evidence (Phase 0 bake-off, 2026-09-25)

Owner's laptop: Intel Core Ultra 7 258V, 32 GB, Arc iGPU (Vulkan).

| Finding | Consequence |
|---|---|
| Through LM Studio, MiniCPM5-2B ignored `enable_thinking: false`; on a quiz prompt it spent its whole 2048-token budget thinking and answered nothing (61 s) | Reasoning is disabled server-side in the bundled runtime; local requests also send `reasoning_effort: "none"` |
| Bundled runtime vs LM Studio, same model and cases: 2.1 s vs 24.3 s per case, 749 vs 8158 output tokens | The bundled runtime is the product path, not an optimisation |
| With the old prompt, MiniCPM talked about the workspace instructions instead of following them (3/4 workspace cases failed) | Task framing + schema: 4/4, across all three models tested |
| Built-in cases, final harness: MiniCPM5-2B 10/10 (2.3 s), Qwen3.5-2B 10/10 (4.2 s), Granite 4.1 3B 9/10 (6.0 s) | MiniCPM5-2B is the default |
| Real material (owner's syllabus + reading, 13 cases): MiniCPM5-2B 10–13/13 across runs (5–6 s), Qwen3.5-2B 11/13, Granite 11/13 | Dominant remaining failure is **over-refusal** (answer present, model says it isn't) |
| Cross-encoder reranker (ms-marco-MiniLM-L6, CPU) before generation, keeping 6 of 10 chunks: live answers 9.9 → 8.3 s on average, and "what percentage for an A-?" went from a false "not in the material" to the correct scale | Reranker on by default (`configs/retrieval.toml [rerank]`); real-material eval 13/13 and 12/13 |
| Reading answers found scorer false negatives (inflections, "not provided") and false positives (refusal markers inside copied syllabus text) | Scorer fixed and regression-tested; answers are read, not just counted |

The plan's pass bar (≥ 90% on the eval set with thinking off, < 30 s per
answer on the floor machine) is met on the built-in set and on most real-
material runs; the 8 GB floor machine is not yet measured.

## Consequences

- Next levers: quote-first answers (§6.2) against the remaining
  over-refusal; per-model top-k profiles; a larger real-material eval set.
- Every prompt or model change is re-measured with
  `scripts/eval_models.py` (bundled runtime, optional real-material course).
