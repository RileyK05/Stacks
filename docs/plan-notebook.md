# Plan: central library and cross-platform desktop

Updated 2026-09-29. This is the current implementation and release handoff.
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
  invokes `show_companion`; in a browser preview it opens `/companion/` in a
  resizable popup. The control is near the top of navigation, and course pages
  also show a labeled **Companion** button.
- `show_companion` creates the webview only on first request. Later requests
  bring the same window forward. Creation is serialized across rapid requests.
  Closing it frees that window without quitting the library. The static build
  includes `companion/index.html` for the native secondary window.
- Opening Office from a course also opens or focuses the companion on that
  course. An already open companion switches courses and clears prior turns.
- Quiz generation checks options, answer keys, cited names/dates, and dated
  events. It can make two repair attempts and retain individually verified
  questions across them. If none survive, it declines to propose a quiz.
- The companion uses native decorations and has minimum dimensions, normal
  resize behavior, and an opt-in always-on-top toggle.
- A second app launch focuses the library. Closing the library exits Stacks and
  shuts down the backend and supervised local model.
- Release packaging is native per OS: NSIS on Windows, DMG on Apple Silicon,
  and AppImage plus deb on Linux x64.

## Adaptive learning baseline (2026-09-29)

The library now records whole multiple-choice tests, keeps distilled course
capability evidence after session deletion, and applies cross-course teaching
preferences. Chat suggests cautious experiments in the background. The optional
Memory tab exposes evidence and corrections; it is not a step students must
complete before getting help. Practice selection enforces weak-area cooldowns,
focus quotas, occasional strong-area checks, and selected-source scope.

`docs/learning-memory.md` is the implementation and behavior handoff. Calibration,
free-response assessment, proving method effectiveness, and broad factual
quality evaluation remain open; passing persistence tests does not settle them.

## Platform evidence

Release `v0.3.1` already produced all four native artifacts in one successful
GitHub Actions run:

- `Stacks_0.3.1_x64-setup.exe`
- `Stacks_0.3.1_aarch64.dmg`
- `Stacks_0.3.1_amd64.AppImage`
- `Stacks_0.3.1_amd64.deb`

That proves native packaging for the prior code. The current window lifecycle
passed all six backend and Tauri/frontend jobs on Windows x64, macOS arm64, and
Linux x64 in CI run `36490786861`. Release workflow run `36492354123` then
built and uploaded fresh `stacks-0.3.1-macos-arm64` and
`stacks-0.3.1-linux-x64` artifacts from the current implementation. Installed
UI checks remain below.

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
- [ ] From an installed build, confirm the companion renders content instead
      of a white webview, including after two quick clicks.
- [ ] Apple Silicon installed smoke for the same lifecycle.
- [ ] Linux X11 and Wayland installed smoke. Assert normal move/resize under
      Wayland; do not require compositor-controlled positioning.

### C. Quality and build

- [x] `.venv/Scripts/python -m pytest -q` (512 passed on 2026-09-28)
- [x] `python -m ruff check .`
- [x] `python -m mypy src`
- [x] regenerate frontend API types from the current backend
- [x] `npm run check` and `npm run build` in `src/frontend`
- [x] `npm run check` and `npm test` in `src/office-addin` (12 passed)
- [x] `cargo clippy --all-targets --locked -- -D warnings`
- [x] Build the Windows installer from this working tree (83 MB NSIS bundle);
      its bundled backend returned `/api/health` OK with disposable data.
- [x] Build Apple Silicon macOS and Linux x64 installers from this
      implementation (release workflow run `36492354123`).
- [x] Three-platform CI matrix passed for the current lifecycle implementation
      (run `36490786861`, commit `8c1bf97`).

The checks above include local validation of this working tree. In a production
browser preview with an isolated backend, two disposable courses were created.
The companion rendered, opening it twice kept one popup, and opening it from
each course switched the selected course in the existing popup. An empty course
now explains that a source must be added before asking. Installed UI smoke for
these latest fixes remains a release gate.

The local Windows build produced
`src/frontend/src-tauri/target/release/bundle/nsis/Stacks_0.3.1_x64-setup.exe`
with SHA-256 `D248ED09419A8AA6018DFE587AE6E3C3A97CC8A8A28A2898D046E9594A5F9C83`.
It was built as a smoke artifact at the current `0.3.1` version; it has not
been installed or published.

A manual MiniCPM5-2B probe used two synthetic César Chávez passages through
the real model provider and quiz composition path. It exposed wrong answer
indexes and a question about an event with no date in the cited passage. The
new gate filtered those outputs; the latest three runs each returned specific,
cited questions with matching answers. This is evidence for the generation
path, not a substitute for the indexed-course and installed UI smoke below.

### D. Core product smoke

- [ ] Fresh launch shows the library and no companion.
- [ ] Create or select a course, add a source, and see indexing finish.
- [ ] With a ready model, run a grounded library question and verify citations.
- [ ] Open the companion, run Explain, Find in course, Quiz me, Summarize, and
      a free question; verify substantive answers cite valid passages.
- [ ] With a ready local model, request a quiz on a named topic from indexed
      course material. Confirm specific questions and full answer choices;
      confirm unusable output is withheld.
- [ ] Switch companion courses and confirm its visible conversation clears.
- [ ] Export and re-import a disposable `.course` archive.
- [ ] Quit and confirm the backend and local model child processes stop.

### E. Office bridge (Windows only)

- [ ] Connect Office from an installed Windows build and restart Office once.
- [ ] From a course, use **Open in Office** and confirm its document, course
      companion, and Office task pane all open with the expected context.
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


## Companion work-session baseline (2026-09-29)

The companion route now opens saved work sessions beside external applications.
File/paste, Windows window capture, and Office publication share document
snapshots with the main database. Course evidence remains separate from draft
text; paper review and worksheet discussion cannot write learning memory or
scores. Revision checks prevent responses attaching to a refreshed document.
See `docs/companion-work.md` for the implemented flow, model-quality findings,
and the remaining native capture, Office-host, and direct-edit verification.

The baseline passed 685 backend tests, backend lint/types, frontend check/build,
and Office bridge tests/types. Structured reviews and proposed edits validate
exact draft passages; archived references clear missing source links. Live model
quality is still mixed: a usable selected-passage edit had an incorrect
explanation. Keep model judgments inspectable and do not describe semantic
acceptance as passed. Native Windows capture and real Office hosts still need
verification. Test-only services were shut down after browser verification.
