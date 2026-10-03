from importlib import import_module
from pathlib import Path

from src.backend.common.config import PROJECT_ROOT
from src.backend.main import create_api, create_app
from src.backend.office_addin.app import create_office_host


def test_backend_modules_resolve_to_current_source() -> None:
    for path in sorted((PROJECT_ROOT / "src" / "backend").rglob("*.py")):
        parts = path.relative_to(PROJECT_ROOT).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        module = import_module(name)
        assert module.__file__ is not None, name
        assert Path(module.__file__).resolve() == path.resolve(), name


def test_app_factories_mount_current_routes_without_starting_services() -> None:
    api = create_api()
    assert "/courses/{course_id}/retrieval-settings" in api.openapi()["paths"]
    assert (
        "/courses/{course_id}/practice/{suite_id}/questions/{index}/help"
        in api.openapi()["paths"]
    )
    assert any(getattr(route, "path", None) == "/api" for route in create_app().routes)
    assert any(
        getattr(route, "path", None) == "/office"
        for route in create_office_host().routes
    )
