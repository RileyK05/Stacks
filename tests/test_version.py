"""One version, written down in several places (scripts/set_version.py)."""

from __future__ import annotations

import json
import re
import tomllib

from scripts import set_version
from src.backend.version import __version__


def test_every_manifest_carries_the_same_version() -> None:
    pyproject = tomllib.loads(set_version.PYPROJECT.read_text(encoding="utf-8"))
    cargo = tomllib.loads(set_version.CARGO_TOML.read_text(encoding="utf-8"))
    package = json.loads(set_version.PACKAGE_JSON.read_text(encoding="utf-8"))
    lock = json.loads(set_version.PACKAGE_LOCK.read_text(encoding="utf-8"))
    assert set_version.SEMVER.match(__version__)
    assert {
        "pyproject.toml": pyproject["project"]["version"],
        "Cargo.toml": cargo["package"]["version"],
        "package.json": package["version"],
        "package-lock.json": lock["version"],
    } == dict.fromkeys(
        ("pyproject.toml", "Cargo.toml", "package.json", "package-lock.json"),
        __version__,
    )


def test_the_tauri_app_takes_its_version_from_package_json() -> None:
    conf = set_version.CARGO_TOML.parent / "tauri.conf.json"
    assert json.loads(conf.read_text(encoding="utf-8"))["version"] == "../package.json"


def test_the_changelog_has_an_entry_for_this_version() -> None:
    changelog = (set_version.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[?{re.escape(__version__)}\]?", changelog, re.MULTILINE)
