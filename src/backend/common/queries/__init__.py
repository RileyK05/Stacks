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
    blocks = {m.group(1): m.group(2).strip() for m in _BLOCK_RE.finditer(text)}
    if not blocks:
        return {"": text.strip()}
    return blocks


def get(file_name: str, block_name: str) -> str:
    """Return the SQL for a named block, or the whole file if no markers."""
    return load(file_name).get(block_name) or load(file_name).get("") or ""
