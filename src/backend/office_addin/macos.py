"""Per-user Office add-in setup for macOS.

Manifests are copied into the user container for each installed Office app.
The Stacks CA is managed only in the user's login keychain through Apple's
``security`` command; Office launches use the exact detected application path.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from src.backend.office_addin.windows import APP_NAMES, OfficeApp

if TYPE_CHECKING:
    from collections.abc import Sequence

SUPPORTED = sys.platform == "darwin"
COMMAND_TIMEOUT_SECONDS = 30
SECURITY = "/usr/bin/security"
OPEN = "/usr/bin/open"

APP_PATHS: dict[OfficeApp, tuple[str, str]] = {
    "word": ("Microsoft Word.app", "com.microsoft.Word"),
    "excel": ("Microsoft Excel.app", "com.microsoft.Excel"),
    "powerpoint": ("Microsoft PowerPoint.app", "com.microsoft.Powerpoint"),
}
_ADDIN_ID = re.compile(r"[0-9a-fA-F]+(?:-[0-9a-fA-F]+)*\Z")
_SHA1_THUMBPRINT = re.compile(r"[0-9a-fA-F]{40}\Z")


def _app_path(app: OfficeApp) -> Path | None:
    application_name, _container_id = APP_PATHS[app]
    for folder in (Path("/Applications"), Path.home() / "Applications"):
        candidate = folder / application_name
        if candidate.is_dir():
            return candidate
    return None


def _container_path(app: OfficeApp) -> Path:
    _application_name, container_id = APP_PATHS[app]
    return (
        Path.home()
        / "Library"
        / "Containers"
        / container_id
        / "Data"
        / "Documents"
        / "wef"
    )


def _manifest_path(app: OfficeApp, addin_id: str) -> Path:
    return _container_path(app) / f"stacks-{addin_id}.xml"


def _validate_addin_id(addin_id: str) -> None:
    if (
        not isinstance(addin_id, str)
        or len(addin_id) > 128
        or not _ADDIN_ID.fullmatch(addin_id)
    ):
        raise ValueError(
            "Add-in ID must contain only hexadecimal characters and hyphens."
        )


def _login_keychain() -> Path:
    return Path.home() / "Library" / "Keychains" / "login.keychain-db"


def _run_security(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SECURITY, *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )


def _temporary_certificate(certificate_der: bytes) -> tempfile.TemporaryDirectory[str]:
    temporary = tempfile.TemporaryDirectory(prefix="stacks-office-ca-")
    (Path(temporary.name) / "stacks-ca.cer").write_bytes(certificate_der)
    return temporary


def installed_apps() -> list[OfficeApp]:
    """Return Office apps found in /Applications or ~/Applications."""
    if sys.platform != "darwin":
        return []
    return [app for app in APP_PATHS if _app_path(app) is not None]


def is_trusted(ca_der: bytes) -> bool:
    """Check the exact CA fingerprint and its basic certificate trust."""
    if sys.platform != "darwin":
        return False
    thumbprint = hashlib.sha1(ca_der, usedforsecurity=False).hexdigest().upper()
    try:
        with _temporary_certificate(ca_der) as temporary:
            cert_path = str(Path(temporary) / "stacks-ca.cer")
            keychain = str(_login_keychain())
            found = _run_security(["find-certificate", "-a", "-Z", keychain])
            if found.returncode != 0 or thumbprint not in found.stdout.upper():
                return False
            verified = _run_security(
                ["verify-cert", "-c", cert_path, "-p", "basic", "-k", keychain]
            )
            return verified.returncode == 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def trust(ca_path: Path) -> bool:
    """Add only the supplied CA to the user's login keychain."""
    if sys.platform != "darwin":
        return False
    try:
        result = _run_security(
            [
                "add-trusted-cert",
                "-r",
                "trustRoot",
                "-k",
                str(_login_keychain()),
                str(ca_path),
            ]
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def untrust(thumbprint: str) -> None:
    """Delete the exact SHA-1 certificate from the user's login keychain."""
    if sys.platform != "darwin":
        return
    if not isinstance(thumbprint, str) or not _SHA1_THUMBPRINT.fullmatch(thumbprint):
        raise ValueError("Certificate thumbprint must be 40 hexadecimal characters.")
    try:
        result = _run_security(
            [
                "delete-certificate",
                "-Z",
                thumbprint.upper(),
                "-t",
                str(_login_keychain()),
            ]
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OSError(f"Could not remove the Stacks certificate: {error}") from error
    if result.returncode != 0:
        raise OSError(
            result.stderr.strip() or "Could not remove the Stacks certificate."
        )


def register(addin_id: str, manifest: Path) -> None:
    if sys.platform != "darwin":
        return
    _validate_addin_id(addin_id)
    content = manifest.read_bytes()
    for app in installed_apps():
        destination = _manifest_path(app, addin_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def unregister(addin_id: str) -> None:
    if sys.platform != "darwin":
        return
    _validate_addin_id(addin_id)
    for app in APP_PATHS:
        _manifest_path(app, addin_id).unlink(missing_ok=True)


def is_registered(addin_id: str, manifest: Path) -> bool:
    if sys.platform != "darwin":
        return False
    _validate_addin_id(addin_id)
    apps = installed_apps()
    if not apps or not manifest.is_file():
        return False
    expected = manifest.read_bytes()
    try:
        return all(
            _manifest_path(app, addin_id).read_bytes() == expected for app in apps
        )
    except OSError:
        return False


def launch(app: OfficeApp, document: Path | None = None) -> None:
    """Open a detected Office app and optional document without shell parsing."""
    if sys.platform != "darwin":
        raise OSError("Office apps can only be launched on macOS")
    app_path = _app_path(app)
    if app_path is None:
        raise OSError(f"Microsoft {APP_NAMES[app]} is not installed.")
    arguments = [OPEN, "-a", str(app_path)]
    if document is not None:
        arguments.append(str(document))
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OSError(
            f"Could not launch Microsoft {APP_NAMES[app]}: {error}"
        ) from error
    if result.returncode != 0:
        raise OSError(
            result.stderr.strip() or f"Could not launch Microsoft {APP_NAMES[app]}."
        )
