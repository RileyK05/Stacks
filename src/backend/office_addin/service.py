"""Connect Stacks to Office, report the connection, and open documents.

State lives in three places, all inspectable: the ``office.connected``
setting (the user's intent), ``<data dir>/office-addin/`` (certificate and
rendered manifest), and the platform's trusted CA and Office registration.
``status`` reads all of them rather than trusting the setting alone.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

from src.backend.common import settings_repo
from src.backend.common.config import get_settings
from src.backend.office_addin import certs, live, macos, manifest, preferences, windows
from src.backend.office_addin.host import HOST, PortInUseError
from src.backend.office_addin.windows import OfficeApp
from src.backend.version import __version__

_logger = logging.getLogger(__name__)

CONNECTED_SETTING = "office.connected"
PENDING_TRUST_SETTING = "office.pending_trust_cleanup"
_LIFECYCLE_LOCK = threading.RLock()
_COHORT_NAMES = (
    "localhost.pem",
    "localhost-key.pem",
    "stacks-local-ca.cer",
    "manifest.xml",
)

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

    def __str__(self) -> str:
        message = super().__str__()
        notes = getattr(self, "__notes__", ())
        return f"{message} ({'; '.join(notes)})" if notes else message


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


@dataclass
class _Snapshot:
    files: dict[str, bytes | None]
    connected: bool
    active_ca: bytes | None
    active_trusted: bool
    active_thumbprint: str | None
    registration: object
    host_running: bool
    pending: list[dict[str, str]]


def _folder() -> Path:
    return Path(get_settings().data_dir) / "office-addin"


def _port() -> int:
    return get_settings().office_port


def _platform() -> ModuleType:
    return macos if sys.platform == "darwin" else windows


def _registered(path: Path) -> bool:
    if sys.platform == "darwin":
        return macos.is_registered(manifest.addin_id(), path)
    return (
        windows.registered_manifest(manifest.addin_id()) == str(path) and path.is_file()
    )


def status() -> OfficeStatus:
    with _LIFECYCLE_LOCK:
        return _status_locked()


def _status_locked() -> OfficeStatus:
    paths = certs.CertPaths.in_dir(_folder())
    platform = _platform()
    connected = bool(settings_repo.get_setting(CONNECTED_SETTING, False))
    trusted = paths.exist() and platform.is_trusted(certs.ca_der(paths))
    manifest_path = _folder() / "manifest.xml"
    registered = _registered(manifest_path)
    running = HOST.running
    problems: list[str] = []
    pending = [item["thumbprint"] for item in _pending_records()]
    if pending:
        problems.append(
            "Office certificate cleanup is incomplete for trust thumbprint(s) "
            f"{', '.join(pending)}. Disconnect or reconnect to retry cleanup."
        )
    if connected:
        if not certs.is_current(paths):
            problems.append("The local certificate is missing or expiring.")
        elif not trusted:
            problems.append("This computer no longer trusts the Stacks certificate.")
        if not registered:
            problems.append("The add-in is no longer registered with Office.")
        if not running:
            problems.append(
                f"The add-in is not being served (port {_port()} may be in use)."
            )
    return OfficeStatus(
        supported=platform.SUPPORTED,
        apps=platform.installed_apps(),
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
    with _LIFECYCLE_LOCK:
        platform = _platform()
        if not platform.SUPPORTED:
            raise OfficeSetupError(
                "Connecting Office is available on Windows and macOS "
                "with compatible Microsoft Office desktop apps."
            )
        folder = _folder()
        folder.mkdir(parents=True, exist_ok=True)
        snapshot = _snapshot(platform, folder)
        candidate_thumbprint: str | None = None
        candidate_der: bytes | None = None
        candidate_trust_introduced = False
        host_stopped_for_change = False
        try:
            paths = certs.CertPaths.in_dir(folder)
            if not certs.is_current(paths):
                with tempfile.TemporaryDirectory(
                    prefix="office-candidate-", dir=folder
                ) as staged:
                    staged_paths = certs.issue(Path(staged))
                    candidate_thumbprint = certs.ca_thumbprint(staged_paths)
                    candidate_der = certs.ca_der(staged_paths)
                    trusted_before = platform.is_trusted(candidate_der)
                    try:
                        accepted = trusted_before or platform.trust(staged_paths.ca)
                    except Exception:
                        candidate_trust_introduced = (
                            _trust_may_have_changed(platform, candidate_der)
                            and not trusted_before
                        )
                        raise
                    if not accepted:
                        candidate_trust_introduced = (
                            _trust_may_have_changed(platform, candidate_der)
                            and not trusted_before
                        )
                        raise _trust_declined()
                    candidate_trust_introduced = not trusted_before
                    if HOST.running:
                        HOST.stop()
                        host_stopped_for_change = True
                    _publish_cohort(staged_paths, paths)
            else:
                paths = certs.CertPaths.in_dir(folder)
                candidate_thumbprint = certs.ca_thumbprint(paths)
                candidate_der = certs.ca_der(paths)
                trusted_before = platform.is_trusted(certs.ca_der(paths))
                if not trusted_before:
                    try:
                        accepted = platform.trust(paths.ca)
                    except Exception:
                        candidate_trust_introduced = _trust_may_have_changed(
                            platform, candidate_der
                        )
                        raise
                    if not accepted:
                        # A provider can report failure after making the trust change.
                        candidate_trust_introduced = _trust_may_have_changed(
                            platform, certs.ca_der(paths)
                        )
                        raise _trust_declined()
                    candidate_trust_introduced = True
                if HOST.running:
                    HOST.stop()
                    host_stopped_for_change = True

            manifest_path = manifest.write(folder, _port(), __version__)
            try:
                platform.register(manifest.addin_id(), manifest_path)
            except OSError as error:
                raise OfficeSetupError(
                    f"Could not install the Office manifest: {error}"
                ) from error
            _start(paths)
            settings_repo.put_setting(CONNECTED_SETTING, True)
        except Exception as error:
            primary = (
                error
                if isinstance(error, OfficeSetupError)
                else OfficeSetupError(f"Could not connect Office: {error}")
            )
            _rollback_connect(
                primary,
                platform,
                folder,
                snapshot,
                candidate_thumbprint,
                candidate_der,
                candidate_trust_introduced,
                host_stopped_for_change,
            )
            if primary is error:
                raise
            raise primary from error

        # A successful renewal replaces the active trust. Old trust cleanup is
        # best effort and recorded so status/disconnect can report and retry it.
        old_thumbprint = snapshot.active_thumbprint
        if (
            snapshot.active_trusted
            and old_thumbprint
            and old_thumbprint != candidate_thumbprint
        ):
            try:
                platform.untrust(old_thumbprint)
                _forget_pending(old_thumbprint)
            except Exception as cleanup_error:
                try:
                    _remember_pending(old_thumbprint, snapshot.active_ca)
                except Exception as record_error:
                    _logger.error(
                        "Could not record pending Office trust cleanup for %s: %s",
                        old_thumbprint,
                        record_error,
                    )
                _logger.warning(
                    "Connected Office, but old certificate trust cleanup failed: %s",
                    cleanup_error,
                )
        _retry_pending_trust(platform, candidate_thumbprint)
        return _status_locked()


def disconnect() -> OfficeStatus:
    """Undo ``connect``: unregister, stop serving, untrust, delete files."""
    with _LIFECYCLE_LOCK:
        platform = _platform()
        folder = _folder()
        snapshot = _snapshot(platform, folder)
        try:
            HOST.stop()
        except Exception as error:
            raise OfficeSetupError(
                "Could not stop the Office add-in host; certificate files and "
                f"trust were kept: {error}"
            ) from error
        try:
            platform.unregister(manifest.addin_id())
            _remove_trusts(platform, snapshot)
            for name in _COHORT_NAMES:
                (folder / name).unlink(missing_ok=True)
            settings_repo.put_setting(CONNECTED_SETTING, False)
        except Exception as error:
            primary = OfficeSetupError(f"Could not fully disconnect Office: {error}")
            _rollback_disconnect(primary, platform, folder, snapshot)
            raise primary from error
        live.BROKER.clear()
        return _status_locked()


def start_if_connected() -> None:
    """Called at backend startup. Never prompts: a certificate that needs
    renewing or re-trusting waits for the user to press Connect again."""
    with _LIFECYCLE_LOCK:
        if not settings_repo.get_setting(CONNECTED_SETTING, False):
            return
        paths = certs.CertPaths.in_dir(_folder())
        platform = _platform()
        if not certs.is_current(paths) or not platform.is_trusted(certs.ca_der(paths)):
            _logger.warning("Office add-in not started: certificate needs renewing")
            return
        manifest_path = manifest.write(_folder(), _port(), __version__)
        try:
            platform.register(manifest.addin_id(), manifest_path)
            _start(paths)
        except (OfficeSetupError, OSError) as err:
            _logger.warning("Office add-in not started: %s", err)


def stop() -> None:
    with _LIFECYCLE_LOCK:
        HOST.stop()
        live.BROKER.clear()


def _snapshot(platform: ModuleType, folder: Path) -> _Snapshot:
    paths = certs.CertPaths.in_dir(folder)
    try:
        active_ca = paths.ca.read_bytes()
    except OSError:
        active_ca = None
    return _Snapshot(
        files={name: _read_optional(folder / name) for name in _COHORT_NAMES},
        connected=bool(settings_repo.get_setting(CONNECTED_SETTING, False)),
        active_ca=active_ca,
        active_trusted=bool(active_ca and platform.is_trusted(active_ca)),
        active_thumbprint=hashlib.sha1(active_ca, usedforsecurity=False)
        .hexdigest()
        .upper()
        if active_ca
        else None,
        registration=_registration_snapshot(platform),
        host_running=bool(HOST.running),
        pending=_pending_records(),
    )


def _read_optional(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _registration_snapshot(platform: ModuleType) -> object:
    addin_id = manifest.addin_id()
    if platform is macos:
        return {
            app: _read_optional(macos._manifest_path(app, addin_id))
            for app in macos.APP_PATHS
        }
    return platform.registered_manifest(addin_id)


def _restore_registration(
    platform: ModuleType, registration: object, folder: Path
) -> None:
    addin_id = manifest.addin_id()
    if platform is macos and isinstance(registration, dict):
        for app, content in registration.items():
            destination = macos._manifest_path(app, addin_id)
            if content is None:
                destination.unlink(missing_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                certs._atomic_write(destination, content)
        return
    if registration is None:
        platform.unregister(addin_id)
    else:
        platform.register(addin_id, Path(str(registration)))


def _publish_cohort(staged: certs.CertPaths, destination: certs.CertPaths) -> None:
    # Each replacement is atomic and private-key mode remains 0600. Callers hold
    # the lifecycle lock, so status and service operations see one cohort.
    for source, target in zip(
        (staged.cert, staged.key, staged.ca),
        (destination.cert, destination.key, destination.ca),
        strict=True,
    ):
        certs._atomic_write(target, source.read_bytes())


def _rollback_connect(
    primary: Exception,
    platform: ModuleType,
    folder: Path,
    snapshot: _Snapshot,
    candidate_thumbprint: str | None,
    candidate_der: bytes | None,
    candidate_trust_introduced: bool,
    host_stopped_for_change: bool,
) -> None:
    failures: list[str] = []

    old_host_still_running = snapshot.host_running and not host_stopped_for_change
    if HOST.running and not old_host_still_running:
        _attempt_rollback(failures, "stop candidate host", HOST.stop)
    safe_to_restore_files = old_host_still_running or not HOST.running
    if safe_to_restore_files:
        _attempt_rollback(
            failures,
            "restore Office registration",
            lambda: _restore_registration(platform, snapshot.registration, folder),
        )
        for name, content in snapshot.files.items():
            path = folder / name
            if content is None:
                _attempt_rollback(
                    failures, f"remove new {name}", partial(_remove_file, path)
                )
            else:
                _attempt_rollback(
                    failures,
                    f"restore {name}",
                    partial(_restore_file, path, content),
                )
    else:
        failures.append(
            "live host may still use the candidate certificate; "
            "certificate files were retained"
        )
    if candidate_trust_introduced and candidate_thumbprint:
        # If the host could not stop, keep trust too and make it discoverable.
        if safe_to_restore_files:
            _attempt_rollback(
                failures,
                "remove newly trusted candidate CA",
                lambda: _untrust_candidate(
                    platform, candidate_thumbprint, candidate_der
                ),
            )
        else:
            _attempt_rollback(
                failures,
                "record candidate trust for cleanup",
                lambda: _remember_pending(candidate_thumbprint, candidate_der),
            )
    _attempt_rollback(
        failures,
        "restore connected intent",
        lambda: settings_repo.put_setting(CONNECTED_SETTING, snapshot.connected),
    )
    if snapshot.host_running and not HOST.running and safe_to_restore_files:
        old_paths = certs.CertPaths.in_dir(folder)
        if old_paths.exist():
            _attempt_rollback(
                failures, "restart previous host", lambda: _start(old_paths)
            )
    if failures:
        note = "Office setup rollback was incomplete: " + "; ".join(failures)
        primary.add_note(note)


def _rollback_disconnect(
    primary: Exception, platform: ModuleType, folder: Path, snapshot: _Snapshot
) -> None:
    failures: list[str] = []

    for name, content in snapshot.files.items():
        path = folder / name
        if content is None:
            _attempt_rollback(
                failures,
                f"restore missing {name} state",
                partial(_remove_file, path),
            )
        else:
            _attempt_rollback(
                failures,
                f"restore {name}",
                partial(_restore_file, path, content),
            )
    _attempt_rollback(
        failures,
        "restore Office registration",
        lambda: _restore_registration(platform, snapshot.registration, folder),
    )
    if snapshot.active_ca is not None and snapshot.active_trusted:
        _attempt_rollback(
            failures,
            "restore active certificate trust",
            partial(_trust_bytes, platform, snapshot.active_ca, folder),
        )
    for item in snapshot.pending:
        der = _decode_pending(item)
        if der:
            _attempt_rollback(
                failures,
                f"restore pending trust {item['thumbprint']}",
                partial(_trust_bytes, platform, der, folder),
            )
    _attempt_rollback(
        failures,
        "restore pending cleanup record",
        lambda: _set_pending(snapshot.pending),
    )
    _attempt_rollback(
        failures,
        "restore connected intent",
        lambda: settings_repo.put_setting(CONNECTED_SETTING, snapshot.connected),
    )
    if snapshot.host_running and not HOST.running:
        paths = certs.CertPaths.in_dir(folder)
        if paths.exist():
            _attempt_rollback(failures, "restart previous host", lambda: _start(paths))
    if failures:
        primary.add_note(
            "Office disconnect rollback was incomplete: " + "; ".join(failures)
        )


def _attempt_rollback(
    failures: list[str], label: str, operation: Callable[[], Any]
) -> None:
    try:
        operation()
    except Exception as rollback_error:
        failures.append(f"{label}: {rollback_error}")
        _logger.exception("Office rollback failed during %s", label)


def _remove_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def _restore_file(path: Path, content: bytes) -> None:
    certs._atomic_write(path, content)


def _remove_trusts(platform: ModuleType, snapshot: _Snapshot) -> None:
    if (
        snapshot.active_ca is not None
        and snapshot.active_trusted
        and snapshot.active_thumbprint
    ):
        platform.untrust(snapshot.active_thumbprint)
    for item in snapshot.pending:
        thumbprint = item["thumbprint"]
        if thumbprint != snapshot.active_thumbprint:
            platform.untrust(thumbprint)
    _set_pending([])


def _trust_bytes(platform: ModuleType, der: bytes, folder: Path) -> None:
    with tempfile.TemporaryDirectory(
        prefix="office-rollback-", dir=folder
    ) as temporary:
        ca_path = Path(temporary) / "stacks-local-ca.cer"
        ca_path.write_bytes(der)
        if not platform.is_trusted(der) and not platform.trust(ca_path):
            raise OSError("The prior Office certificate trust could not be restored.")


def _trust_may_have_changed(platform: ModuleType, der: bytes) -> bool:
    try:
        return bool(platform.is_trusted(der))
    except Exception:
        # Prefer recording a possibly introduced trust for explicit cleanup.
        return True


def _untrust_candidate(
    platform: ModuleType, thumbprint: str, der: bytes | None
) -> None:
    try:
        platform.untrust(thumbprint)
    except Exception:
        _remember_pending(thumbprint, der)
        raise


def _retry_pending_trust(platform: ModuleType, active_thumbprint: str | None) -> None:
    pending = _pending_records()
    remaining: list[dict[str, str]] = []
    for record in pending:
        thumbprint = record["thumbprint"]
        if thumbprint == active_thumbprint:
            remaining.append(record)
            continue
        try:
            platform.untrust(thumbprint)
        except Exception as error:
            remaining.append(record)
            _logger.warning(
                "Office remains connected, but pending certificate trust cleanup "
                "for %s failed: %s",
                thumbprint,
                error,
            )
    try:
        _set_pending(remaining)
    except Exception as error:
        _logger.warning(
            "Could not update pending Office trust cleanup records: %s", error
        )


def _pending_records() -> list[dict[str, str]]:
    raw = settings_repo.get_setting(PENDING_TRUST_SETTING, [])
    records: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return records
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("thumbprint"), str):
            records.append(
                {
                    "thumbprint": item["thumbprint"],
                    "ca_der": str(item.get("ca_der", "")),
                }
            )
        elif isinstance(item, str):
            records.append({"thumbprint": item, "ca_der": ""})
    return records


def _decode_pending(record: dict[str, str]) -> bytes | None:
    try:
        return base64.b64decode(record.get("ca_der", ""), validate=True)
    except (ValueError, TypeError):
        return None


def _set_pending(records: list[dict[str, str]]) -> None:
    if records:
        settings_repo.put_setting(PENDING_TRUST_SETTING, records)
    else:
        settings_repo.delete_setting(PENDING_TRUST_SETTING)


def _remember_pending(thumbprint: str, der: bytes | None = None) -> None:
    records = _pending_records()
    encoded = base64.b64encode(der).decode("ascii") if der else ""
    for record in records:
        if record["thumbprint"] == thumbprint:
            if encoded:
                record["ca_der"] = encoded
            _set_pending(records)
            return
    records.append({"thumbprint": thumbprint, "ca_der": encoded})
    _set_pending(records)


def _forget_pending(thumbprint: str) -> None:
    _set_pending(
        [item for item in _pending_records() if item["thumbprint"] != thumbprint]
    )


def _trust_declined() -> OfficeSetupError:
    return OfficeSetupError(
        "The certificate trust request was declined or could not be completed. "
        "Office needs a trusted local connection. Try connecting again and "
        "approve the system's trust request. On Mac, check that the login "
        "keychain is unlocked."
    )


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
        preferences.select_course(course_id)
    try:
        _platform().launch(app, document)
    except OSError as err:
        raise OfficeSetupError(
            f"Could not start {windows.APP_NAMES[app]}: is Microsoft Office "
            f"installed? ({err})"
        ) from err
    return app
