# Changelog

All notable changes to Stacks. Versions follow [semantic versioning](https://semver.org);
`scripts/set_version.py` sets a new one everywhere it is written down.

## [0.3.0] - 2026-09-28

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
- A docked Windows companion is now the primary interface. It snaps to the
  right work area, can stay on top, collapses to a narrow edge tab, opens the
  full course library on demand, and works beside any app from pasted context.
- The companion shares the grounded Office assistant path for Explain, Find in
  course, Quiz me, Summarize, free questions, and cited answers.
- The app shows its version in Settings, and the API reports it.
- A start-up screen while the backend loads, and a clear message if it
  fails to start.
- Only one copy of the app runs at a time; opening it again brings the
  existing window forward.
- Stacks inside Word, Excel and PowerPoint (Windows): connect Office once in
  Settings, or press Open in Office on a course, and a Stacks button appears
  on the Home tab. Its pane explains, finds, quizzes and summarizes what you
  select from your course, with sources, and can insert the answer. Office
  keeps full control of your files.

### Removed
- The pywebview window, and the Postgres importer used during the move to
  local-first.

## [0.1.0]

The first local-first build: SQLite, the bundled llama.cpp runtime with
MiniCPM5-2B by default, optional OpenRouter / OpenAI / custom providers,
ONNX encoders, task-framed answers with citations, "Ask a bigger model",
the answer cache, `.course` export and import, and the 30-day trash.
