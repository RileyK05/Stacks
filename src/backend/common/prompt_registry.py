from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, model_validator
from src.backend.common.config import PROJECT_ROOT
from src.backend.common.schemas.base import KNOWN_GENERATION_TASKS

DEFAULT_PROMPTS_PATH = PROJECT_ROOT / "configs" / "prompts.toml"


class PromptPolicy(BaseModel):
    """Every system/instruction prompt, versioned in configs/prompts.toml.
    Prompt text leaves the code: iterating on a prompt is a config edit +
    an eval-harness run, not a code change. `prompts_config_version` is
    recorded wherever the prompt influences output (traces, eval logs) so
    regressions are attributable to a prompt version."""

    prompts_config_version: str
    prompts: dict[str, str]

    @model_validator(mode="after")
    def _complete_known_tasks(self) -> PromptPolicy:
        missing = KNOWN_GENERATION_TASKS.difference(self.prompts)
        if missing:
            raise ValueError(
                f"prompts.toml must cover the known generation tasks "
                f"(missing: {sorted(missing)})"
            )
        return self


def load_prompt_policy(
    path: Path = DEFAULT_PROMPTS_PATH,
) -> PromptPolicy:
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    prompts = {
        name: section["text"] for name, section in raw["prompt"].items()
    }
    return PromptPolicy(
        prompts_config_version=raw["version"]["prompts_config_version"],
        prompts=prompts,
    )


def load_prompt(task: str, path: Path = DEFAULT_PROMPTS_PATH) -> str:
    if task not in KNOWN_GENERATION_TASKS:
        raise ValueError(f"unknown generation task: {task}")
    policy = load_prompt_policy(path)
    text = policy.prompts.get(task)
    if text is None:
        raise KeyError(f"no prompt configured for task: {task}")
    return text.strip()