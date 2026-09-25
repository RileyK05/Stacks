# Changelog

All notable changes to Stacks. Versions follow [semantic versioning](https://semver.org);
`scripts/set_version.py` sets a new one everywhere it is written down.

## [0.2.0] - Unreleased

### Changed
- The desktop app is now a Tauri app named Stacks. The window, the
  installer (NSIS, per-user, no admin rights) and the app's own shell are
  native; the Python backend runs as a background process the app starts
  and stops.
- Your data lives in the per-user app-data folder (`%LOCALAPPDATA%\io.github.rileyk05.stacks` on Windows).
- Fonts ship with the app: no request to Google Fonts on launch, and the
  app looks right offline.
- Links in answers open in your browser instead of inside the app.
- `.course` exports now carry the format id `stacks/course`.

### Added
- The app shows its version in Settings, and the API reports it.
- A start-up screen while the backend loads, and a clear message if it
  fails to start.
- Only one copy of the app runs at a time; opening it again brings the
  existing window forward.

### Removed
- The pywebview window, and the Postgres importer used during the move to
  local-first.

## [0.1.0]

The first local-first build: SQLite, the bundled llama.cpp runtime with
MiniCPM5-2B by default, optional OpenRouter / OpenAI / custom providers,
ONNX encoders, task-framed answers with citations, "Ask a bigger model",
the answer cache, `.course` export and import, and the 30-day trash.
