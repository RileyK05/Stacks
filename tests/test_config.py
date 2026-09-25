from pathlib import Path

import pytest
from pydantic import ValidationError
from src.backend.common.config import get_settings
from src.backend.common.lifecycle_config import LifecyclePolicy, load_lifecycle_policy
from src.backend.common.providers import TaskClass, load_models_config, task_class
from src.backend.common.schemas.base import INGESTION_TASKS, KNOWN_GENERATION_TASKS
from src.backend.ingest.config import load_ingestion_config
from src.backend.ingest.pipeline import PIPELINE_STAGES


def test_app_data_dir_drives_database_and_storage_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_PATH")
    monkeypatch.delenv("STORAGE_ROOT")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "profile"))
    settings = get_settings()
    assert Path(settings.database_path) == tmp_path / "profile" / "course_assistant.db"
    assert Path(settings.storage_root) == tmp_path / "profile" / "raw"


def test_ingestion_config_matches_supported_pipeline() -> None:
    config = load_ingestion_config()
    assert config.max_attempts == 2
    assert tuple(stage.name for stage in config.stages) == PIPELINE_STAGES


def test_decompression_cap_covers_raw_upload_ceiling() -> None:
    """Stored files are our gzip of a body that already passed the upload
    ceiling, so legitimate expansion reaches at least that size. A smaller
    cap would make large uploads dead on arrival (upload passes, read
    raises)."""
    policy = load_lifecycle_policy()
    assert policy.max_decompressed_bytes >= policy.max_raw_upload_bytes


def test_lifecycle_policy_rejects_cap_below_upload_ceiling() -> None:
    fields = load_lifecycle_policy().model_dump()
    fields["max_decompressed_bytes"] = fields["max_raw_upload_bytes"] - 1
    with pytest.raises(ValidationError, match="max_decompressed_bytes"):
        LifecyclePolicy(**fields)


def test_lifecycle_config_requires_decompression_section(tmp_path: Path) -> None:
    from src.backend.common.lifecycle_config import DEFAULT_LIFECYCLE_PATH

    raw = DEFAULT_LIFECYCLE_PATH.read_text(encoding="utf-8")
    without_section = "\n".join(
        line
        for line in raw.splitlines()
        if not line.startswith("max_decompressed_bytes")
    ).replace("[decompression]\n", "")
    config_path = tmp_path / "lifecycle.toml"
    config_path.write_text(without_section, encoding="utf-8")
    with pytest.raises(KeyError):
        load_lifecycle_policy(config_path)


def test_every_task_has_a_task_class() -> None:
    for task in KNOWN_GENERATION_TASKS:
        expected = (
            TaskClass.BACKGROUND if task in INGESTION_TASKS else TaskClass.INTERACTIVE
        )
        assert task_class(task) == expected
    with pytest.raises(ValueError, match="unknown generation task"):
        task_class("not_a_task")


def test_models_config_has_a_keyless_local_preset() -> None:
    config = load_models_config()
    local = config.presets["local"]
    assert local.requires_key is False and local.disclosure is False
    assert local.base_url.startswith("http://127.0.0.1")
    # Every cloud preset is disclosed to the user before first use.
    for name, preset in config.presets.items():
        if name != "local":
            assert preset.disclosure is True
    assert config.generation.enable_thinking is False
