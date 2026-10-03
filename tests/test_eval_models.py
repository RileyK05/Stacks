import pytest
from scripts import eval_models


@pytest.mark.parametrize(
    "report, expected",
    [
        (eval_models.ModelReport(model="test", passed=1), 0),
        (eval_models.ModelReport(model="test", passed=1, failed=1), 1),
        (eval_models.ModelReport(model="test", unresolved=1), 1),
        (eval_models.ModelReport(model="test"), 1),
        (eval_models.ModelReport(model="test", passed=1, errors=["timeout"]), 1),
    ],
)
def test_bakeoff_exit_status_reflects_quality_failures(
    monkeypatch, tmp_path, report, expected
) -> None:
    from src.backend.common import migrate

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(migrate, "migrate", lambda: None)
    monkeypatch.setattr(eval_models, "_seed_harness_course", lambda: None)
    monkeypatch.setattr(eval_models, "_run_model", lambda *args: report)
    assert (
        eval_models.main(["--base-url", "http://localhost:8081/v1", "--model", "test"])
        == expected
    )
