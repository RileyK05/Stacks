"""Print a version's CHANGELOG section, for the GitHub release notes.

python -m scripts.release_notes 0.3.0 > release-notes.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def release_notes(version: str, changelog: str) -> str:
    match = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        changelog,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else "See CHANGELOG.md."


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m scripts.release_notes X.Y.Z")
    print(release_notes(args[0], CHANGELOG.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
