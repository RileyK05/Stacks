from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, model_validator
from src.backend.common.config import PROJECT_ROOT
from src.backend.common.schemas.base import KNOWN_GENERATION_TASKS

# Prompts that are not generation tasks of their own: the per-kind
# workspace prompts share the `artifact_generation` task for routing and
# usage, but each has its own text (tutor/compose.py).
WORKSPACE_PROMPTS = frozenset(
    f"workspace_{kind}" for kind in ("quiz", "document", "sheet", "slides", "code")
)
KNOWN_PROMPTS = KNOWN_GENERATION_TASKS | WORKSPACE_PROMPTS | {"tutor_steer"}

DEFAULT_PROMPTS_PATH = PROJECT_ROOT / "configs" / "prompts.toml"

# Input marking (the prompt-injection go-live gate): uploaded course text
# is untrusted. It is fenced between these markers and every prompt using
# it states that the fenced block is data, never instructions. A fence is
# not a security boundary on its own — no text convention is — but it is
# the documented, inspectable mitigation: the model is told exactly where
# untrusted content starts and ends, and reviewers can see the same.
UNTRUSTED_BEGIN = "<<<UNTRUSTED_COURSE_MATERIAL begin>>>"
UNTRUSTED_END = "<<<UNTRUSTED_COURSE_MATERIAL end>>>"


def fence_untrusted(text: str) -> str:
    """Wrap untrusted uploaded text in the data fence.

    Any occurrence of the fence markers in the content itself is
    neutralized first: otherwise an upload could embed the end marker and
    close the fence early, making the text after it read as instructions.
    Neutralizing (not escaping) keeps the visible content honest — the
    reader/model still sees the words, just not as a marker. This is a
    documented mitigation, not a proof: fenced data can still try to
    persuade, which is why the prompts also say the block is data.
    """
    safe = text.replace(UNTRUSTED_BEGIN, "[fence marker]").replace(
        UNTRUSTED_END, "[fence marker]"
    )
    return f"{UNTRUSTED_BEGIN}\n{safe}\n{UNTRUSTED_END}"


def strip_fence_echo(text: str) -> str:
    """Remove fenced material a model echoed into its answer — whole
    begin…end blocks, then any stray marker line. It is prompt plumbing,
    never content (Phase 0 bake-off: a 2B model appended the entire fenced
    question and material after its answer)."""
    begin, end = re.escape(UNTRUSTED_BEGIN), re.escape(UNTRUSTED_END)
    text = re.sub(rf"{begin}.*?{end}", "", text, flags=re.DOTALL)
    lines = [
        line
        for line in text.splitlines()
        if UNTRUSTED_BEGIN not in line and UNTRUSTED_END not in line
    ]
    return "\n".join(lines).strip()


def grounded_prompt(instruction: str, material: str) -> str:
    """Assemble a task prompt: trusted instruction first, then the course
    material fenced as data. Every prompt that embeds uploaded text goes
    through here so input marking is structural, not a per-call habit."""
    return f"{instruction}\n\n{fence_untrusted(material)}"


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
        missing = KNOWN_PROMPTS.difference(self.prompts)
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
    if task not in KNOWN_PROMPTS:
        raise ValueError(f"unknown prompt: {task}")
    policy = load_prompt_policy(path)
    text = policy.prompts.get(task)
    if text is None:
        raise KeyError(f"no prompt configured for task: {task}")
    return text.strip()