import pytest
from pydantic import ValidationError
from src.backend.common.config import DEVELOPMENT_JWT_SECRET, Settings
from src.backend.common.lifecycle_config import load_lifecycle_policy
from src.backend.common.tiers import load_tier_policies
from src.backend.ingest.config import load_ingestion_config
from src.backend.ingest.pipeline import PIPELINE_STAGES


def test_production_rejects_development_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="production JWT_SECRET"):
        Settings(app_env="production", jwt_secret=DEVELOPMENT_JWT_SECRET)


def test_production_accepts_long_unique_jwt_secret() -> None:
    settings = Settings(app_env="production", jwt_secret="x" * 32)
    assert settings.app_env == "production"


def test_ingestion_config_matches_supported_pipeline() -> None:
    config = load_ingestion_config()
    assert config.max_attempts == 2
    assert tuple(stage.name for stage in config.stages) == PIPELINE_STAGES


def test_decompression_cap_covers_raw_upload_ceilings() -> None:
    """The decompression ceiling must be >= every tier's raw upload ceiling:
    stored files are our gzip of a body that already passed the upload
    ceiling, so legitimate expansion reaches at least that size. A smaller
    cap makes large paid uploads dead on arrival (quota passes, read
    raises)."""
    policy = load_lifecycle_policy()
    ceilings = [
        tier_policy.max_raw_upload_bytes
        for tier_policy in load_tier_policies().tiers.values()
    ]
    assert policy.max_decompressed_bytes >= max(ceilings)


def test_lifecycle_config_requires_decompression_section(tmp_path) -> None:
    from src.backend.common.lifecycle_config import (
        DEFAULT_LIFECYCLE_PATH,
        load_lifecycle_policy,
    )

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
