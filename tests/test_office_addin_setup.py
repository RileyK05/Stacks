"""Connecting Stacks to Office: certificate, trust, registration, hosting,
and opening documents (src/backend/office_addin/).

The Windows side (trust store, Office's add-in registry key, launching
apps) is replaced by a recording fake, so the suite never touches the real
machine; one test serves the real pane over real TLS on a free port.
"""

from __future__ import annotations

import datetime as dt
import socket
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from src.backend.office_addin import certs, manifest, preferences, service, windows


@dataclass
class FakeWindows:
    trusted: set[bytes] = field(default_factory=set)
    accept_trust: bool = True
    registry: dict[str, str] = field(default_factory=dict)
    launched: list[tuple[str, Path | None]] = field(default_factory=list)
    trust_prompts: int = 0
    installed: bool = True

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(windows, "SUPPORTED", True)
        monkeypatch.setattr(windows, "installed_apps", self.installed_apps)
        monkeypatch.setattr(windows, "is_trusted", lambda der: der in self.trusted)
        monkeypatch.setattr(windows, "trust", self.trust)
        monkeypatch.setattr(windows, "untrust", self.untrust)
        monkeypatch.setattr(windows, "register", self.register)
        monkeypatch.setattr(windows, "unregister", self.registry.pop)
        monkeypatch.setattr(windows, "registered_manifest", self.registry.get)
        monkeypatch.setattr(windows, "launch", self.launch)

    def installed_apps(self) -> list[windows.OfficeApp]:
        return ["word", "excel", "powerpoint"] if self.installed else []

    def trust(self, ca_path: Path) -> bool:
        self.trust_prompts += 1
        if self.accept_trust:
            self.trusted.add(ca_path.read_bytes())
        return self.accept_trust

    def untrust(self, thumbprint: str) -> None:
        self.trusted = {
            der
            for der in self.trusted
            if certs.hashlib.sha1(der, usedforsecurity=False).hexdigest().upper()
            != thumbprint
        }

    def register(self, addin_id: str, path: Path) -> None:
        self.registry[addin_id] = str(path)

    def launch(self, app: windows.OfficeApp, document: Path | None) -> None:
        if not self.installed:
            raise OSError("not installed")
        self.launched.append((app, document))


class FakeHost:
    def __init__(self) -> None:
        self.running = False
        self.starts = 0
        self.busy = False

    def start(self, app: Any, *, port: int, cert: Path, key: Path) -> None:
        from src.backend.office_addin.host import PortInUseError

        if self.busy:
            raise PortInUseError(f"port {port} is already in use")
        assert cert.is_file() and key.is_file()
        self.running = True
        self.starts += 1

    def stop(self) -> None:
        self.running = False


@pytest.fixture
def fake_windows(monkeypatch: pytest.MonkeyPatch) -> FakeWindows:
    fake = FakeWindows()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def fake_host(monkeypatch: pytest.MonkeyPatch) -> FakeHost:
    host = FakeHost()
    monkeypatch.setattr(service, "HOST", host)
    return host


def _addin_dir(data_dir: Path) -> Path:
    return data_dir / "office-addin"


# --- certificate ------------------------------------------------------------


def test_issued_certificate_serves_localhost_and_keeps_no_ca_key(
    tmp_path: Path,
) -> None:
    paths = certs.issue(tmp_path / "certs")
    assert certs.is_current(paths)
    assert sorted(p.name for p in (tmp_path / "certs").iterdir()) == sorted(
        [paths.cert.name, paths.key.name, paths.ca.name]
    )
    leaf, chained_ca = x509.load_pem_x509_certificates(paths.cert.read_bytes())
    ca = x509.load_der_x509_certificate(paths.ca.read_bytes())
    assert chained_ca == ca
    leaf.verify_directly_issued_by(ca)
    names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert names.value.get_values_for_type(x509.DNSName) == ["localhost"]
    assert {str(ip) for ip in names.value.get_values_for_type(x509.IPAddress)} == {
        "127.0.0.1",
        "::1",
    }
    # The only private key on disk is the server's, not the CA's.
    key = serialization.load_pem_private_key(paths.key.read_bytes(), password=None)
    assert key.public_key() == leaf.public_key()
    assert key.public_key() != ca.public_key()
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca


def test_certificate_is_renewed_before_it_expires(tmp_path: Path) -> None:
    paths = certs.issue(tmp_path / "certs")
    soon = dt.datetime.now(dt.UTC) + certs.LIFETIME - dt.timedelta(days=10)
    assert not certs.is_current(paths, now=soon)


def test_certificate_from_another_ca_is_not_current(tmp_path: Path) -> None:
    paths = certs.issue(tmp_path / "a")
    other = certs.issue(tmp_path / "b")
    paths.ca.write_bytes(other.ca.read_bytes())
    assert not certs.is_current(paths)


# --- connect / disconnect ---------------------------------------------------


def test_connect_does_every_step_and_reports_ready(
    fake_windows: FakeWindows, fake_host: FakeHost, _isolated_data_dir: Path
) -> None:
    before = service.status()
    assert not before.connected and not before.ready

    status = service.connect()

    assert status.ready, status.problems
    assert status.certificate_trusted and status.registered and status.running
    assert status.url == "https://localhost:47831"
    registered = Path(fake_windows.registry[manifest.addin_id()])
    assert registered == _addin_dir(_isolated_data_dir) / "manifest.xml"
    assert "https://localhost:47831/taskpane.html" in registered.read_text(
        encoding="utf-8"
    )
    assert fake_windows.trust_prompts == 1


def test_connect_again_does_not_prompt_again(
    fake_windows: FakeWindows, fake_host: FakeHost
) -> None:
    service.connect()
    service.connect()
    assert fake_windows.trust_prompts == 1


def test_declined_trust_stops_before_registering(
    fake_windows: FakeWindows, fake_host: FakeHost
) -> None:
    fake_windows.accept_trust = False
    with pytest.raises(service.OfficeSetupError, match="declined"):
        service.connect()
    assert fake_windows.registry == {}
    assert not fake_host.running
    assert not service.status().connected


def test_connect_is_windows_only(
    monkeypatch: pytest.MonkeyPatch, fake_host: FakeHost
) -> None:
    monkeypatch.setattr(windows, "SUPPORTED", False)
    with pytest.raises(service.OfficeSetupError, match="Windows"):
        service.connect()


def test_busy_port_is_reported(fake_windows: FakeWindows, fake_host: FakeHost) -> None:
    fake_host.busy = True
    with pytest.raises(service.OfficeSetupError, match="in use"):
        service.connect()


def test_status_notices_a_removed_registration(
    fake_windows: FakeWindows, fake_host: FakeHost
) -> None:
    service.connect()
    fake_windows.registry.clear()
    status = service.status()
    assert status.connected and not status.ready
    assert any("registered" in problem for problem in status.problems)


def test_disconnect_undoes_everything(
    fake_windows: FakeWindows, fake_host: FakeHost, _isolated_data_dir: Path
) -> None:
    service.connect()
    status = service.disconnect()
    assert not status.connected and not status.registered and not status.running
    assert fake_windows.registry == {}
    assert fake_windows.trusted == set()
    assert list(_addin_dir(_isolated_data_dir).iterdir()) == []


def test_startup_serves_a_connected_addin_without_prompting(
    fake_windows: FakeWindows, fake_host: FakeHost
) -> None:
    service.start_if_connected()
    assert fake_host.starts == 0

    service.connect()
    fake_host.stop()
    prompts = fake_windows.trust_prompts
    service.start_if_connected()
    assert fake_host.running
    assert fake_windows.trust_prompts == prompts


def test_startup_waits_for_the_user_when_trust_was_removed(
    fake_windows: FakeWindows, fake_host: FakeHost
) -> None:
    service.connect()
    fake_host.stop()
    fake_windows.trusted.clear()
    service.start_if_connected()
    assert not fake_host.running
    assert fake_windows.trust_prompts == 1


# --- opening documents ------------------------------------------------------


def test_open_new_document_remembers_the_course(
    fake_windows: FakeWindows, fake_host: FakeHost
) -> None:
    from src.backend.common import courses_repo

    course = courses_repo.create_course("Econ 301")
    assert service.open_document("excel", None, course.course_id) == "excel"
    assert fake_windows.launched == [("excel", None)]
    assert preferences.last_course() == str(course.course_id)


def test_open_file_picks_the_app_from_its_extension(
    fake_windows: FakeWindows, fake_host: FakeHost, tmp_path: Path
) -> None:
    deck = tmp_path / "Lecture 3.PPTX"
    deck.write_bytes(b"pptx")
    assert service.open_document("word", deck, None) == "powerpoint"
    assert fake_windows.launched == [("powerpoint", deck)]


def test_open_refuses_other_files_and_missing_ones(
    fake_windows: FakeWindows, fake_host: FakeHost, tmp_path: Path
) -> None:
    script = tmp_path / "run.bat"
    script.write_text("echo hi")
    with pytest.raises(service.OfficeSetupError, match="not a Word"):
        service.open_document(None, script, None)
    with pytest.raises(service.OfficeSetupError, match="does not exist"):
        service.open_document(None, tmp_path / "gone.docx", None)
    assert fake_windows.launched == []


def test_open_without_office_says_so(
    fake_windows: FakeWindows, fake_host: FakeHost
) -> None:
    fake_windows.installed = False
    with pytest.raises(service.OfficeSetupError, match="Word"):
        service.open_document("word", None, None)


# --- desktop API ------------------------------------------------------------


def test_api_status_connect_and_open(
    client: TestClient, fake_windows: FakeWindows, fake_host: FakeHost
) -> None:
    status = client.get("/office/status").json()
    assert status["connected"] is False
    assert status["apps"] == ["word", "excel", "powerpoint"]

    course = client.post("/courses", json={"name": "Econ 301"}).json()
    opened = client.post(
        "/office/open", json={"app": "powerpoint", "course_id": course["course_id"]}
    )
    assert opened.status_code == 200, opened.text
    assert opened.json() == {"app": "powerpoint", "first_time": True}
    assert client.get("/office/status").json()["ready"] is True

    again = client.post("/office/open", json={"app": "word"})
    assert again.json() == {"app": "word", "first_time": False}
    assert fake_windows.trust_prompts == 1

    status = client.post("/office/disconnect").json()
    assert status["connected"] is False


def test_api_reports_setup_problems_as_conflicts(
    client: TestClient, fake_windows: FakeWindows, fake_host: FakeHost
) -> None:
    fake_windows.accept_trust = False
    response = client.post("/office/connect")
    assert response.status_code == 409
    assert "declined" in response.json()["detail"]
    missing = client.post(
        "/office/open",
        json={"app": "word", "course_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing.status_code == 404


def test_api_rejects_unknown_apps(client: TestClient) -> None:
    response = client.post("/office/open", json={"app": "outlook"})
    assert response.status_code == 422


# --- the real host ----------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_host_serves_pane_and_bridge_over_trusted_tls(tmp_path: Path) -> None:
    from src.backend.office_addin.app import create_office_host
    from src.backend.office_addin.host import AddinHost, PortInUseError

    paths = certs.issue(tmp_path / "certs")
    ca = x509.load_der_x509_certificate(paths.ca.read_bytes())
    context = ssl.create_default_context(
        cadata=ca.public_bytes(serialization.Encoding.PEM).decode()
    )
    port = _free_port()
    host = AddinHost()
    host.start(create_office_host(), port=port, cert=paths.cert, key=paths.key)
    try:
        base = f"https://localhost:{port}"
        deadline = time.monotonic() + 10
        while True:
            try:
                pane = httpx.get(f"{base}/taskpane.html", verify=context)
                break
            except httpx.ConnectError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        assert pane.status_code == 200
        assert "taskpane.js" in pane.text
        assert pane.headers["cache-control"] == "no-store"
        health = httpx.get(f"{base}/office/health", verify=context)
        assert health.json()["app"] == "Stacks"
        with pytest.raises(PortInUseError):
            AddinHost().start(
                create_office_host(), port=port, cert=paths.cert, key=paths.key
            )
    finally:
        host.stop()
    assert not host.running
