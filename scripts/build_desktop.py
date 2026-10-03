"""Build the Stacks installer.

    .venv/Scripts/python -m scripts.build_desktop [--skip-backend]

1. bundles the Python backend (src/backend/serve.py), its configs, SQL and
   the Office add-in's pane files into one folder with PyInstaller, placed
   at src/frontend/src-tauri/backend/;
2. runs `tauri build`, which builds the SPA, compiles the shell, and packs
   both plus the backend folder into this OS's installers (BUNDLES) under
   src/frontend/src-tauri/target/release/bundle/.

PyInstaller cannot cross-compile, so each OS builds its own installers.

Needs the `desktop` extra (PyInstaller), Node.js, and a Rust toolchain.
Model files and the llama.cpp runtime are NOT bundled: the user downloads
them from Settings into their data folder, checksummed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "src" / "frontend"
SHELL = FRONTEND / "src-tauri"
BACKEND_NAME = "stacks-backend"
BUNDLE_CONFIG = SHELL / "tauri.bundle.conf.json"

# Tauri bundle targets per OS, and the installer file each one produces.
# macOS and Linux are experimental: built by CI, not yet tested by hand.
BUNDLES: dict[str, dict[str, str]] = {
    "win32": {"nsis": ".exe"},
    "darwin": {"dmg": ".dmg"},
    "linux": {"appimage": ".AppImage", "deb": ".deb"},
}


def _bundles() -> dict[str, str]:
    try:
        return BUNDLES[sys.platform]
    except KeyError:
        raise SystemExit(f"no installer defined for {sys.platform}") from None


def build_backend() -> Path:
    common = ROOT / "src" / "backend" / "common"
    datas = [
        (ROOT / "configs", "configs"),
        (
            ROOT / "src/backend/office_reader/capture_windows.ps1",
            "src/backend/office_reader",
        ),
        (common / "migrations", "src/backend/common/migrations"),
        (common / "queries", "src/backend/common/queries"),
        # The Office task pane the backend serves (src/backend/office_addin).
        (ROOT / "src" / "office-addin" / "public", "src/office-addin/public"),
    ]
    work = ROOT / "build" / "pyinstaller"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        # A console program: the shell talks to it over stdin/stdout and
        # starts it without a window (CREATE_NO_WINDOW).
        "--console",
        "--name",
        BACKEND_NAME,
        "--distpath",
        str(work / "dist"),
        "--workpath",
        str(work),
        "--specpath",
        str(ROOT / "build"),
        "--paths",
        str(ROOT),
        # uvicorn picks its implementations at runtime.
        "--collect-submodules",
        "uvicorn",
        # In-process encoders run on ONNX Runtime; the torch stack is only a
        # dev-time parity reference and must never be bundled.
        "--collect-all",
        "onnxruntime",
        "--collect-submodules",
        "tokenizers",
        # Course-graph clustering (backend/graph/clustering.py) imports
        # Artifact export: Word and PowerPoint build from template files
        # shipped inside their packages.
        "--collect-data",
        "docx",
        "--collect-data",
        "pptx",
        "--exclude-module",
        "torch",
        "--exclude-module",
        "sentence_transformers",
        "--exclude-module",
        "transformers",
    ]
    for source, target in datas:
        command += ["--add-data", f"{source}{os.pathsep}{target}"]
    command.append(str(ROOT / "src" / "backend" / "serve.py"))
    subprocess.run(command, cwd=ROOT, check=True)

    target = SHELL / "backend"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(work / "dist" / BACKEND_NAME, target)
    return target


def build_installer() -> list[Path]:
    """Run `tauri build` for this OS; returns one installer per bundle."""
    bundles = _bundles()
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    bundle = SHELL / "target" / "release" / "bundle"
    if bundle.exists():
        shutil.rmtree(bundle)
    subprocess.run(
        [
            npm,
            "run",
            "tauri",
            "--",
            "build",
            "--config",
            str(BUNDLE_CONFIG),
            "--bundles",
            ",".join(bundles),
            "--",
            "--locked",
        ],
        cwd=FRONTEND,
        check=True,
    )
    installers = []
    for suffix in bundles.values():
        found = sorted(bundle.rglob(f"*{suffix}"))
        if len(found) != 1:
            raise SystemExit(
                f"Tauri must produce exactly one {suffix} installer; found {len(found)}"
            )
        installers += found
    return installers


def _size(path: Path) -> str:
    total = (
        sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        if path.is_dir()
        else path.stat().st_size
    )
    return f"{total / 1e6:.0f} MB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_desktop")
    parser.add_argument(
        "--skip-backend",
        action="store_true",
        help="reuse the backend already in src-tauri/backend/",
    )
    args = parser.parse_args(argv)
    if args.skip_backend:
        backend = SHELL / "backend"
        if (
            not (backend / f"{BACKEND_NAME}.exe").exists()
            and not (backend / BACKEND_NAME).exists()
        ):
            raise SystemExit(
                "no backend in src-tauri/backend/; build without --skip-backend"
            )
    else:
        backend = build_backend()
    print(f"backend: {backend} ({_size(backend)})")
    for installer in build_installer():
        print(f"installer: {installer} ({_size(installer)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
