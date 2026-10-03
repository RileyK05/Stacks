"""One version, written down in several places (scripts/set_version.py)."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
from scripts import set_version
from src.backend.version import __version__


def test_every_manifest_carries_the_same_version() -> None:
    pyproject = tomllib.loads(set_version.PYPROJECT.read_text(encoding="utf-8"))
    cargo = tomllib.loads(set_version.CARGO_TOML.read_text(encoding="utf-8"))
    cargo_lock = tomllib.loads(set_version.CARGO_LOCK.read_text(encoding="utf-8"))
    package = json.loads(set_version.PACKAGE_JSON.read_text(encoding="utf-8"))
    lock = json.loads(set_version.PACKAGE_LOCK.read_text(encoding="utf-8"))
    assert set_version.SEMVER.match(__version__)
    assert {
        "pyproject.toml": pyproject["project"]["version"],
        "Cargo.toml": cargo["package"]["version"],
        "Cargo.lock": next(
            package["version"]
            for package in cargo_lock["package"]
            if package["name"] == "stacks"
        ),
        "package.json": package["version"],
        "package-lock.json": lock["version"],
    } == dict.fromkeys(
        (
            "pyproject.toml",
            "Cargo.toml",
            "Cargo.lock",
            "package.json",
            "package-lock.json",
        ),
        __version__,
    )


def test_the_tauri_app_takes_its_version_from_package_json() -> None:
    conf = set_version.CARGO_TOML.parent / "tauri.conf.json"
    assert json.loads(conf.read_text(encoding="utf-8"))["version"] == "../package.json"


def test_the_changelog_has_an_entry_for_this_version() -> None:
    changelog = (set_version.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[?{re.escape(__version__)}\]?", changelog, re.MULTILINE)


def test_set_version_updates_every_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {
        "VERSION_PY": ('__version__ = "0.2.0"\n', "version.py"),
        "PYPROJECT": ('version = "0.2.0"\n', "pyproject.toml"),
        "CARGO_TOML": ('version = "0.2.0"\n', "Cargo.toml"),
        "CARGO_LOCK": (
            '[[package]]\nname = "stacks"\nversion = "0.2.0"\n',
            "Cargo.lock",
        ),
        "PACKAGE_JSON": ('{"version":"0.2.0"}\n', "package.json"),
        "PACKAGE_LOCK": (
            '{"version":"0.2.0","packages":{"":{"version":"0.2.0"}}}\n',
            "package-lock.json",
        ),
    }
    paths: dict[str, Path] = {}
    for constant, (content, name) in files.items():
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        monkeypatch.setattr(set_version, constant, path)
        paths[constant] = path

    set_version.set_version("1.2.3")

    assert 'version = "1.2.3"' in paths["CARGO_LOCK"].read_text(encoding="utf-8")
    assert (
        json.loads(paths["PACKAGE_LOCK"].read_text(encoding="utf-8"))["packages"][""][
            "version"
        ]
        == "1.2.3"
    )
