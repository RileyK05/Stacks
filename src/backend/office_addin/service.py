"""Connect Stacks to Office, report the connection, and open documents.

State lives in three places, all inspectable: the ``office.connected``
setting (the user's intent), ``<data dir>/office-addin/`` (certificate and
rendered manifest), and Windows (trusted CA, Office's developer add-in
key). ``status`` reads all of them rather than trusting the setting alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from src.backend.common import settings_repo
from src.backend.common.config import get_settings
from src.backend.office_addin import certs, manifest, windows
from src.backend.office_addin.host import HOST, PortInUseError
from src.backend.office_addin.windows import OfficeApp
from src.backend.version import __version__

_logger = logging.getLogger(__name__)

CONNECTED_SETTING = "office.connected"
LAST_COURSE_SETTING = "office.last_course"

DOCUMENT_APPS: dict[str, OfficeApp] = {
    ".docx": "word",
    ".docm": "word",
    ".doc": "word",
    ".dotx": "word",
    ".rtf": "word",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".xls": "excel",
    ".csv": "excel",
    ".pptx": "powerpoint",
    ".pptm": "powerpoint",
    ".ppt": "powerpoint",
    ".potx": "powerpoint",
}


class OfficeSetupError(Exception):
    """A setup step the user can act on; the message says how."""


@dataclass
class OfficeStatus:
    supported: bool
    apps: list[OfficeApp]
    connected: bool
    certificate_trusted: bool
    registered: bool
    running: bool
    url: str
    problems: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.connected and not self.problems


def _folder() -> Path:
    return Path(get_settings().data_dir) / "office-addin"


def _port() -> int:
    return get_settings().office_port


def status() -> OfficeStatus:
    paths = certs.CertPaths.in_dir(_folder())
    connected = bool(settings_repo.get_setting(CONNECTED_SETTING, False))
    trusted = paths.exist() and windows.is_trusted(certs.ca_der(paths))
    manifest_path = _folder() / "manifest.xml"
    registered = (
        windows.registered_manifest(manifest.addin_id()) == str(manifest_path)
        and manifest_path.is_file()
    )
    running = HOST.running
    problems: list[str] = []
    if connected:
        if not certs.is_current(paths):
            problems.append("The local certificate is missing or expiring.")
        elif not trusted:
            problems.append("Windows no longer trusts the Stacks certificate.")
        if not registered:
            problems.append("The add-in is no longer registered with Office.")
        if not running:
            problems.append(
                f"The add-in is not being served (port {_port()} may be in use)."
            )
    return OfficeStatus(
        supported=windows.SUPPORTED,
        apps=windows.installed_apps(),
        connected=connected,
        certificate_trusted=trusted,
        registered=registered,
        running=running,
        url=manifest.origin(_port()),
        problems=problems,
    )


def connect() -> OfficeStatus:
    """Do every step needed for the Stacks button to appear in Word, Excel
    and PowerPoint. Idempotent: repairs whatever ``status`` reports."""
    if not windows.SUPPORTED:
        raise OfficeSetupError(
            "Connecting Office is available on Windows with Microsoft 365 or "
            "Office 2016 or later."
        )
    folder = _folder()
    paths = certs.CertPaths.in_dir(folder)
    if not certs.is_current(paths):
        paths = certs.issue(folder)
    if not windows.is_trusted(certs.ca_der(paths)) and not windows.trust(paths.ca):
        raise OfficeSetupError(
            "Windows asked whether to trust the Stacks certificate and it was "
            "declined. Office only loads add-ins over a trusted connection; "
            "try again and choose Yes."
        )
    manifest_path = manifest.write(folder, _port(), __version__)
    windows.register(manifest.addin_id(), manifest_path)
    _start(paths)
    settings_repo.put_setting(CONNECTED_SETTING, True)
    return status()


def disconnect() -> OfficeStatus:
    """Undo ``connect``: unregister, stop serving, untrust, delete files."""
    HOST.stop()
    windows.unregister(manifest.addin_id())
    paths = certs.CertPaths.in_dir(_folder())
    if paths.ca.is_file() and windows.is_trusted(certs.ca_der(paths)):
        windows.untrust(certs.ca_thumbprint(paths))
    for path in (paths.cert, paths.key, paths.ca, _folder() / "manifest.xml"):
        path.unlink(missing_ok=True)
    settings_repo.put_setting(CONNECTED_SETTING, False)
    return status()


def start_if_connected() -> None:
    """Called at backend startup. Never prompts: a certificate that needs
    renewing or re-trusting waits for the user to press Connect again."""
    if not settings_repo.get_setting(CONNECTED_SETTING, False):
        return
    paths = certs.CertPaths.in_dir(_folder())
    if not certs.is_current(paths) or not windows.is_trusted(certs.ca_der(paths)):
        _logger.warning("Office add-in not started: certificate needs renewing")
        return
    # The app version may have changed since the manifest was written.
    manifest_path = manifest.write(_folder(), _port(), __version__)
    windows.register(manifest.addin_id(), manifest_path)
    try:
        _start(paths)
    except OfficeSetupError as err:
        _logger.warning("Office add-in not started: %s", err)


def stop() -> None:
    HOST.stop()


def _start(paths: certs.CertPaths) -> None:
    from src.backend.office_addin.app import create_office_host

    try:
        HOST.start(create_office_host(), port=_port(), cert=paths.cert, key=paths.key)
    except PortInUseError as err:
        raise OfficeSetupError(
            f"Stacks could not serve the Office add-in: {err}."
        ) from err


def app_for(document: Path) -> OfficeApp:
    app = DOCUMENT_APPS.get(document.suffix.lower())
    if app is None:
        raise OfficeSetupError(
            f"{document.name} is not a Word, Excel or PowerPoint file."
        )
    return app


def open_document(
    app: OfficeApp | None, document: Path | None, course_id: UUID | None
) -> OfficeApp:
    """Launch Office (a new document, or ``document``) and remember the
    course so the Stacks pane opens on it."""
    if document is not None:
        if not document.is_file():
            raise OfficeSetupError(f"{document} does not exist.")
        app = app_for(document)
    if app is None:
        raise OfficeSetupError("Choose Word, Excel or PowerPoint, or a file.")
    if course_id is not None:
        settings_repo.put_setting(LAST_COURSE_SETTING, str(course_id))
    try:
        windows.launch(app, document)
    except OSError as err:
        raise OfficeSetupError(
            f"Could not start {windows.APP_NAMES[app]}: is Microsoft Office "
            f"installed? ({err})"
        ) from err
    return app


def last_course() -> str | None:
    value = settings_repo.get_setting(LAST_COURSE_SETTING)
    return str(value) if value else None
