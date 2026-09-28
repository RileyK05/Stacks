# Plan: prepare the Stacks companion for release

Updated 2026-09-28. This is the current plan and handoff. Implementation
history belongs in `docs/notes.md`; candidate bugs belong in `docs/docket.md`.

## Start here

1. The companion is the primary product surface. Preserve its right-edge,
   pin, collapse, open-library, and explicit Quit behavior.
2. The full library manages courses, sources, saved work, models, data, and
   setup. It starts hidden and is opened from the companion.
3. The Office add-in is an optional live document bridge. Office owns and
   saves Office files; Stacks never reserializes them.
4. Work the **Release gate** in order. Do not return to large feature work
   until the installer and clean-install smoke test pass.

## Current state

The owner approved the companion's layout and interaction model after a live
Windows pass. The 420 px view, pin, collapse/restore, full-library button,
course selection, context actions, free question input, and error recovery are
implemented. The companion and Office pane share the same grounded assistant
contract and citation rules.

The full library, local backend, model runtime, course storage, ingestion,
retrieval, saved chats, artifacts, course archives, and Office setup remain in
place. Previous file-backed Office editors remain retired.

Release cleanup completed in the current working tree:

- public, contributor, frontend, system, and changelog docs now describe the
  companion-first product;
- Tauri permissions are split so the companion does not receive file dialogs
  or external opener access;
- chart HTML export is isolated in a sandboxed iframe with a restrictive CSP;
- version bumps update npm and Cargo lockfiles;
- installer builds use the locked Rust graph, clear stale output, and require
  exactly one installer;
- direct `lxml` production and typing dependencies are declared;
- packaged-backend startup errors point to the actual stderr log.

## Release gate

### A. Land one coherent change

- [x] Review `git diff` and remove accidental/generated files.
- [ ] Include the companion's tracked modifications and new files in the same
      commit. A partial commit does not build from a clean checkout.
- [ ] Keep `docs/docket.md` as the verified/deferred ledger, not a claim that
      every static-review candidate is reproduced.

### B. Quality checks

- [x] `python -m pytest -q` (499 passed)
- [x] `python -m ruff check .`
- [x] `python -m mypy src`
- [x] regenerate the frontend API schema from the current backend
- [x] `npm run check` and `npm run build` in `src/frontend`
- [x] `npm run check` and `npm test` in `src/office-addin`
- [x] `cargo clippy --all-targets --locked -- -D warnings`

### C. Installer

- [x] Run `.venv/Scripts/python -m scripts.build_desktop` without
      `--skip-backend`.
- [x] Confirm exactly one NSIS installer is produced under
      `src/frontend/src-tauri/target/release/bundle/nsis/`.
- [ ] Install for the current user and launch without the checkout, virtualenv,
      Node, or Vite running.
- [ ] Confirm Quit removes Stacks, its Python backend, Office host, and local
      model child processes.
- [ ] Uninstall and confirm user data is handled as documented.

### D. Product smoke test

- [ ] Companion opens on the right work area and remains usable at 100%, 125%,
      and 150% display scaling.
- [ ] Pin and collapse/restore work across a monitor change.
- [ ] Open the full library, create or select a course, and add a source.
- [ ] With a ready model, run Explain, Find in course, Quiz me, Summarize, and a
      free question. Every substantive answer shows valid source passages.
- [ ] Switch courses and confirm the visible companion conversation clears.
- [ ] Restart Stacks and confirm remembered course, pin, and collapsed state.
- [ ] Export and re-import a disposable `.course` archive.

### E. Office bridge smoke test

- [ ] Connect Office from an installed Stacks build and restart Office once.
- [ ] Word: selection read, cited answer, insert below, replace selection, save,
      close, and reopen.
- [ ] Excel: selected values/formulas, cited answer, comment or notes sheet,
      replace active cell, save, close, and reopen.
- [ ] PowerPoint: selected text/slide read, cited answer, text-box insert,
      replace selected text, save, close, and reopen.
- [ ] Disconnect Office and verify the registration disappears after Office
      restarts.

### F. Release metadata

- [ ] Choose the release version.
- [ ] Run `.venv/Scripts/python -m scripts.set_version X.Y.Z`.
- [ ] Finish that version's `CHANGELOG.md` entry.
- [ ] Push a matching `vX.Y.Z` tag only after the clean-install smoke test.
- [ ] Review the draft GitHub release and installer before publishing.

## How it works

```text
Any Windows app                Stacks companion             Stacks library
---------------                ----------------             --------------
copy text / ask a question --> /api/companion/assist  -->  courses + sources
                               cited answer                  settings + setup
                               pin / collapse / expand

Word / Excel / PowerPoint      Office task pane
-------------------------      ----------------
live selection <-------------> Office.js adapter
document insertion             /office/assist -> grounded assistant
```

The desktop creates two Tauri windows. `companion` is visible and docks to the
right work area. `main` starts hidden. Both use one authenticated loopback
backend. The installed build packages that backend with PyInstaller and stores
user data under the app's local data directory.

## Code map

| Piece | Location |
| --- | --- |
| Companion route | `src/frontend/src/routes/companion/+page.svelte` |
| Dock, pin, collapse, library, quit | `src/frontend/src-tauri/src/companion.rs` |
| Window/process lifecycle | `src/frontend/src-tauri/src/lib.rs`, `backend.rs` |
| Tauri windows and installer | `src/frontend/src-tauri/tauri.conf.json` |
| Companion API | `src/backend/api/companion.py` |
| Grounded Office/companion assistant | `src/backend/api/office.py`, `src/backend/tutor/office.py` |
| Full library | `src/frontend/src/routes/(app)/` |
| Office host and setup | `src/backend/office_addin/` |
| Office task pane | `src/office-addin/public/` |
| Installer script | `scripts/build_desktop.py` |
| Version script | `scripts/set_version.py` |

## After the first release

1. Use daily companion feedback to decide whether an always-on-top edge window
   is sufficient or a Windows AppBar should reserve desktop space.
2. Add one-click clipboard capture or a global hotkey only after defining its
   privacy and focus behavior.
3. Decide whether closing the companion should quit or leave a tray process for
   the Office pane.
4. Return to concept extraction, diagnostics, the student error model, and
   transparent study recommendations in `docs/project.md`.

## Product rules

- Every substantive academic answer stays grounded in the selected course.
- Office owns Office files; all document edits go through Office.js.
- Local data stays local unless the user explicitly selects a cloud provider or
  exports a course.
- Do not silently solve graded work.
- Do not publish a release that has only been run from the checkout.
