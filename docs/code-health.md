# Code health review — 2026-09-29

This pass uses the existing working tree as its baseline. It preserves the
uncommitted feature work. Review covered the API and repository seams,
retrieval and evaluation, storage, provider/runtime lifecycle, artifact saving,
and the older engineering ledger. It is a targeted maintenance pass, not a
claim that every feature has been exercised in an installed app.

## Cleanup completed

- Consolidated the repeated active-course lookup and 404 behavior into
  `api/deps.require_course`. Course, source, tutor, chat, and artifact routes
  keep their existing response contracts.
- Retrieval fusion now creates normalized candidates instead of bypassing
  frozen dataclasses with `object.__setattr__`. Callers can reuse their original
  seam results without changed scores. TOC entry deduplication preserves order
  with a dictionary rather than repeated list scans.
- Retrieval evaluation counts every locator in a chunk's span. A chunk covering
  pages 1 and 2 previously scored as though it covered only its primary page.
  Exact label matching and equal per-seam/fused retrieval limits remain intact.
- Removed the unused storage-copy helper, blank-content wrapper, course-memory
  query and truncation marker, and empty type-checking block.
- Removed the duplicate, test-only in-memory compression implementation.
  Compression tests now exercise the streaming path used by uploads.
- Storage tests now restore `tempfile.tempdir` and use isolated per-test paths.
  The course-directory deletion test checks the actual directory it wrote;
  its old patch targeted the wrong imported function and its assertion could
  pass without verifying deletion.
- Office token comparison now uses UTF-8 bytes, matching the desktop API.
  Non-ASCII input previously raised `TypeError` instead of returning 401.
- Corrected the companion API's obsolete description as a docked window.

## Decisions with real tradeoffs

### 1. What guarantee should unsaved edits have?

**Current behavior:** `OpenArtifact.flush()` returns no save outcome, and returns
early if another save is in flight. Propose, restore, and export continue after
it. The artifact page fires a flush during destruction without waiting for it.
The draft exists in component state; no durable draft recovery is implemented.
These are verified control-flow observations, not an installed-app reproduction.

**Options:**

- Wait for saves and prevent navigation or dependent actions when a save fails.
  This is smaller and keeps one persisted source of truth, but users can be
  held on the page and a crash can still lose a draft.
- Keep a durable local draft and reconcile it with the artifact's version on
  reopening. Users can leave and recover work after a crash, but draft cleanup,
  conflict resolution, and deletion/export semantics become explicit features.

**Recommendation:** durable drafts if this is intended to be a daily writing
workspace; a navigation/save guard as the first stage. Either implementation
must await in-flight saves and prevent proposals/restores from discarding edits
after a failed save. Decide the guarantee before changing this lifecycle.

### 2. How should different local models share the machine?

**Current behavior:** one supervised llama-server serves the bundled runtime.
`provider.generate()` ensures the requested model, then performs HTTP outside
the server's lock. `LlamaServer.start()` stops the old server before loading
the next model. Chats, background tasks, and the bigger-model choice can select
different models. A switch can therefore overlap another request. This is an
identified interleaving to reproduce with a deterministic concurrency test;
it was not exercised against real models in this pass.

**Options:**

- Use one server with a scheduler that holds a model lease through each request,
  prioritizes foreground work, and switches only between requests. RAM stays
  bounded, but another model's request waits for the active call and reload.
- Run separate servers for active models. Calls can overlap, but RAM/VRAM and
  context buffers multiply; capacity limits and eviction become necessary.

**Recommendation:** one scheduled server for the documented 8 GB floor machine.
Keep concurrent runners as an explicit option for machines with enough memory.
The choice controls latency, cancellation, and background-task scheduling.

### 3. How much authority should the local integrations have?

**Current behavior:** the authenticated artifact-export API accepts a file path
and writes there, with a filename extension check but no directory scope. The
Office HTTPS bridge accepts requests without a token when `APP_OFFICE_TOKEN`
is empty, which is the default. Its pane is served on the bridge's own origin.
Same-origin serving simplifies the pane but is not request authentication.

**Options:**

- Keep the authenticated desktop API as a trusted local controller with broad
  file authority. The implementation stays simple, but anyone obtaining its
  token gets those powers, and Office needs an explicit origin/auth policy.
- Move arbitrary-path file operations into native commands tied to user file
  selections, keep backend exports in a managed directory, and define a separate
  authenticated Office session. Authority is narrower, but pane bootstrap,
  token rotation, and file handoff add integration work.

**Recommendation:** narrow native file operations and an authenticated Office
session before broader distribution. This is not isolation from other software
already running as the same OS user. Define the attacker and allowed clients
before selecting a token/bootstrap design.

## Engineering follow-up that needs no product decision

- Expand the retrieval corpus before changing the four-seam algorithm. The
  committed retrieval set currently contains one case. A multi-page label fix
  makes scoring more accurate; it does not establish retrieval quality.
- Build dependency locks for reproducible Python release environments.
- Move evaluation fixture seeding out of `tests.factories`; the production
  bake-off script currently imports it. Check the report directory naming for
  model IDs containing Windows-invalid filename characters.
- Test failed-save and concurrent-model paths deterministically once their
  intended behavior is selected. Passing isolated request tests is insufficient
  evidence for these lifecycle paths.

## Older ledger corrections

`docket.md` is a candidate ledger, not an executable work list. In particular:

- C-01's upload-copy writer-lock claim does not describe this tree: the file
  copy occurs before the first database write, and SQLite transactions start
  lazily on that write. Opening a connection alone does not acquire the writer.
- D-07's retired migration numbers are checked by an existing test; deleting the
  constant as supposedly dead code would remove a migration-history safeguard.
- D-16's `raw_pdf_bytes` parameter is used by the PDF extraction path and should
  remain. Only its empty `TYPE_CHECKING` block was removed.
- The two `ExportView` models have different fields and purposes. Matching
  class names alone is not a reason to merge their contracts.
- Do not rename the keyring service just to match the app's branding; existing
  credentials need a migration. Planned student-model schemas likewise need
  a separate scope review, rather than deletion by reference count.

## Validation

Baseline: 628 Python tests passed, Ruff passed, backend mypy passed, and
Svelte diagnostics reported zero errors and warnings.

After cleanup: the focused storage, retrieval, Office bridge, and course API
suite passed 168 tests; the full Python suite passed 634 tests. Ruff and strict
backend mypy passed. Svelte diagnostics reported zero errors and warnings;
Office.js type checks and all 12 bridge tests passed. The Python suite retains
the dependency's existing Starlette/httpx deprecation warning. No native build
or installed-app smoke was run; Rust and frontend behavior were not changed.

An incremental patch relative to the pre-existing working tree is available
locally at `runs/cleanup-review/cleanup.patch`; it excludes the earlier edits.
No commits, dependency upgrades, schema migrations, or model/prompt changes
were made in this pass.
