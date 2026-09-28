# Stacks

[![CI](https://github.com/RileyK05/Stacks/actions/workflows/ci.yml/badge.svg)](https://github.com/RileyK05/Stacks/actions/workflows/ci.yml)

Stacks is a local-first study companion for course materials. Add syllabi,
readings, slides, and notes, then ask questions grounded in those sources.
Every substantive answer shows the passages it used.

- **A companion beside your work.** Stacks opens as a narrow Windows sidebar
  beside Word, a browser, or a PDF. Pin it above other apps, collapse it to an
  edge tab, paste what you are looking at, and explain, find, quiz, summarize,
  or ask a follow-up without leaving the current task.
- **Local by default.** A small open model runs through a supervised local
  llama.cpp server. Course files and history stay in the user's data folder.
- **Your choice of model.** Settings can use another local model, OpenRouter,
  OpenAI, or an OpenAI-compatible endpoint. Cloud use is opt-in and keys are
  stored in the OS keychain.
- **Answers you can check.** Retrieval combines keyword search, the course table
  of contents, concept links, and embeddings, then reranks the result. Answers
  cite the material they draw on and refuse when the material does not cover a
  question.
- **A full course library.** The companion opens the larger Stacks window for
  source management, saved chats, cited notes, schedules, study decks, quizzes,
  flashcards, course export/import, and settings.
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
- **macOS (Apple Silicon, experimental):** `Stacks_x.y.z_aarch64.dmg`. Drag
  Stacks into Applications and open it. When macOS says it can't verify the
  app, open *System Settings → Privacy & Security*, scroll down, and click
  *Open Anyway*. You only do this once.
- **Linux (x64, experimental):** `Stacks_x.y.z_amd64.AppImage` runs anywhere
  (`chmod +x` it, then run it); `Stacks_x.y.z_amd64.deb` installs on Debian and
  Ubuntu.

The macOS and Linux builds are new and less tested than Windows. The docked
companion and the Office add-in are designed for Windows first. On Linux under
Wayland the companion can't snap itself to the screen edge.

Before the first question, download a local model in Settings or choose a cloud
provider. The default local model is about 1.6 GB; downloads and the llama.cpp
runtime are checksummed.

**Requirements:** Windows 10 or 11, macOS 11+ on Apple Silicon, or 64-bit
Linux (Ubuntu 22.04 or newer). 8 GB RAM minimum, 16 GB recommended.

## Build from source

Install Python 3.12+, Node.js 22+, Rust, and the Visual Studio C++ build tools.

```powershell
python -m venv .venv
.venv/Scripts/pip install -e ".[desktop,dev]"
cd src/frontend
npm install
cd ../..
```

Run the app in development:

```powershell
cd src/frontend
npm run desktop
```

Build the Windows installer:

```powershell
.venv/Scripts/python -m scripts.build_desktop
```

The installer is written under
`src/frontend/src-tauri/target/release/bundle/nsis/`.

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
