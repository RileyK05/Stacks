# Plan: central library and cross-platform desktop

Updated 2026-09-28. This is the current implementation and release handoff.
History belongs in `docs/notes.md`; candidate bugs belong in `docs/docket.md`.

## Product direction

1. The full library is the primary Stacks experience. It is the central place
   for courses, source-grounded knowledge, course memory, saved work, model
   setup, and data controls.
2. The companion is optional. The app does not create or position it at launch;
   the user presses **Open companion** when a separate focused window is useful.
3. The companion behaves like a normal desktop window: movable, resizable,
   minimizable, maximizable, closable, and optionally kept on top.
4. The core app targets Windows x64, Apple Silicon macOS, and Linux x64. The
   Office bridge remains an optional Windows integration.

## Current implementation

- Tauri starts the visible `main` library window and one authenticated Python
  backend child process.
- The persistent library navigation contains **Open companion**. In Tauri it
  invokes `show_companion`; in a browser preview it opens `/companion` in a
  resizable popup.
- `show_companion` creates the webview only on first request. Later requests
  bring the same window forward. Closing it frees that window without quitting
  the library.
- The companion uses native decorations and has minimum dimensions, normal
  resize behavior, and an opt-in always-on-top toggle.
- A second app launch focuses the library. Closing the library exits Stacks and
  shuts down the backend and supervised local model.
- Release packaging is native per OS: NSIS on Windows, DMG on Apple Silicon,
  and AppImage plus deb on Linux x64.

## Platform evidence

Release `v0.3.1` already produced all four native artifacts in one successful
GitHub Actions run:

- `Stacks_0.3.1_x64-setup.exe`
- `Stacks_0.3.1_aarch64.dmg`
- `Stacks_0.3.1_amd64.AppImage`
- `Stacks_0.3.1_amd64.deb`

That proves native packaging for the prior code. The current window lifecycle
passed all six backend and Tauri/frontend jobs on Windows x64, macOS arm64, and
Linux x64 in CI run `36490786861`. Installed UI checks remain below.

## Release gate

### A. Product hierarchy

- [x] Library is the only window created at startup.
- [x] Library contains a persistent, accessible **Open companion** action.
- [x] Companion creation is explicit and idempotent.
- [x] A second launch focuses the library.
- [x] Closing the library owns application shutdown.

### B. Window behavior

- [x] Companion uses native decorations and resizing.
- [x] Companion no longer forces monitor size, edge position, or collapsed
      geometry.
- [x] Always-on-top defaults off and remains user controlled.
- [ ] Windows installed smoke: open, move, resize, minimize, maximize, pin,
      close, reopen, and verify one companion window.
- [ ] Apple Silicon installed smoke for the same lifecycle.
- [ ] Linux X11 and Wayland installed smoke. Assert normal move/resize under
      Wayland; do not require compositor-controlled positioning.

### C. Quality and build

- [x] `python -m pytest -q` (507 passed)
- [x] `python -m ruff check .`
- [x] `python -m mypy src`
- [x] regenerate frontend API types from the current backend
- [x] `npm run check` and `npm run build` in `src/frontend`
- [x] `npm run check` and `npm test` in `src/office-addin` (12 passed)
- [x] `cargo clippy --all-targets --locked -- -D warnings`
- [x] Build the Windows installer from this tree (83 MB NSIS bundle).
- [x] Three-platform CI matrix passed for the current lifecycle implementation
      (run `36490786861`, commit `8c1bf97`).

### D. Core product smoke

- [ ] Fresh launch shows the library and no companion.
- [ ] Create or select a course, add a source, and see indexing finish.
- [ ] With a ready model, run a grounded library question and verify citations.
- [ ] Open the companion, run Explain, Find in course, Quiz me, Summarize, and
      a free question; verify substantive answers cite valid passages.
- [ ] Switch companion courses and confirm its visible conversation clears.
- [ ] Export and re-import a disposable `.course` archive.
- [ ] Quit and confirm the backend and local model child processes stop.

### E. Office bridge (Windows only)

- [ ] Connect Office from an installed Windows build and restart Office once.
- [ ] Word: selection read, cited answer, insert below, replace selection, save,
      close, and reopen.
- [ ] Excel: selected values/formulas, cited answer, comment or notes sheet,
      replace active cell, save, close, and reopen.
- [ ] PowerPoint: selected text/slide read, cited answer, text-box insert,
      replace selected text, save, close, and reopen.
- [ ] Disconnect Office and verify registration disappears after Office restarts.

### F. Release metadata

- [ ] Choose the next release version and run `scripts.set_version`.
- [ ] Finish the changelog entry.
- [ ] Commit the lifecycle, platform CI, tests, and docs together.
- [ ] Push a matching tag only after installed smoke tests.
- [ ] Review every platform artifact before publishing.

## Process topology

```text
launch Stacks
     |
     v
central library  ---- Open companion ----> movable/resizable companion
courses + memory                              pasted context + cited help
saved work + setup                            optional always-on-top
     |                                                 |
     +---------------- authenticated /api -------------+
                              |
                    SQLite + source files
                              |
                  local or selected cloud model

Windows Office only:
Word / Excel / PowerPoint <-> Office.js pane <-> grounded assistant
```

## Platform matrix

| Target | Package | Local model runtime | Office bridge |
| --- | --- | --- | --- |
| Windows x64 | NSIS `.exe` | Vulkan, then CPU fallback | Supported |
| macOS arm64 (M-series) | `.dmg` | Metal | Not yet supported |
| Linux x64 | `.AppImage`, `.deb` | Vulkan, then CPU fallback | Not applicable |

Intel macOS and Linux arm64 are outside the current matrix because there are no
pinned llama.cpp runtime assets for them. Add those targets only with native
PyInstaller builds, checksummed runtime archives, hardware mapping, and tests.

## Code map

| Piece | Location |
| --- | --- |
| Primary library shell and opener | `src/frontend/src/routes/(app)/+layout.svelte` |
| Companion route | `src/frontend/src/routes/companion/+page.svelte` |
| Dynamic companion window | `src/frontend/src-tauri/src/companion.rs` |
| Window and process lifecycle | `src/frontend/src-tauri/src/lib.rs`, `backend.rs` |
| Main window and platform-neutral bundle config | `src/frontend/src-tauri/tauri.conf.json` |
| Native installer selection | `scripts/build_desktop.py` |
| Platform CI | `.github/workflows/ci.yml` |
| macOS/Linux release builds | `.github/workflows/release-macos-linux.yml` |
| Companion API | `src/backend/api/companion.py` |
| Full library | `src/frontend/src/routes/(app)/` |
| Office host and setup | `src/backend/office_addin/` |

## Product rules

- Every substantive academic answer stays grounded in the selected course.
- The library remains useful without the companion or Office.
- Office owns Office files; document edits go through Office.js.
- Local data stays local unless the user explicitly selects a cloud provider or
  exports a course.
- Do not silently solve graded work.
