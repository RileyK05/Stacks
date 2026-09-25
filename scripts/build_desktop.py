"""Build the Stacks installer.

    .venv/Scripts/python -m scripts.build_desktop [--skip-backend]

1. bundles the Python backend (src/backend/serve.py), its configs and SQL
   into one folder with PyInstaller, placed at src/frontend/src-tauri/backend/;
2. runs `tauri build`, which builds the SPA, compiles the shell, and packs
   both plus the backend folder into an installer (NSIS on Windows) under
   src/frontend/src-tauri/target/release/bundle/.

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


def build_backend() -> Path:
    common = ROOT / "src" / "backend" / "common"
    datas = [
        (ROOT / "configs", "configs"),
        (common / "migrations", "src/backend/common/migrations"),
        (common / "queries", "src/backend/common/queries"),
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
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(work / "dist" / BACKEND_NAME, target)
    return target


def build_installer() -> list[Path]:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    subprocess.run(
        [npm, "run", "tauri", "--", "build", "--config", str(BUNDLE_CONFIG)],
        cwd=FRONTEND,
        check=True,
    )
    bundle = SHELL / "target" / "release" / "bundle"
    return sorted(
        p
        for p in bundle.rglob("*")
        if p.suffix in {".exe", ".msi", ".dmg", ".deb", ".AppImage"}
    )


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
