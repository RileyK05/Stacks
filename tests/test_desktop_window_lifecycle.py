from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "src" / "frontend" / "src-tauri"


def test_library_is_the_only_window_created_at_startup() -> None:
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    windows = config["app"]["windows"]

    assert [window["label"] for window in windows] == ["main"]
    assert windows[0]["visible"] is True
    assert "targets" not in config["bundle"]


def test_desktop_can_activate_a_recovered_backup_with_restart() -> None:
    """B-14: the shell exposes an activation command that stops the
    backend, runs the one-shot swap, and restarts the backend through a
    swappable cell (managed state cannot be replaced in place)."""
    library = (TAURI / "src" / "library.rs").read_text(encoding="utf-8")
    shell = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    backend = (TAURI / "src" / "backend.rs").read_text(encoding="utf-8")

    assert "pub async fn activate_backup" in library
    assert "backend.shutdown()" in library
    assert "Backend::spawn(app)" in library
    assert "BackendCell" in library and "BackendCell" in shell
    assert "library::activate_backup" in shell
    assert "activation_command" in backend
    assert '"--activate"' in backend
    assert "app.manage(backend)" not in shell, (
        "the backend lives in a swappable cell so activation can replace it"
    )


def test_companion_is_created_on_demand_as_a_normal_window() -> None:
    companion = (TAURI / "src" / "companion.rs").read_text(encoding="utf-8")
    shell = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")

    # Async, or building the webview on the main thread deadlocks WebView2:
    # the companion opened white and a second click froze the app.
    assert "pub async fn show_companion" in companion
    assert "WebviewWindowBuilder::new" in companion
    assert ".resizable(true)" in companion
    assert ".decorations(true)" in companion
    assert "PhysicalPosition" not in companion
    assert 'get_webview_window("main")' in shell
    assert "companion::initialize" not in shell
