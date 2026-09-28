"""The add-in manifest Office is pointed at.

``src/office-addin/public/manifest.xml`` is written for the default port;
the copy registered with Office is rendered from it with this machine's
origin and the app version (Office reloads a cached add-in when the version
changes).
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree
from src.backend.common.config import DEFAULT_OFFICE_PORT, PROJECT_ROOT

# Only what Office loads; the add-in's tests and tooling sit one level up.
ADDIN_DIR = PROJECT_ROOT / "src" / "office-addin" / "public"
TEMPLATE = ADDIN_DIR / "manifest.xml"
TEMPLATE_ORIGIN = f"https://localhost:{DEFAULT_OFFICE_PORT}"
_APP_NS = "http://schemas.microsoft.com/office/appforoffice/1.1"


def origin(port: int) -> str:
    return f"https://localhost:{port}"


def addin_id() -> str:
    root = etree.parse(str(TEMPLATE)).getroot()
    value = root.findtext(f"{{{_APP_NS}}}Id")
    if not value:
        raise ValueError(f"{TEMPLATE} has no <Id>")
    return value.strip()


def office_version(app_version: str) -> str:
    """Office wants four numeric parts and at least 1.0, so the app version
    goes after a fixed 1: ``0.2.0`` -> ``1.0.2.0``. It still only grows as
    the app version grows."""
    parts = [re.sub(r"\D.*", "", part) or "0" for part in app_version.split(".")]
    return ".".join(["1", *(parts + ["0"] * 3)[:3]])


def render(port: int, app_version: str) -> str:
    text = TEMPLATE.read_text(encoding="utf-8").replace(TEMPLATE_ORIGIN, origin(port))
    return re.sub(
        r"<Version>[^<]*</Version>",
        f"<Version>{office_version(app_version)}</Version>",
        text,
        count=1,
    )


def write(folder: Path, port: int, app_version: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.xml"
    path.write_text(render(port, app_version), encoding="utf-8")
    return path
