"""Build the desktop app (plan §11, Phase 6).

    .venv/Scripts/python -m scripts.build_desktop

1. builds the SPA (`npm run build` in src/frontend);
2. bundles the backend, its configs and SQL, and the SPA into
   `dist/CourseAssistant/` with PyInstaller (one folder, no console
   window). Run `dist/CourseAssistant/CourseAssistant.exe` (Windows) or
   the equivalent binary elsewhere.

Model files and the llama.cpp runtime are NOT bundled: they download on
first use into the per-user data directory, checksummed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "src" / "frontend"
NAME = "CourseAssistant"


def build_frontend() -> Path:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)
    build = FRONTEND / "build"
    if not (build / "200.html").is_file():
        raise SystemExit("frontend build is missing 200.html")
    return build


def build_app(frontend_build: Path) -> Path:
    sep = os.pathsep
    common = ROOT / "src" / "backend" / "common"
    datas = [
        (ROOT / "configs", "configs"),
        (common / "migrations", "src/backend/common/migrations"),
        (common / "queries", "src/backend/common/queries"),
        (frontend_build, "frontend"),
    ]
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        NAME,
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build"),
        "--paths",
        str(ROOT),
        # uvicorn and pywebview pick implementations at runtime.
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "webview",
        "--collect-data",
        "webview",
        # The in-process encoders (embeddings, reranker) until Phase 5
        # replaces them with ONNX Runtime.
        "--collect-all",
        "sentence_transformers",
        "--copy-metadata",
        "torch",
        "--copy-metadata",
        "tqdm",
        "--copy-metadata",
        "regex",
        "--copy-metadata",
        "safetensors",
        "--copy-metadata",
        "tokenizers",
        "--copy-metadata",
        "huggingface-hub",
        "--copy-metadata",
        "transformers",
    ]
    for source, target in datas:
        command += ["--add-data", f"{source}{sep}{target}"]
    command.append(str(ROOT / "src" / "backend" / "desktop.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    return ROOT / "dist" / NAME


def main() -> int:
    shutil.rmtree(ROOT / "dist" / NAME, ignore_errors=True)
    app = build_app(build_frontend())
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print(f"built {app} ({size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
