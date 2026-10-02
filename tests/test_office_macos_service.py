from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.backend.office_addin import certs, live, macos, manifest, service


@dataclass
class FakeMac:
    installed: tuple[str, ...] = ("word", "excel", "powerpoint")
    trusted: set[bytes] = field(default_factory=set)
    registered: dict[str, bytes] = field(default_factory=dict)
    launched: list[tuple[str, Path | None]] = field(default_factory=list)
    trust_prompts: int = 0
    untrusted: list[str] = field(default_factory=list)

    SUPPORTED = True

    def installed_apps(self) -> list[str]:
        return list(self.installed)

    def is_trusted(self, ca_der: bytes) -> bool:
        return ca_der in self.trusted

    def trust(self, ca_path: Path) -> bool:
        self.trust_prompts += 1
        self.trusted.add(ca_path.read_bytes())
        return True

    def untrust(self, thumbprint: str) -> None:
        self.untrusted.append(thumbprint)
        self.trusted = {
            certificate
            for certificate in self.trusted
            if hashlib.sha1(certificate, usedforsecurity=False).hexdigest().upper()
            != thumbprint
        }

    def register(self, addin_id: str, manifest_path: Path) -> None:
        content = manifest_path.read_bytes()
        for app in self.installed:
            self.registered[app] = content

    def unregister(self, addin_id: str) -> None:
        self.registered.clear()

    def is_registered(self, addin_id: str, manifest_path: Path) -> bool:
        if not self.installed or not manifest_path.is_file():
            return False
        expected = manifest_path.read_bytes()
        return all(self.registered.get(app) == expected for app in self.installed)

    def launch(self, app: str, document: Path | None = None) -> None:
        if app not in self.installed:
            raise OSError(f"Microsoft {app} is not installed")
        self.launched.append((app, document))


class FakeHost:
    def __init__(self) -> None:
        self.running = False
        self.starts = 0
        self.stops = 0

    def start(self, app: Any, *, port: int, cert: Path, key: Path) -> None:
        assert cert.is_file() and key.is_file()
        self.running = True
        self.starts += 1

    def stop(self) -> None:
        self.running = False
        self.stops += 1


class FakeBroker:
    def __init__(self) -> None:
        self.connections = ["active fake connection"]
        self.clears = 0

    def clear(self) -> None:
        self.connections.clear()
        self.clears += 1


@pytest.fixture
def mac_service(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FakeMac, FakeHost, FakeBroker]:
    platform = FakeMac()
    host = FakeHost()
    broker = FakeBroker()
    monkeypatch.setattr(service, "_platform", lambda: platform)
    monkeypatch.setattr(
        service,
        "_registered",
        lambda path: platform.is_registered(manifest.addin_id(), path),
    )
    monkeypatch.setattr(service, "HOST", host)
    monkeypatch.setattr(live, "BROKER", broker)
    return platform, host, broker


def test_mac_connect_is_ready_and_repeat_connection_does_not_prompt_again(
    mac_service: tuple[FakeMac, FakeHost, FakeBroker], _isolated_data_dir: Path
) -> None:
    platform, host, _broker = mac_service
    before = service.status()
    assert before.supported and not before.connected and not before.ready

    connected = service.connect()

    assert connected.ready, connected.problems
    assert connected.apps == ["word", "excel", "powerpoint"]
    assert connected.certificate_trusted and connected.registered and connected.running
    assert platform.trust_prompts == 1
    assert host.running and host.starts == 1
    paths = certs.CertPaths.in_dir(_isolated_data_dir / "office-addin")
    assert certs.is_current(paths)
    assert platform.trusted == {certs.ca_der(paths)}
    expected_manifest = (
        _isolated_data_dir / "office-addin" / "manifest.xml"
    ).read_bytes()
    assert set(platform.registered) == set(platform.installed)
    assert all(content == expected_manifest for content in platform.registered.values())

    repeated = service.connect()
    assert repeated.ready, repeated.problems
    assert platform.trust_prompts == 1


def test_mac_disconnect_stops_clears_broker_unregisters_untrusts_and_removes_files(
    mac_service: tuple[FakeMac, FakeHost, FakeBroker], _isolated_data_dir: Path
) -> None:
    platform, host, broker = mac_service
    service.connect()
    paths = certs.CertPaths.in_dir(_isolated_data_dir / "office-addin")
    expected_thumbprint = certs.ca_thumbprint(paths)

    status = service.disconnect()

    assert not status.connected and not status.running and not status.registered
    assert host.stops == 1 and not host.running
    assert broker.clears == 1 and broker.connections == []
    assert platform.registered == {}
    assert platform.trusted == set()
    assert platform.untrusted == [expected_thumbprint]
    assert list((_isolated_data_dir / "office-addin").iterdir()) == []


def test_mac_startup_repairs_manifest_and_host_without_prompting(
    mac_service: tuple[FakeMac, FakeHost, FakeBroker]
) -> None:
    platform, host, _broker = mac_service
    service.connect()
    prompt_count = platform.trust_prompts
    host.stop()
    platform.registered.clear()

    service.start_if_connected()

    assert host.running and host.starts == 2
    assert service.status().ready
    assert platform.registered
    assert platform.trust_prompts == prompt_count

    host.stop()
    platform.trusted.clear()
    service.start_if_connected()
    assert not host.running
    assert platform.trust_prompts == prompt_count


def test_open_document_launches_mac_office_and_remembers_course(
    mac_service: tuple[FakeMac, FakeHost, FakeBroker]
) -> None:
    from src.backend.common import courses_repo

    platform, _host, _broker = mac_service
    course = courses_repo.create_course("Mac Office launch")

    assert service.open_document("excel", None, course.course_id) == "excel"

    assert platform.launched == [("excel", None)]
    assert service.last_course() == str(course.course_id)


def test_registered_routes_to_macos_using_a_local_platform_stub(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(service, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(
        macos,
        "is_registered",
        lambda addin_id, path: calls.append((addin_id, path)) or True,
    )
    manifest_path = tmp_path / "manifest.xml"

    assert service._registered(manifest_path)
    assert calls == [(manifest.addin_id(), manifest_path)]
