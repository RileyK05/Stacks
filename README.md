# Stacks

A study tool that runs on your own laptop. Add your course materials
(syllabi, readings, slides, notes) and ask questions about them. Every
answer cites the passages it came from, and you can open them without
leaving the answer.

- **Local by default.** A small open model (MiniCPM5-2B) runs on your
  machine through a bundled llama.cpp server, so no account or API key is
  needed. Your files and history stay in a folder on your computer.
- **Your choice of model.** In Settings you can switch to another local
  model, or to OpenRouter, OpenAI, or any OpenAI-compatible endpoint. A
  cloud model is used only if you pick one, and the app tells you what it
  will receive first. Keys are stored in your OS keychain.
- **Answers you can check.** Retrieval combines keyword search, the
  course's table of contents, concept links, and embeddings, then reranks
  the results. Answers must cite the material they draw on, and the app
  says so when the material doesn't cover a question.
- **More than Q&A.** Ask for a quiz, notes, a table, or slides, and the
  output is built from your course and cited. Requests to do graded work
  get steered toward help with learning it.
- **Portable courses.** Export a course as one `.course` file and import
  it on another machine.

This is an early build. The student model (diagnostics, mastery, "what to
study next") is designed but not built yet; see [docs/project.md](docs/project.md).

## Install

Installers will be published on this repo's Releases page; until the
first one is, build it from source (below). The installer,
`Stacks_<version>_x64-setup.exe`, installs for your user only (no admin
rights needed). It isn't code-signed yet, so Windows SmartScreen will warn
before it runs.

Before the first question, download a local model in Settings. The default
is about 1.6 GB, and the llama.cpp runtime comes with it; both are
checksummed. If LM Studio or the Hugging Face cache already holds a
verified copy, the app uses that one instead.

**Requirements:** Windows 10 or 11, 8 GB RAM minimum (16 GB recommended).
macOS and Linux builds are planned.

## Build from source

You need Python 3.12+, Node.js 22+, and a Rust toolchain
([rustup](https://rustup.rs); on Windows also the Visual Studio C++ build
tools).

```
python -m venv .venv
.venv/Scripts/pip install -e ".[desktop,dev]"
cd src/frontend && npm install && cd ../..
```

Run the app in development (it starts the backend from `.venv` and uses
the checkout's `data/` folder):

```
cd src/frontend
npm run desktop
```

Build the installer (lands in `src/frontend/src-tauri/target/release/bundle/nsis/`):

```
.venv/Scripts/python -m scripts.build_desktop
```

## Development

```
.venv/Scripts/python -m pytest              # tests
.venv/Scripts/python -m ruff check .        # lint
.venv/Scripts/python -m mypy src            # typecheck
cd src/frontend && npm run check            # frontend typecheck
cd src/frontend/src-tauri && cargo clippy   # desktop shell lint
```

Releases: `python -m scripts.set_version X.Y.Z` sets the version in every
manifest, and [CHANGELOG.md](CHANGELOG.md) gets the notes.

`scripts/eval_models.py` measures answer quality for any model in the
catalog, optionally against your own course files:

```
.venv/Scripts/python -m scripts.eval_models --help
```

## Docs

- [docs/project.md](docs/project.md): what the product is and where it's going
- [docs/plan-local-first.md](docs/plan-local-first.md): the desktop plan and its progress
- [docs/system.md](docs/system.md): architecture
- [docs/AGENTS.md](docs/AGENTS.md): conventions for contributors and coding agents
- [docs/decisions/](docs/decisions/): design decisions (012 covers the move to local-first)
- [src/frontend/README.md](src/frontend/README.md): the desktop app's frontend and Tauri shell

## License

[MIT](LICENSE)
