from __future__ import annotations

from scripts.release_notes import release_notes

CHANGELOG = """# Changelog

## [Unreleased]

### Added
- Next thing.

## [1.2.0] - 2026-01-01

### Fixed
- A bug.

## [1.1.0]
- Old.
"""


def test_notes_are_the_versions_own_section() -> None:
    assert release_notes("1.2.0", CHANGELOG) == "### Fixed\n- A bug."
    assert release_notes("1.1.0", CHANGELOG) == "- Old."


def test_a_version_without_a_section_points_at_the_changelog() -> None:
    assert release_notes("9.9.9", CHANGELOG) == "See CHANGELOG.md."
