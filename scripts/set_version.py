"""Set the app's version everywhere it is written down.

    .venv/Scripts/python -m scripts.set_version 0.3.0

The version lives in src/backend/version.py (what the API reports),
pyproject.toml, src/frontend/package.json (+ its lockfile; the Tauri
config reads the version from package.json) and the Tauri crate's
Cargo.toml. tests/test_version.py fails if they disagree. Add the
release's notes to CHANGELOG.md alongside.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")

VERSION_PY = ROOT / "src" / "backend" / "version.py"
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_JSON = ROOT / "src" / "frontend" / "package.json"
PACKAGE_LOCK = ROOT / "src" / "frontend" / "package-lock.json"
CARGO_TOML = ROOT / "src" / "frontend" / "src-tauri" / "Cargo.toml"


def _replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"no version line found in {path}")
    path.write_text(updated, encoding="utf-8")


def _set_json(path: Path, version: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    root_package = data.get("packages", {}).get("")
    if root_package is not None:
        root_package["version"] = version
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def set_version(version: str) -> None:
    if not SEMVER.match(version):
        raise SystemExit(f"not a semantic version: {version!r}")
    _replace_once(VERSION_PY, r'^__version__ = ".*"$', f'__version__ = "{version}"')
    _replace_once(PYPROJECT, r'^version = ".*"$', f'version = "{version}"')
    _replace_once(CARGO_TOML, r'^version = ".*"$', f'version = "{version}"')
    _set_json(PACKAGE_JSON, version)
    if PACKAGE_LOCK.exists():
        _set_json(PACKAGE_LOCK, version)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m scripts.set_version X.Y.Z")
    set_version(args[0])
    print(f"version set to {args[0]}; add its notes to CHANGELOG.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
