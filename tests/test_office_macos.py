from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from src.backend.office_addin import macos

ADDIN_ID = "12345678-1234-4abc-9def-1234567890ab"


def enable_macos(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setattr(macos.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))


def fake_apps(monkeypatch: pytest.MonkeyPatch, apps: dict[str, Path]) -> None:
    def is_dir(path: Path) -> bool:
        return path in apps.values()

    monkeypatch.setattr(Path, "is_dir", is_dir)


def test_supported_and_installed_apps_include_system_and_user_locations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home with spaces"
    enable_macos(monkeypatch, home)
    apps = {
        "word": Path("/Applications/Microsoft Word.app"),
        "excel": home / "Applications" / "Microsoft Excel.app",
    }
    fake_apps(monkeypatch, apps)

    assert macos.installed_apps() == ["word", "excel"]
    assert macos._app_path("word") == apps["word"]
    assert macos._app_path("excel") == apps["excel"]
    assert macos.APP_NAMES["word"] == "Word"


def test_installation_operations_are_inert_off_macos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(macos.sys, "platform", "win32")
    monkeypatch.setattr(
        macos, "_container_path", lambda _app: pytest.fail("path accessed")
    )
    monkeypatch.setattr(macos, "_app_path", lambda _app: pytest.fail("app probed"))
    monkeypatch.setattr(
        macos, "_run_security", lambda _args: pytest.fail("security called")
    )
    manifest = tmp_path / "missing.xml"

    assert macos.installed_apps() == []
    assert not macos.is_trusted(b"ca")
    assert not macos.trust(manifest)
    macos.untrust("invalid")
    macos.register("../bad", manifest)
    macos.unregister("../bad")
    assert not macos.is_registered("../bad", manifest)
    with pytest.raises(OSError, match="only be launched on macOS"):
        macos.launch("word")


def test_register_copies_only_to_each_installed_user_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home with spaces"
    enable_macos(monkeypatch, home)
    apps = {
        "word": Path("/Applications/Microsoft Word.app"),
        "powerpoint": home / "Applications" / "Microsoft PowerPoint.app",
    }
    fake_apps(monkeypatch, apps)
    source = tmp_path / "manifest with spaces.xml"
    source.write_text("exact <manifest />\n", encoding="utf-8")

    macos.register(ADDIN_ID, source)

    word_copy = (
        home
        / "Library/Containers/com.microsoft.Word/Data/Documents/wef"
        / f"stacks-{ADDIN_ID}.xml"
    )
    powerpoint_copy = (
        home
        / "Library/Containers/com.microsoft.Powerpoint/Data/Documents/wef"
        / f"stacks-{ADDIN_ID}.xml"
    )
    assert word_copy.read_bytes() == source.read_bytes()
    assert powerpoint_copy.read_bytes() == source.read_bytes()
    assert not (
        home
        / "Library/Containers/com.microsoft.Excel/Data/Documents/wef"
        / f"stacks-{ADDIN_ID}.xml"
    ).exists()


@pytest.mark.parametrize(
    "addin_id", ["../escape", "-abc", "abc-", "abc/123", "x" * 129]
)
def test_registration_validates_addin_id_before_resolving_file_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, addin_id: str
) -> None:
    enable_macos(monkeypatch, tmp_path)
    monkeypatch.setattr(
        macos, "_container_path", lambda _app: pytest.fail("path computed")
    )

    with pytest.raises(ValueError, match="hexadecimal characters"):
        macos.register(addin_id, tmp_path / "manifest.xml")
    with pytest.raises(ValueError, match="hexadecimal characters"):
        macos.unregister(addin_id)
    with pytest.raises(ValueError, match="hexadecimal characters"):
        macos.is_registered(addin_id, tmp_path / "manifest.xml")


def test_unregister_removes_only_this_addin_from_office_container_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    enable_macos(monkeypatch, home)
    target_dirs = [
        macos._manifest_path(app, ADDIN_ID).parent for app in macos.APP_PATHS
    ]
    for directory in target_dirs:
        directory.mkdir(parents=True)
        (directory / f"stacks-{ADDIN_ID}.xml").write_text("own")
        (directory / "other-addin.xml").write_text("preserve")

    macos.unregister(ADDIN_ID)

    for directory in target_dirs:
        assert not (directory / f"stacks-{ADDIN_ID}.xml").exists()
        assert (directory / "other-addin.xml").read_text() == "preserve"


def test_registration_verifies_exact_copies_for_all_detected_apps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    enable_macos(monkeypatch, home)
    apps = {
        "word": Path("/Applications/Microsoft Word.app"),
        "excel": home / "Applications/Microsoft Excel.app",
    }
    fake_apps(monkeypatch, apps)
    source = tmp_path / "manifest.xml"
    source.write_text("<manifest />", encoding="utf-8")

    assert not macos.is_registered(ADDIN_ID, source)
    macos.register(ADDIN_ID, source)
    assert macos.is_registered(ADDIN_ID, source)
    _manifest_copy = macos._manifest_path("excel", ADDIN_ID)
    _manifest_copy.write_text("changed", encoding="utf-8")
    assert not macos.is_registered(ADDIN_ID, source)


def test_registration_with_no_installed_apps_is_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    enable_macos(monkeypatch, tmp_path)
    fake_apps(monkeypatch, {})
    source = tmp_path / "manifest.xml"
    source.write_text("manifest", encoding="utf-8")

    assert macos.installed_apps() == []
    assert not macos.is_registered(ADDIN_ID, source)


def test_trust_uses_login_keychain_argument_array_and_reports_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home with spaces"
    enable_macos(monkeypatch, home)
    ca = tmp_path / "CA cert with spaces.cer"
    ca.write_bytes(b"CA")
    seen: list[list[str]] = []

    def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        seen.append(arguments)
        return subprocess.CompletedProcess(
            arguments, returncode=1, stdout="", stderr="no"
        )

    monkeypatch.setattr(macos, "_run_security", run)

    assert not macos.trust(ca)
    assert seen == [
        [
            "add-trusted-cert",
            "-r",
            "trustRoot",
            "-k",
            str(home / "Library/Keychains/login.keychain-db"),
            str(ca),
        ]
    ]


def test_is_trusted_checks_exact_fingerprint_then_basic_policy_and_cleans_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    enable_macos(monkeypatch, home)
    ca_der = b"specific CA bytes"
    fingerprint = macos.hashlib.sha1(ca_der, usedforsecurity=False).hexdigest().upper()
    calls: list[list[str]] = []
    temporary_paths: list[Path] = []

    def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[0] == "find-certificate":
            return subprocess.CompletedProcess(
                arguments, 0, f"SHA-1 hash: {fingerprint}", ""
            )
        temporary_paths.append(Path(arguments[2]))
        assert temporary_paths[-1].read_bytes() == ca_der
        return subprocess.CompletedProcess(arguments, 0, "trusted", "")

    monkeypatch.setattr(macos, "_run_security", run)

    assert macos.is_trusted(ca_der)
    assert calls[0] == [
        "find-certificate",
        "-a",
        "-Z",
        str(home / "Library/Keychains/login.keychain-db"),
    ]
    assert calls[1][0:5] == ["verify-cert", "-c", calls[1][2], "-p", "basic"]
    assert calls[1][-2:] == ["-k", str(home / "Library/Keychains/login.keychain-db")]
    assert len(temporary_paths) == 1 and not temporary_paths[0].exists()


def test_is_trusted_requires_matching_exact_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    enable_macos(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "SHA-1 hash: different", "")

    monkeypatch.setattr(macos, "_run_security", run)

    assert not macos.is_trusted(b"CA")
    assert len(calls) == 1


def test_untrust_validates_thumbprint_and_deletes_by_exact_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home with spaces"
    enable_macos(monkeypatch, home)
    calls: list[list[str]] = []

    def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(macos, "_run_security", run)

    macos.untrust("ab" * 20)

    assert calls == [
        [
            "delete-certificate",
            "-Z",
            "AB" * 20,
            "-t",
            str(home / "Library/Keychains/login.keychain-db"),
        ]
    ]
    for invalid in ("xyz", "ab" * 19, "ab" * 19 + "g0"):
        with pytest.raises(ValueError, match="40 hexadecimal"):
            macos.untrust(invalid)


def test_launch_uses_exact_app_and_separate_document_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    enable_macos(monkeypatch, home)
    app_path = home / "Applications" / "Microsoft Word.app"
    fake_apps(monkeypatch, {"word": app_path})
    document = tmp_path / "lecture notes and homework.docx"
    calls: list[dict[str, Any]] = []

    def run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"arguments": arguments, **kwargs})
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(macos.subprocess, "run", run)

    macos.launch("word", document)

    assert calls[0]["arguments"] == [
        "/usr/bin/open",
        "-a",
        str(app_path),
        str(document),
    ]
    assert "shell" not in calls[0]
    assert calls[0]["timeout"] == 30
    assert calls[0]["capture_output"] and calls[0]["text"]


def test_launch_reports_missing_apps_command_failures_and_timeouts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    enable_macos(monkeypatch, home)
    fake_apps(monkeypatch, {})
    with pytest.raises(OSError, match="not installed"):
        macos.launch("word")

    app_path = home / "Applications" / "Microsoft Word.app"
    fake_apps(monkeypatch, {"word": app_path})
    monkeypatch.setattr(
        macos.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", "open failed"),
    )
    with pytest.raises(OSError, match="open failed"):
        macos.launch("word")

    def timeout(*_args: Any, **_kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("open", 30)

    monkeypatch.setattr(macos.subprocess, "run", timeout)
    with pytest.raises(OSError, match="timed out"):
        macos.launch("word")


def test_security_timeouts_and_command_errors_are_handled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    enable_macos(monkeypatch, tmp_path)

    def timeout(_arguments: list[str]) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("security", 30)

    monkeypatch.setattr(macos, "_run_security", timeout)
    assert not macos.trust(tmp_path / "ca.cer")
    assert not macos.is_trusted(b"CA")
    with pytest.raises(OSError, match="timed out"):
        macos.untrust("ab" * 20)
