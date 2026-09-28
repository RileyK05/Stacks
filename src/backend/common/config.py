from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Where a development checkout keeps its database and uploads. A packaged
# desktop build sets APP_DATA_DIR to the per-user OS data directory
# instead.
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DATABASE_FILENAME = "course_assistant.db"
DEFAULT_OFFICE_PORT = 47831


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
    # The Office bridge is a second local trust boundary: the task-pane add-in
    # is a web page loaded by Microsoft Office, so it cannot hold the desktop
    # shell's per-launch token. When set, office requests carry this instead.
    # Empty by default: the pane is served same-origin by the add-in host.
    office_bridge_token: str = Field(default="")
    # The fixed local HTTPS port the Office add-in is served from. Fixed
    # because Office stores the add-in's absolute URLs in its manifest.
    office_port: int = Field(default=DEFAULT_OFFICE_PORT, ge=1024, le=65535)
    # Where `.course` exports are written (the user's Downloads folder).
    export_dir: str = Field(default="")


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
        office_bridge_token=os.getenv("APP_OFFICE_TOKEN", ""),
        office_port=int(os.getenv("APP_OFFICE_PORT", str(DEFAULT_OFFICE_PORT))),
        export_dir=os.getenv("APP_EXPORT_DIR", str(_downloads_dir())),
    )


def _downloads_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()
