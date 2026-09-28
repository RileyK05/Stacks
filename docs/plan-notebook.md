# Plan: Stacks inside Microsoft Office

Updated 2026-09-27. This file is **only the current plan**. History and
decisions live in `docs/notes.md` (append-only); when the direction changes,
rewrite this file rather than letting it grow.

## Start here (next contributor)

1. Checks green: `pytest`, `ruff check .`, `mypy src`, `npm run check` in
   `src/frontend`, `npm run check` + `npm test` in `src/office-addin`,
   `cargo clippy` in `src/frontend/src-tauri`. CI runs the same
   (`.github/workflows/ci.yml`).
2. Read "How it works" and "Code map" below, then the latest `notes.md`
   entries ("One-click Office", "Office assistant", "Retiring the file-backed
   Office editors").
3. The gate for everything under "Next" is the **owner's first run in real
   Office** (checklist below). Fix what it finds before building more.

## Direction

**Stacks knows the student; Office knows the document.** Instead of
rebuilding Word, Excel and PowerPoint inside Stacks (tried and retired: every
editor either lost authored content on save or could not render real files),
Stacks goes into Office as a task pane. Office renders, edits and saves its
own files; Stacks reads what the student is looking at, answers from their
course with citations, and hands text back for Office to insert. Stacks never
writes an Office file, so a feature Stacks doesn't understand is a missing
capability, never a corrupted document.

- The retired editors are deleted (code, branch, and their test artifacts).
  Their migration numbers 006/007 stay reserved (`migrate.RETIRED_VERSIONS`):
  databases from those builds recorded them.
- The JSON artifact kinds stay as Stacks-side study tools: `doc` → course
  notes, `sheet` → schedules/trackers, `slides` → study decks, plus quizzes,
  flashcards, code, charts.
- Windows desktop Office (Microsoft 365 / Office 2016+) only, for now.

## Status

Built and machine-tested end to end: setup, hosting, the bridge, the grounded
answers, the pane logic and its Office.js calls (type-checked against
Microsoft's `@types/office-js`), and the manifest (passes Microsoft's
`office-addin-manifest validate`). **Not yet done: a run inside real Office.**
The certificate prompt, Office picking up the registration, and the pane
reading/writing a live document can only be proven there.

## How it works

```text
Stacks app                                  Word / Excel / PowerPoint
─────────                                   ─────────────────────────
Settings → Microsoft Office → Connect   ──▶ Home tab → Stacks → pane
  or a course → Open in Office                reads the selection
                                              asks /office/assist
backend (already running with the app)        inserts / replaces text
  serves https://localhost:47831              through Office.js
    /            the pane (src/office-addin/public)
    /office/*    the bridge (api/office.py)
```

**Connect Office** (`office_addin/service.connect`; idempotent, "Repair" runs
the same thing), per-user, no admin rights:

1. Issue a `localhost` certificate signed by a fresh CA whose private key is
   discarded immediately, so trusting it cannot be abused for other sites.
2. Ask Windows to trust that CA (`certutil -user -addstore Root`: one system
   dialog). Office only loads panes over trusted HTTPS.
3. Render the manifest for this port and app version into the data folder
   and register it under `HKCU\Software\Microsoft\Office\16.0\WEF\Developer`,
   the per-user developer add-in key Office reads at start (all three apps).
4. Serve pane and bridge from the backend process (own thread, fixed port
   `APP_OFFICE_PORT`, default 47831). Later launches re-serve automatically
   and never prompt; an expired or untrusted certificate shows "Needs
   attention" → Repair.

**Open in Office** (course header menu, or Settings) launches Word, Excel or
PowerPoint with a new document or a picked file, connecting first if needed,
and remembers the course so the pane opens on it. Office only picks up a newly
registered add-in when it starts, so the first time, an already-open app needs
one restart (the app says so).

**The pane** follows the selection, remembers the course per document, and
offers Explain / Find in my course / Quiz me / Summarize or a free question.

| Host | Reads | Insert | Replace |
| --- | --- | --- | --- |
| Word | selection, or the paragraph at the cursor | paragraphs below the selection | the selection |
| Excel | selected range: address, values, formulas (first 100×20 cells) | a comment on the active cell, else a row in a "Stacks notes" sheet | the active cell |
| PowerPoint | selected text, else every text shape on the slide | a text box on the slide | the selected text |

Every host falls back to Office's Common API (`get/setSelectedDataAsync`) when
its richer API isn't available. Inserted text is plain text plus a "Sources:"
list for the citations it uses. Graded work is refused; empty retrieval is
refused (source grounding, AGENTS.md rules 1 and 4).

**Stacks must be open** while the pane is used: the app serves it. Disconnect
(Settings) unregisters, stops serving, untrusts the CA and deletes its files.

## Code map

| Piece | Where |
| --- | --- |
| Setup, certificate, Windows trust/registry/launch, HTTPS host | `src/backend/office_addin/` (`service`, `certs`, `windows`, `manifest`, `host`, `app`) |
| App API: status / connect / disconnect / open | `src/backend/api/office_setup.py` → `/api/office/*` |
| Bridge the pane calls: health, courses, assist, read | `src/backend/api/office.py` → `/office/*` on the add-in origin |
| Grounded answers for the pane actions | `src/backend/tutor/office.py`, prompts `office_*` in `configs/prompts.toml` |
| Redundant readers (scrape / package / screenshot OCR, merged) | `src/backend/office_reader/`, `POST /office/read` |
| The pane (served and bundled as-is, no build step) | `src/office-addin/public/` (`manifest.xml`, `taskpane.*`, `bridge.js`, `assets/`) |
| Pane tooling: Office.js type-check, logic tests | `src/office-addin/` (`npm run check`, `npm test`) |
| App UI | `lib/components/settings/OfficeCard.svelte`, `lib/components/course/OfficeMenu.svelte`, `lib/stores/office.ts` |
| Tests | `tests/test_office_addin_setup.py`, `test_office_addin_manifest.py`, `test_office_bridge_api.py`, `test_office_assistant.py`, `test_office_reader.py`, `src/office-addin/bridge.test.js` |

Tests fake the Windows layer (`FakeWindows`); nothing in the suite touches
the real trust store or registry.

## Owner's first run (the gate)

Use `npm run desktop` (or an installed build) with a course that has sources
and a model ready.

1. Settings → Microsoft Office → **Connect Office**. Windows asks to install
   a certificate → Yes. The card shows **Connected**.
2. On the course: **Open in Office** → New PowerPoint deck (or open a lecture
   `.pptx`). If PowerPoint was already open, close it and reopen once.
3. Home tab → **Stacks**. The pane says "Connected to Stacks …" with the
   course selected.
4. Select text on a slide: "Looking at" fills in. **Explain** → an answer
   with citations. **Add to slide** → a text box with a Sources list;
   **Replace selected text** → the selection changes.
5. Same in Word (select a paragraph; Insert below / Replace selection) and
   Excel (select cells with formulas; Add as comment / Write into cell).
6. Save, close and reopen each file in Office: everything else is intact.
7. Close Stacks: the pane can't load. Reopen Stacks, reopen the pane: works.
8. Settings → **Disconnect** → confirm Windows' prompt. After an Office
   restart the Stacks button is gone.

If something fails: the backend log is `backend.log` in the data folder
(Settings → Your data → Open folder); the card's "Needs attention" list names
the broken step. Record the result in `notes.md`.

## Next (in order, after the first run)

1. **Fix what the first run finds.** Likely spots: Office not showing the
   button (registration / cache), the certificate prompt, host-specific
   Office.js behaviour.
2. **Installed build.** Build with `scripts.build_desktop`, install, repeat
   the checklist once; the installer has never been run end to end.
3. **Save from the pane into the course.** "Save to course notes" turns a
   pane answer into a cited `doc` artifact, so work done in Office feeds the
   course notebook.
4. **Deeper reads.** The pane sends only the scrape today; send the package
   bytes (Office's `getFileAsync`) and slide renders to `/office/read` so the
   merged read catches what text scraping misses (charts, images, scans).
5. **Per-host actions.** Excel: explain a formula chain; Word: add the answer
   as a comment; PowerPoint: speaker notes once Office.js exposes them.
6. **Keep the pane available.** Today the pane needs the Stacks window open;
   decide whether Stacks keeps running in the tray (owner question).
7. Then back to the product plan (`project.md`): concept extraction and the
   student model.

## Open questions (owner)

1. Keep Stacks running in the tray when the window closes, so the Office pane
   always works?
2. Office on the web and on Mac are out of scope for now: confirm.

## Rules for this work

- Office owns the file: no Stacks code writes, exports or re-serializes a
  `.docx`/`.xlsx`/`.pptx`. Document changes go through Office.js only.
- Every Office.js call must type-check against `@types/office-js`
  (`npm run check` in `src/office-addin`); requirement sets are checked at
  runtime (`isSetSupported`) with a Common API fallback.
- Only `src/office-addin/public/` is served and bundled; keep tooling and
  tests outside it.
- The bridge returns text and citations only, and every answer is grounded
  in the course (the same fence and graded-work rule as the tutor).
