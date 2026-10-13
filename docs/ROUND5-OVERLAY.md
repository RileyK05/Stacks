# Round-5 bug overlay (working map)

Maps every open item in `docs/RETEST-round5.md` and `docs/STATUS-round5.md` to the
code that owns it, the intended fix, and the status after the round-6 pass. This is
the working "overlay" for the retest; durable lessons move to `docs/notes.md`.

Legend: **fixed** = code changed + regression test; **partial** = improved but the
root cause needs a design-level change; **tricky** = attempted, not fully solvable
mechanically (recorded so it is not re-attempted blind).

| ID | Sev | Owner (file) | Status |
|---|---|---|---|
| R5-NEW-l | high | `common/prompt_registry.py` | fixed |
| R5-NEW-o | medium | `ingest/orchestrator.py` | fixed |
| R5-NEW-a | medium | `tutor/critique.py` | fixed |
| R5-NEW-b | medium | `student_model/grading.py` | tricky (partial: passive/"not … until"; synonyms need a model) |
| R5-NEW-c | medium | `tutor/compose.py` | fixed |
| R5-NEW-d | medium | `tutor/compose.py` | fixed |
| R5-NEW-k | medium | `tutor/materials.py` | fixed |
| R5-NEW-s | medium | `artifacts/exam_style.py`, `configs/generation.toml` | partial (own token budget + transient retry) |
| R5-NEW-e | low | `tutor/materials.py` | fixed |
| R5-NEW-f | low | `tutor/materials.py` | fixed |
| R5-NEW-g | low | `ingest/ocr_pages.py` | fixed |
| R5-NEW-h | low | `common/provider.py` | fixed |
| R5-NEW-i | low | `tutor/critique.py` | fixed |
| R5-NEW-j | low | `ingest/orchestrator.py` | fixed (page list already capped at 20) |
| R5-NEW-m | low | ingest segmentation | tricky (one table split across title/table/note chunks; ranking, not chunking, is the real loss) |
| R5-NEW-n | low | `tutor/critique.py` | fixed |
| R5-NEW-p | low | `retrieval/funnel.py` | tricky (ranking) |
| R5-NEW-q | low | `common/storage.py` | fixed |
| R5-NEW-r | low | `ingest/orchestrator.py` | fixed |
| R5-NEW-t | low | `tutor/materials.py` | fixed |
| R5-NEW-u | low | `tutor/materials.py` | fixed |
| STK-025/044 | – | `retrieval/funnel.py` | tricky (ranking, not attempted this pass) |
| STK-039 | – | `retrieval/funnel.py` | tricky (ranking, not attempted this pass) |
| C-4 | – | `tutor/work.py` | fixed (only `review` must cite) |

Regression coverage: `tests/test_round5_regressions.py` (R5-NEW-*), plus
`tests/test_companion_work.py` (C-4).
