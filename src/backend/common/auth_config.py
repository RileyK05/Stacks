from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from src.backend.common.config import PROJECT_ROOT

DEFAULT_AUTH_PATH = PROJECT_ROOT / "configs" / "auth.toml"


class LoginThrottlePolicy(BaseModel):
    """Failed-login throttle. Versioned in configs/auth.toml; keys and
    thresholds are never hardcoded in the API."""

    auth_config_version: str
    max_failures: int = Field(ge=1)
    window_seconds: int = Field(ge=1)
    lockout_seconds: int = Field(ge=1)
    trust_forwarded_for: bool = False

    @model_validator(mode="after")
    def _lockout_covers_window(self) -> LoginThrottlePolicy:
        if self.lockout_seconds < self.window_seconds:
            raise ValueError(
                "lockout_seconds must be >= window_seconds so a lock never "
                "expires while the failures that caused it are still counted"
            )
        return self


def load_login_throttle_policy(
    path: Path = DEFAULT_AUTH_PATH,
) -> LoginThrottlePolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return LoginThrottlePolicy.model_validate(
        {
            "auth_config_version": raw["version"]["auth_config_version"],
            **raw["login_throttle"],
        }
    )
