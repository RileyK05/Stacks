from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEVELOPMENT_JWT_SECRET = "development-only-secret-change-before-production"


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
    pg_host: str = Field(default="localhost")
    pg_port: int = Field(default=5432)
    pg_database: str = Field(default="course_assistant")
    pg_user: str = Field(default="postgres")
    pg_password: str = Field(default="")
    storage_root: str = Field(default=str(PROJECT_ROOT / "data" / "raw"))
    jwt_secret: str = Field(default=DEVELOPMENT_JWT_SECRET)
    jwt_expire_minutes: int = Field(default=60 * 24 * 7, gt=0, le=60 * 24 * 30)
    jwt_issuer: str = Field(default="course-assistant")
    jwt_audience: str = Field(default="course-assistant-api")

    @model_validator(mode="after")
    def _secure_production_secret(self) -> Settings:
        if self.app_env == "production" and (
            self.jwt_secret == DEVELOPMENT_JWT_SECRET
            or len(self.jwt_secret.encode()) < 32
        ):
            raise ValueError("production JWT_SECRET must be a unique 32+ byte value")
        return self

    @property
    def dsn(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} "
            f"dbname={self.pg_database} user={self.pg_user} "
            f"password={self.pg_password}"
        )


def get_settings() -> Settings:
    _load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        app_env=cast(
            Literal["development", "test", "production"],
            os.getenv("APP_ENV", "development"),
        ),
        pg_host=os.getenv("PGHOST", "localhost"),
        pg_port=int(os.getenv("PGPORT", "5432")),
        pg_database=os.getenv("PGDATABASE", "course_assistant"),
        pg_user=os.getenv("PGUSER", "postgres"),
        pg_password=os.getenv("PGPASSWORD", ""),
        storage_root=os.getenv("STORAGE_ROOT", str(PROJECT_ROOT / "data" / "raw")),
        jwt_secret=os.getenv("JWT_SECRET", DEVELOPMENT_JWT_SECRET),
        jwt_expire_minutes=int(os.getenv("JWT_EXPIRE_MINUTES", "10080")),
        jwt_issuer=os.getenv("JWT_ISSUER", "course-assistant"),
        jwt_audience=os.getenv("JWT_AUDIENCE", "course-assistant-api"),
    )
