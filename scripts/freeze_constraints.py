"""Regenerate constraints.txt from pyproject.toml + the installed venv.

The direct dependencies in pyproject.toml (base and every optional extra)
are resolved against the environment's installed distributions, then
written as exact `==` pins. Only direct dependencies are pinned; their
transitive dependencies stay free to resolve, which keeps the file
cross-platform (no environment markers) and small enough to review.

    .venv/Scripts/python -m scripts.freeze_constraints
    .venv/Scripts/python -m scripts.freeze_constraints --check  # CI drift gate

`--check` exits non-zero if constraints.txt is out of date, so CI can fail
when a dependency is bumped without re-freezing.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CONSTRAINTS = ROOT / "constraints.txt"

_HEADER = """\
# Pinned, cross-platform Python dependency set (T-03).
#
# pyproject.toml keeps the intentional lower bounds and platform markers;
# this file freezes the exact versions CI and development install from so
# a release cannot drift silently. It intentionally contains only
# platform-independent pins (no environment markers), because CI installs
# the same file on Windows, macOS, and Linux.
#
# Regenerate with:
#   .venv/Scripts/python -m scripts.freeze_constraints
# then run the test/lint/type gates before committing.
#
# Install (CI and local):
#   python -m pip install -e ".[dev]" -c constraints.txt
"""


def _requirement_names() -> list[str]:
    """Every direct dependency name, base first then each extra."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    groups: list[list[str]] = [list(project.get("dependencies", []))]
    groups.extend(project.get("optional-dependencies", {}).values())

    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            name = raw.split(";", 1)[0].split("[", 1)[0]
            name = name.split(">=", 1)[0].split("==", 1)[0].split("<", 1)[0]
            name = name.split("~=", 1)[0].split(">", 1)[0].strip()
            key = name.lower()
            if key and key not in seen:
                seen.add(key)
                names.append(name)
    return names


def _pins() -> list[str]:
    pins: list[str] = []
    missing: list[str] = []
    for name in _requirement_names():
        try:
            pins.append(f"{name}=={version(name)}")
        except PackageNotFoundError:
            missing.append(name)
    if missing:
        raise SystemExit("not installed, cannot freeze: " + ", ".join(sorted(missing)))
    return sorted(pins, key=str.lower)


def render() -> str:
    pins = _pins()
    base = [p for p in pins if p.split("==", 1)[0].lower() not in _EXTRA_NAMES]
    extras = [p for p in pins if p.split("==", 1)[0].lower() in _EXTRA_NAMES]
    body = "\n".join(base)
    if extras:
        body += (
            "\n\n# Optional extras, pinned too so `.[dev]`, `.[desktop]`,"
            " `.[parity]`\n# resolve identically everywhere.\n" + "\n".join(extras)
        )
    return f"{_HEADER}\n{body}\n"


_EXTRA_NAMES = {
    "pytest",
    "ruff",
    "mypy",
    "types-openpyxl",
    "lxml-stubs",
    "pyinstaller",
    "sentence-transformers",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if out of date")
    args = parser.parse_args(argv)
    rendered = render()
    if args.check:
        current = (
            CONSTRAINTS.read_text(encoding="utf-8") if CONSTRAINTS.exists() else ""
        )
        if current != rendered:
            print("constraints.txt is out of date; run scripts.freeze_constraints")
            return 1
        print("constraints.txt is current")
        return 0
    CONSTRAINTS.write_text(rendered, encoding="utf-8")
    print(f"wrote {CONSTRAINTS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
