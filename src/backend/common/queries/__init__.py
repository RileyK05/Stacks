import re
from functools import cache
from pathlib import Path

QUERIES_DIR = Path(__file__).resolve().parent

_BLOCK_RE = re.compile(r"--\s*name:\s*(\w+)\s*\n(.*?)(?=\n--\s*name:|\Z)", re.DOTALL)


@cache
def load(file_name: str) -> dict[str, str]:
    """Load and cache named SQL blocks from `queries/<file_name>.sql`.

    Files use `-- name: block` markers to delimit multiple named queries. A file
    with no markers returns one block keyed "" (the whole file, stripped).
    """
    text = (QUERIES_DIR / f"{file_name}.sql").read_text(encoding="utf-8")
    blocks: dict[str, str] = {}
    for match in _BLOCK_RE.finditer(text):
        name = match.group(1)
        if name in blocks:
            raise ValueError(f"duplicate query block '{name}' in {file_name}.sql")
        blocks[name] = match.group(2).strip()
    if not blocks:
        return {"": text.strip()}
    return blocks


def get(file_name: str, block_name: str) -> str:
    """Return the SQL for a named block. Raises if the block is missing."""
    blocks = load(file_name)
    if block_name in blocks:
        return blocks[block_name]
    available = ", ".join(sorted(name for name in blocks if name))
    hint = available or "(no named blocks)"
    raise KeyError(
        f"query block '{block_name}' not found in {file_name}.sql (has: {hint})"
    )
