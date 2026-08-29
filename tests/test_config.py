import pytest
from pydantic import ValidationError
from src.backend.common.config import DEVELOPMENT_JWT_SECRET, Settings
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
