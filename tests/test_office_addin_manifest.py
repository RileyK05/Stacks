"""The Stacks Office add-in manifest and its referenced files.

Plan-notebook.md, "Bring Stacks to Office": one task-pane add-in for Word,
Excel and PowerPoint. A malformed manifest silently fails to load, which is
painful to debug, so this pins the structural requirements, that every URL
the manifest names exists in the add-in directory, and that the copy Stacks
registers is rendered for this machine's port and version.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from lxml import etree
from src.backend.office_addin import manifest

ADDIN = manifest.ADDIN_DIR
MANIFEST = ADDIN / "manifest.xml"

APP_NS = "http://schemas.microsoft.com/office/appforoffice/1.1"
BT_NS = "http://schemas.microsoft.com/office/officeappbasictypes/1.0"
OV_NS = "http://schemas.microsoft.com/office/taskpaneappversionoverrides"


def _tree() -> etree._ElementTree:
    return etree.parse(str(MANIFEST))


def test_manifest_is_well_formed_office_app() -> None:
    root = _tree().getroot()
    assert etree.QName(root).localname == "OfficeApp"
    assert etree.QName(root).namespace == APP_NS
    assert root.get("{http://www.w3.org/2001/XMLSchema-instance}type") == "TaskPaneApp"


def test_manifest_declares_powerpoint_word_and_excel() -> None:
    root = _tree().getroot()
    hosts = [
        host.get("Name")
        for host in root.findall(f"{{{APP_NS}}}Hosts/{{{APP_NS}}}Host")
    ]
    assert hosts == ["Presentation", "Document", "Workbook"]
    override = root.find(f"{{{OV_NS}}}VersionOverrides")
    assert override is not None
    ribbon_hosts = [
        host.get("{http://www.w3.org/2001/XMLSchema-instance}type")
        for host in override.findall(f"{{{OV_NS}}}Hosts/{{{OV_NS}}}Host")
    ]
    assert ribbon_hosts == ["Presentation", "Document", "Workbook"]


def test_manifest_requires_read_write_document() -> None:
    root = _tree().getroot()
    assert root.findtext(f"{{{APP_NS}}}Permissions") == "ReadWriteDocument"


def test_manifest_has_stable_id_version_provider() -> None:
    root = _tree().getroot()
    identity = root.findtext(f"{{{APP_NS}}}Id")
    assert identity and len(identity) == 36
    assert root.findtext(f"{{{APP_NS}}}ProviderName") == "Stacks"
    assert root.findtext(f"{{{APP_NS}}}Version")


def test_every_manifest_url_file_exists_locally() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    paths: set[str] = set()
    prefix = f"{manifest.TEMPLATE_ORIGIN}/"
    for token in text.split('"'):
        if token.startswith(prefix):
            path = token[len(prefix) :]
            if path and "." in path.rsplit("/", 1)[-1]:
                paths.add(path)
    assert paths, "manifest references no add-in files"
    for path in paths:
        assert (ADDIN / path).is_file(), f"manifest references missing file: {path}"


def test_version_overrides_reference_the_taskpane_and_commands() -> None:
    root = _tree().getroot()
    override = root.find(f"{{{OV_NS}}}VersionOverrides")
    assert override is not None
    assert etree.QName(override).namespace == OV_NS
    urls = {
        url.get("id"): url.get("DefaultValue")
        for url in override.findall(
            f"{{{OV_NS}}}Resources/{{{BT_NS}}}Urls/{{{BT_NS}}}Url"
        )
    }
    assert urls["Taskpane.Url"].endswith("/taskpane.html")
    assert urls["Commands.Url"].endswith("/commands.html")


def test_manifest_source_location_points_at_the_taskpane() -> None:
    root = _tree().getroot()
    node = root.find(f"{{{APP_NS}}}DefaultSettings/{{{APP_NS}}}SourceLocation")
    assert node is not None
    source = node.get("DefaultValue")
    assert source and urlparse(source).path.endswith("/taskpane.html")


def test_every_localhost_url_uses_the_template_origin() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    urls = re.findall(r"https?://localhost[^\"<\s]*", text)
    assert urls
    for url in urls:
        assert url.startswith(manifest.TEMPLATE_ORIGIN), url


def test_rendered_manifest_uses_this_port_and_app_version(tmp_path: Path) -> None:
    path = manifest.write(tmp_path, 51000, "1.4.2")
    text = path.read_text(encoding="utf-8")
    assert manifest.TEMPLATE_ORIGIN not in text
    assert "https://localhost:51000/taskpane.html" in text
    root = etree.parse(str(path)).getroot()
    assert root.findtext(f"{{{APP_NS}}}Version") == "1.1.4.2"
    assert root.findtext(f"{{{APP_NS}}}Id") == manifest.addin_id()


def test_office_version_is_four_parts_at_least_one_and_grows() -> None:
    assert manifest.office_version("0.2.0") == "1.0.2.0"
    assert manifest.office_version("1.2.3-beta") == "1.1.2.3"
    assert manifest.office_version("2") == "1.2.0.0"

    def key(version: str) -> tuple[int, ...]:
        return tuple(int(part) for part in manifest.office_version(version).split("."))

    releases = ["0.2.0", "0.2.1", "0.10.0", "1.0.0", "1.0.5", "2.1.0"]
    assert [key(v) for v in releases] == sorted(key(v) for v in releases)
