"""Production eval seeding (T-15) and Windows-safe report paths (T-14)."""

from __future__ import annotations

from scripts import eval_models
from src.backend.common.db import connection
from src.backend.evals import seed
from src.backend.evals.answer import load_answer_cases


def test_harness_course_resolves_every_committed_answer_case() -> None:
    """The seeded harness course satisfies the committed cases file, and
    seeding comes from production code, not tests (T-15)."""
    course = seed.seed_harness_course()
    cases = load_answer_cases()
    assert cases, "the committed cases file must not be empty"
    with connection() as conn:
        labels = {
            row["label"]
            for row in conn.execute(
                "SELECT locator.label FROM chunks AS chunk"
                " JOIN locators AS locator ON locator.locator_id ="
                " chunk.locator_id JOIN sources AS source ON source.source_id ="
                " chunk.source_id WHERE source.course_id = ?",
                (course.course_id,),
            ).fetchall()
        }
    required = {label for case in cases for label in case.seed_chunk_labels}
    assert required <= labels, f"missing seed labels: {required - labels}"


def test_model_report_directory_is_windows_safe() -> None:
    """A documented cloud model id contains `/` and `:`; the report
    directory must be creatable on Windows too (T-14)."""
    unsafe = "inclusionai/ling-3.0-tiny:free"
    safe = eval_models._model_dir_name(unsafe)
    assert safe and not (set(safe) & set('/\\:*?"<>|'))
    assert eval_models._model_dir_name(safe) == safe


def test_model_report_directory_never_empty_or_overlong() -> None:
    assert eval_models._model_dir_name("") == "model"
    assert eval_models._model_dir_name("///") == "model"
    assert len(eval_models._model_dir_name("x" * 500)) <= 120
