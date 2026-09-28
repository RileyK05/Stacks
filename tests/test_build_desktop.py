from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts import build_desktop


def test_installer_build_cleans_stale_output_and_locks_cargo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shell = tmp_path / "src-tauri"
    bundle = shell / "target" / "release" / "bundle"
    stale = bundle / "nsis" / "Stacks_old_x64-setup.exe"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    expected = bundle / "nsis" / "Stacks_1.2.3_x64-setup.exe"
    calls: list[tuple[list[str], Path]] = []

    def fake_run(
        command: list[str], *, cwd: Path, check: bool
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        assert not stale.exists()
        calls.append((command, cwd))
        expected.parent.mkdir(parents=True)
        expected.write_bytes(b"installer")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build_desktop, "SHELL", shell)
    monkeypatch.setattr(build_desktop.subprocess, "run", fake_run)

    assert build_desktop.build_installer() == [expected]
    command, cwd = calls[0]
    assert cwd == build_desktop.FRONTEND
    assert command[-2:] == ["--", "--locked"]
