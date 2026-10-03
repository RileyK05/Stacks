"""The Windows side of connecting Office: trust store, Office's add-in
registry, and launching Word/Excel/PowerPoint.

Everything is per-user (HKCU, the CurrentUser root store) and needs no admin
rights. Every function is a no-op or ``False`` elsewhere; ``service`` checks
``SUPPORTED`` before it promises anything.
"""

from __future__ import annotations

import os
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Literal

OfficeApp = Literal["word", "excel", "powerpoint"]

SUPPORTED = sys.platform == "win32"

# Office loads every manifest path listed here as a developer add-in (the
# same mechanism Microsoft's own add-in tooling uses to sideload), for Word,
# Excel and PowerPoint alike. Value name = add-in id, value = manifest path.
DEVELOPER_KEY = r"Software\Microsoft\Office\16.0\WEF\Developer"
APP_PATHS_KEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
EXECUTABLES: dict[OfficeApp, str] = {
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
}
APP_NAMES: dict[OfficeApp, str] = {
    "word": "Word",
    "excel": "Excel",
    "powerpoint": "PowerPoint",
}
_NO_WINDOW = 0x0800_0000


def installed_apps() -> list[OfficeApp]:
    """Which Office desktop apps are installed (their App Paths entries)."""
    if sys.platform != "win32":
        return []
    import winreg

    found: list[OfficeApp] = []
    for app, exe in EXECUTABLES.items():
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(
                        hive, rf"{APP_PATHS_KEY}\{exe}", 0, winreg.KEY_READ | view
                    ):
                        found.append(app)
                        break
                except OSError:
                    continue
            if app in found:
                break
    return found


def is_trusted(ca_der: bytes) -> bool:
    """Whether this exact CA is in the user's trusted root store."""
    if sys.platform != "win32":
        return False
    return any(
        cert == ca_der and encoding == "x509_asn"
        for cert, encoding, _trust in ssl.enum_certificates("ROOT")
    )


def trust(ca_path: Path) -> bool:
    """Add the CA to the user's trusted roots. Windows shows its own
    confirmation dialog; returns False if the user declines it."""
    if sys.platform != "win32":
        return False
    result = subprocess.run(
        ["certutil", "-user", "-addstore", "-f", "Root", str(ca_path)],
        capture_output=True,
        creationflags=_NO_WINDOW,
        check=False,
    )
    return result.returncode == 0


def untrust(thumbprint: str) -> None:
    """Remove the CA from the user's trusted roots (Windows confirms)."""
    if sys.platform != "win32":
        return
    result = subprocess.run(
        ["certutil", "-user", "-delstore", "Root", thumbprint],
        capture_output=True,
        creationflags=_NO_WINDOW,
        check=False,
    )
    if result.returncode != 0:
        raise OSError("Windows could not remove the Stacks certificate trust.")


def register(addin_id: str, manifest: Path) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, DEVELOPER_KEY) as key:
        winreg.SetValueEx(key, addin_id, 0, winreg.REG_SZ, str(manifest))


def unregister(addin_id: str) -> None:
    if sys.platform != "win32":
        return
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, DEVELOPER_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, addin_id)
    except FileNotFoundError:
        return


def registered_manifest(addin_id: str) -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DEVELOPER_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, addin_id)
    except FileNotFoundError:
        return None
    return str(value)


def launch(app: OfficeApp, document: Path | None = None) -> None:
    """Start an Office app, optionally opening a document in it. Raises
    OSError when the app is not installed."""
    if sys.platform != "win32":
        raise OSError("Office apps can only be launched on Windows")
    arguments = f'"{document}"' if document else ""
    os.startfile(EXECUTABLES[app], "open", arguments)
