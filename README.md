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

## Requirements

- Windows 11 (macOS and Linux are planned but untested)
- 8 GB RAM minimum, 16 GB recommended
- Python 3.12+ and Node.js 22+ to build from source

Before the first question, download a local model in Settings. The default
is about 1.6 GB, and the llama.cpp runtime comes with it; both are
checksummed. If LM Studio or the Hugging Face cache already holds a
verified copy, the app uses that one instead.

## Run from source

```
python -m venv .venv
.venv/Scripts/pip install -e ".[desktop,dev]"

cd src/frontend
npm install
npm run build
cd ../..

.venv/Scripts/python -m src.backend.desktop
```

To package it as a standalone app in `dist/CourseAssistant/`:

```
.venv/Scripts/python -m scripts.build_desktop
```

## Development

```
.venv/Scripts/python -m pytest          # tests
.venv/Scripts/python -m ruff check .    # lint
.venv/Scripts/python -m mypy src        # typecheck
cd src/frontend && npm run check        # frontend typecheck
```

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
