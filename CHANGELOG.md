# Changelog

All notable changes to Stacks. Versions follow [semantic versioning](https://semver.org);
`scripts/set_version.py` sets a new one everywhere it is written down.

## Unreleased

### Changed
- Stacks now opens to the central course and memory library. The companion is
  created only after the user presses **Open companion**.
- The companion is a normal native window with platform title-bar movement,
  resizing, minimizing, and maximizing instead of a fixed Windows edge dock.
- Backend, frontend, and Tauri CI gates now run on Windows x64, Apple Silicon
  macOS, and Linux x64. Release jobs assert their native architecture before
  packaging.

## [0.3.1] - 2026-09-28

### Added
- Experimental macOS (Apple Silicon, `.dmg`) and Linux (x64, `.AppImage` and
  `.deb`) builds, made by their own release workflow and attached to the same
  GitHub release as the Windows installer. The macOS app is ad-hoc signed, not
  notarized.

### Fixed
- On macOS, cleaning up a model server left behind by a crash no longer
  signals whatever process now has its old process id.

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
