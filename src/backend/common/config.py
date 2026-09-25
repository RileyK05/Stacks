from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Where a development checkout keeps its database and uploads. A packaged
# desktop build sets APP_DATA_DIR to the per-user OS data directory
# instead (docs/plan-local-first.md §11).
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DATABASE_FILENAME = "course_assistant.db"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader. Sets only keys not already present in the env."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class Settings(BaseModel):
    app_env: Literal["development", "test", "production"] = Field(
        default="development"
    )
    data_dir: str = Field(default=str(DEFAULT_DATA_DIR))
    database_path: str = Field(default=str(DEFAULT_DATA_DIR / DATABASE_FILENAME))
    storage_root: str = Field(default=str(DEFAULT_DATA_DIR / "raw"))
    # Development fallback for the generation provider. The desktop app
    # configures providers through app_settings + the OS keyring; these
    # env values only apply when no provider has been configured there.
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="")
    llm_model: str = Field(default="")
    # Per-launch secret the desktop shell passes to the backend; when set,
    # every API request must carry it (plan §4). Empty in development.
    api_token: str = Field(default="")


def get_settings() -> Settings:
    _load_dotenv(PROJECT_ROOT / ".env")
    data_dir = Path(os.getenv("APP_DATA_DIR", str(DEFAULT_DATA_DIR)))
    return Settings(
        app_env=cast(
            Literal["development", "test", "production"],
            os.getenv("APP_ENV", "development"),
        ),
        data_dir=str(data_dir),
        database_path=os.getenv(
            "DATABASE_PATH", str(data_dir / DATABASE_FILENAME)
        ),
        storage_root=os.getenv("STORAGE_ROOT", str(data_dir / "raw")),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", ""),
        llm_model=os.getenv("LLM_MODEL", ""),
        api_token=os.getenv("APP_API_TOKEN", ""),
    )
