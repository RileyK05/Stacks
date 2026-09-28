# Stacks

[![CI](https://github.com/RileyK05/Stacks/actions/workflows/ci.yml/badge.svg)](https://github.com/RileyK05/Stacks/actions/workflows/ci.yml)

Stacks is a local-first course and memory workspace. Add syllabi,
readings, slides, and notes, then ask questions grounded in those sources.
Every substantive answer shows the passages it used.

- **One course and memory library.** Stacks opens to the central place for your
  courses, source-grounded knowledge, saved work, model setup, and the evolving
  course-memory records that stay under your control.
- **An optional companion beside your work.** Press **Open companion** when you
  want a separate movable, resizable window beside a browser, PDF, or another
  app. Paste what you are looking at, then explain, find, quiz, summarize, or
  ask a follow-up without leaving the current task.
- **Local by default.** A small open model runs through a supervised local
  llama.cpp server. Course files and history stay in the user's data folder.
- **Your choice of model.** Settings can use another local model, OpenRouter,
  OpenAI, or an OpenAI-compatible endpoint. Cloud use is opt-in and keys are
  stored in the OS keychain.
- **Answers you can check.** Retrieval combines keyword search, the course table
  of contents, concept links, and embeddings, then reranks the result. Answers
  cite the material they draw on and refuse when the material does not cover a
  question.
- **An Office bridge.** The optional Windows add-in reads a live selection in
  Word, Excel, or PowerPoint and can insert a grounded answer through Office.js.
  Office remains responsible for rendering and saving the document.

The companion, cited course Q&A, course library, and Office bridge are
implemented. The student model for diagnostics, mastery, and "what to study
next" remains planned; see [docs/project.md](docs/project.md).

## Install

**[Download the latest release](https://github.com/RileyK05/Stacks/releases/latest)**
and pick the file for your computer under *Assets*. None of the installers is
code-signed yet, so your OS warns before the first launch.

- **Windows:** `Stacks_x.y.z_x64-setup.exe`. It installs for the current user
  without administrator rights. If SmartScreen warns, choose *More info*, then
  *Run anyway*.
- **macOS (Apple Silicon):** `Stacks_x.y.z_aarch64.dmg`. Drag
  Stacks into Applications and open it. When macOS says it can't verify the
  app, open *System Settings → Privacy & Security*, scroll down, and click
  *Open Anyway*. You only do this once.
- **Linux (x64):** `Stacks_x.y.z_amd64.AppImage` runs anywhere
  (`chmod +x` it, then run it); `Stacks_x.y.z_amd64.deb` installs on Debian and
  Ubuntu.

The library, optional companion, packaged backend, and local model runtime are
built natively for all three targets. The Microsoft Office bridge remains a
Windows-only optional integration; the rest of Stacks does not depend on it.

Before the first question, download a local model in Settings or choose a cloud
provider. The default local model is about 1.6 GB; downloads and the llama.cpp
runtime are checksummed.

**Requirements:** Windows 10 or 11, macOS 11+ on Apple Silicon, or 64-bit
Linux (Ubuntu 22.04 or newer). 8 GB RAM minimum, 16 GB recommended.

## Build from source

Install Python 3.12+, Node.js 22+, Rust, and your platform's Tauri prerequisites:
MSVC build tools on Windows, Xcode command-line tools on macOS, or WebKitGTK and
the standard build tools on Linux.

```text
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[desktop,dev]"  # Windows
.venv/bin/python -m pip install -e ".[desktop,dev]"      # macOS/Linux
cd src/frontend
npm install
cd ../..
```

Run the app in development:

```text
cd src/frontend
npm run desktop
```

Build the native installer for the current OS:

```text
.venv/Scripts/python -m scripts.build_desktop
.venv/bin/python -m scripts.build_desktop
```

Installers are written below `src/frontend/src-tauri/target/release/bundle/`:
NSIS on Windows, DMG on Apple Silicon macOS, and AppImage plus deb on x64 Linux.

## Development

```powershell
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy src
cd src/frontend
npm run check
npm run build
cd src-tauri
cargo clippy --all-targets --locked -- -D warnings
```

The Office pane also has its own checks:

```powershell
cd src/office-addin
npm run check
npm test
```

GitHub Actions runs these gates on every push and pull request. A release uses
`scripts.set_version`, a matching `vX.Y.Z` tag, and two workflows: Release
(Windows) and Release (macOS, Linux). Each builds its installers on its own OS
and attaches them to one draft release for review.

## Documentation

- [docs/project.md](docs/project.md): product scope and milestones
- [docs/system.md](docs/system.md): current local architecture
- [docs/plan-notebook.md](docs/plan-notebook.md): release plan and handoff
- [docs/docket.md](docs/docket.md): triaged bugs and release follow-up
- [docs/notes.md](docs/notes.md): append-only implementation history
- [docs/AGENTS.md](docs/AGENTS.md): contributor contract
- [src/frontend/README.md](src/frontend/README.md): frontend and Tauri shell

## License

[MIT](LICENSE)
