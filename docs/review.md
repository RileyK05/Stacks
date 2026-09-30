# Code Review: Stacks (course_proj_model)

**Reviewer:** Angry Code Review  
**Date:** 2026-09-29  
**Scope:** Full codebase — backend (Python/FastAPI), frontend (SvelteKit), Tauri shell (Rust), Office add-in (JS)

---

## Summary

This codebase is a Tauri v2 desktop application with a Python/FastAPI backend, SvelteKit frontend, and Rust shell. It implements a local-first course memory and adaptive study system. The architecture is well-documented and generally well-structured, but there are numerous bugs, security concerns, performance issues, and code quality problems throughout.

**Total issues found:** 50  
**Critical:** 3  
**High:** 10  
**Medium:** 17  
**Low:** 20  

---

## Critical Issues

### C1. Module-level mutable dict leaks memory forever

**File:** `src/backend/common/provider.py:409`

```python
_ADAPTATIONS: dict[tuple[str, str], set[str]] = {}
```

This module-level dict accumulates request adaptations forever. In a long-running server process, this grows unbounded. Every unique `(base_url, model)` pair that ever gets a 400 error adds an entry that is never removed. Over weeks of operation, this becomes a memory leak.

**Fix:** Use a bounded cache (e.g., `functools.lru_cache` with a max size) or clear the dict periodically.

---

### C2. Encoder files downloaded without integrity verification

**File:** `src/backend/common/encoders.py:55-79`

```python
def ensure_files(spec: EncoderSpec) -> Path:
    ...
    if file.sha256 and file.size_bytes:
        download_verified(...)
        continue
    target.parent.mkdir(parents=True, exist_ok=True)
    response = httpx.get(spec.url(file), follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(response.content)
    partial.replace(target)
```

Files without both `sha256` AND `size_bytes` are downloaded with zero integrity verification. A malicious or compromised Hugging Face endpoint could serve arbitrary ONNX model files. The comment says "small files are pinned by revision", but the revision is part of the URL — if it's ever changed to a branch name instead of a commit hash, the file could change silently.

**Fix:** Always verify sha256 for model files. If a file genuinely has no sha256, compute and cache one on first download.

---

### C3. Setting a key creates a connection as a side effect

**File:** `src/backend/api/settings.py:212-221`

```python
def _connection_for_key(name: str) -> Connection:
    found = providers.get_connection(name)
    if found is not None:
        return found
    if name in providers.load_models_config().presets and name != providers.LOCAL:
        return providers.add_connection(name, connection_id=name)
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown connection: {name}")
```

A PUT to `/settings/keys/{connection_id}` with a preset name (e.g., "openai") silently creates a new connection in the database. This is a side effect of a key-setting operation. A user who types a preset name instead of a connection ID gets a new connection created without warning.

**Fix:** Separate the "find or create" logic from the "set key" endpoint. Return a 404 for unknown connections and let the client create the connection explicitly.

---

## High Issues

### H1. `read_stored` loads entire file into memory for identity-encoded files

**File:** `src/backend/common/storage.py:291-311`

```python
def read_stored(...) -> bytes:
    ...
    if stored_encoding != "gzip":
        expanded = path.stat().st_size
        if expanded > max_decompressed_bytes:
            raise DecompressionLimitExceededError(...)
        return path.read_bytes()
```

`path.read_bytes()` loads the entire file into memory. For a large PDF (e.g., 500MB), this allocates 500MB of RAM. The gzip path streams in 1MB chunks, but the identity path does not.

**Fix:** Return a file-like object or stream the response in chunks.

---

### H2. `source_content` API loads entire file into memory

**File:** `src/backend/api/sources.py:148-161`

```python
data = storage.read_stored(
    course_id, source_id, row["stored_encoding"],
    max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
)
return Response(content=data, media_type=row["mime_type"], ...)
```

The entire file is loaded into memory and passed as `content` to `Response`. For large files, this causes memory pressure. FastAPI's `Response` can accept a file-like object or an iterator for streaming.

**Fix:** Use `StreamingResponse` with a file iterator, or pass a file-like object.

---

### H3. `export_course` loads entire file into memory

**File:** `src/backend/common/course_archive.py:126-137`

```python
data = storage.read_stored(
    course_id, row["source_id"], row["stored_encoding"],
    max_decompressed_bytes=policy.max_decompressed_bytes,
)
...
archive.writestr(path, data, compress_type=compression)
```

Each source file is fully loaded into memory before being written to the zip. For a course with large files, this could use significant memory.

**Fix:** Use `archive.open(path, 'w')` and stream the file in chunks.

---

### H4. `embedding_seam` loads all embeddings into memory

**File:** `src/backend/retrieval/funnel.py:297-310`

```python
rows = conn.execute(
    get(_FILE, "embedding_rows"),
    {"course_id": course_id, "model": model, ...},
).fetchall()
```

All embeddings for a course are fetched at once. For a course with 100,000 chunks at 384 dimensions (4 bytes each), this is ~150MB of data loaded into memory.

**Fix:** Use a cursor to iterate over rows, or fetch in batches.

---

### H5. `targets` loads all observations into memory

**File:** `src/backend/student_model/learning.py:258-264`

```python
for observation in rows(conn, "observations", course_id=course_id):
    grouped[(observation["topic"].casefold(), observation["capability"])].append(observation)
```

All observations for a course are loaded at once. For a student with many practice runs, this could be tens of thousands of rows with large evidence dicts.

**Fix:** Use a cursor or fetch in batches.

---

### H6. `course_memory.refresh` loads all material into memory

**File:** `src/backend/common/course_memory.py:155-162`

```python
def _fetch_material(conn: Connection, course_id: UUID) -> dict[str, list[DictRow]]:
    params = {"course_id": course_id}
    return {
        "sources": conn.execute(get(_FILE, "memory_sources"), params).fetchall(),
        "concepts": conn.execute(get(_FILE, "memory_concepts"), params).fetchall(),
        "memory_objects": conn.execute(get(_FILE, "memory_objects"), params).fetchall(),
        "evidence": conn.execute(get(_FILE, "memory_evidence"), params).fetchall(),
    }
```

All sources, concepts, memory objects, and evidence are loaded at once. For a large course, this could be hundreds of MB.

**Fix:** Fetch in batches or use a cursor.

---

### H7. `get_settings()` creates a new Settings object on every call

**File:** `src/backend/common/config.py:62-82`

```python
def get_settings() -> Settings:
    _load_dotenv(PROJECT_ROOT / ".env")
    data_dir = Path(os.getenv("APP_DATA_DIR", str(DEFAULT_DATA_DIR)))
    return Settings(...)
```

`get_settings()` is called extremely frequently — from `database_path()`, `storage_root()`, `deps.py`, and many other places. Each call re-reads environment variables, re-parses the `.env` file, and constructs a new `Settings` object. This is wasteful.

**Fix:** Cache the Settings object and provide a way to reload it when needed (e.g., in tests).

---

### H8. Config files cached with `@cache` are never reloaded

**Files:**
- `src/backend/common/providers.py:96-97` — `_load_models_config`
- `src/backend/common/model_profiles.py:36-37` — `_load`
- `src/backend/common/companion_config.py:19-20` — `load_companion_policy`

```python
@cache
def _load_models_config(path: Path) -> ModelsConfig:
    ...
```

These functions are decorated with `@cache`, which means the config is loaded once per process and never reloaded. If the config file changes (e.g., during development or if the app supports hot-reload), the stale cached value is used forever.

**Fix:** Remove `@cache` or provide an explicit cache invalidation mechanism.

---

### H9. `upload_source` tries to delete the same file twice

**File:** `src/backend/common/sources_repo.py:75-131`

```python
stored_temp: Path = temp_path
...
stored_temp, stored_encoding, stored_size = storage.compress_temp_for_storage(temp_path, mime_type)
...
except BaseException:
    storage.discard_temp(temp_path)
    storage.discard_temp(stored_temp)
```

When `compress_temp_for_storage` returns the original `temp_path` (compression didn't save enough), `stored_temp` is the same object as `temp_path`. The except block then calls `discard_temp` twice on the same path. The second call uses `missing_ok=True` so it doesn't raise, but it's wasteful and confusing.

**Fix:** Check if `stored_temp is not temp_path` before calling `discard_temp(stored_temp)`.

---

### H10. `add_turn` assumes at least 2 messages are returned

**File:** `src/backend/common/conversations_repo.py:218-219`

```python
stored = [m for m in messages(conn, conversation_id) if m.seq >= seq]
return stored[0], stored[1]
```

If the conversation has no messages (which shouldn't happen but could in edge cases after a delete), `stored` will be empty and `stored[0]` will raise `IndexError`.

**Fix:** Add a guard: `if len(stored) < 2: raise RuntimeError("...")`

---

## Medium Issues

### M1. `_generate` retries on EmptyModelError without any delay

**File:** `src/backend/tutor/answer.py:369-378`

```python
def _generate(task: str, prompt: str, **options: Any) -> provider.GenerationResult:
    try:
        return provider.generate(task, prompt, **options)
    except provider.EmptyModelError:
        return provider.generate(task, prompt, **options)
    except provider.ModelOutputTruncatedError:
        return provider.generate(task, prompt + _CUT_OFF_RETRY, **options)
```

If the model consistently returns empty responses, this retries immediately with no backoff. This hammers the provider and can trigger rate limiting.

**Fix:** Add a small delay between retries, or limit the number of retries.

---

### M2. `_citations` opens a new DB connection from within a request

**File:** `src/backend/api/artifacts.py:428-435`

```python
def _citations(course_id: UUID, sources: tuple[UUID, ...]) -> list[ArtifactCitationView]:
    with connection() as conn:
        rows = conn.execute(...)
    ...
```

This is called from `export_artifact`, which may already have a connection open. While SQLite's WAL mode prevents deadlocks in most cases, opening nested connections is wasteful and can lead to lock contention.

**Fix:** Pass the existing connection as a parameter.

---

### M3. `usage_repo.record` opens a new DB connection from within a request

**File:** `src/backend/common/usage_repo.py:35-59`

```python
def record(...) -> UsageLedgerEntry:
    with connection() as conn:
        row = conn.execute(...)
        conn.commit()
    ...
```

This is called from `provider.generate`, which is called from within a request that may already have a connection open. Same issue as M2.

**Fix:** Pass the existing connection as a parameter, or use a connection pool.

---

### M4. `run_once` calls `purge_due()` without error handling

**File:** `src/backend/common/maintenance.py:17-28`

```python
def run_once(*, should_stop: Callable[[], bool] | None = None) -> tuple[int, int]:
    purged = len(courses_repo.purge_due())
    if should_stop is not None and should_stop():
        return purged, 0
    swept = courses_repo.sweep_storage_orphans(...)
    return purged, len(swept)
```

If `purge_due()` raises an exception, the entire maintenance pass fails and the orphan sweep never runs. The exception is caught by the caller (`run_forever`), but the orphan sweep is skipped.

**Fix:** Wrap each phase in its own try/except.

---

### M5. `migrate` uses `executescript` which commits pending transactions

**File:** `src/backend/common/migrate.py:60-65`

```python
conn.executescript(
    "BEGIN IMMEDIATE;\n"
    f"{script}\n"
    f"INSERT INTO schema_migrations (version) VALUES ('{version}');\n"
    "COMMIT;"
)
```

`executescript` implicitly commits any pending transaction before executing the script. If there's an open transaction with uncommitted changes, those changes are committed before the migration runs. This could lead to data loss or inconsistency.

**Fix:** Ensure no transaction is open before calling `executescript`, or use `execute` instead.

---

### M6. `source_pdf_page` doesn't handle non-integer page_number

**File:** `src/backend/api/sources.py:164-206`

```python
@router.get("/{course_id}/sources/{source_id}/pages/{page_number}")
def source_pdf_page(course_id: UUID, source_id: UUID, page_number: int) -> Response:
```

If the user passes a non-integer value for `page_number`, FastAPI returns a 422 error. But if the user passes a negative number or zero, the function handles it with a 404. This is correct, but the error message "page not found" is misleading for a negative number.

**Fix:** Add explicit validation for `page_number >= 1`.

---

### M7. `_fit_lines` can truncate a line mid-way

**File:** `src/backend/common/course_memory.py:61-83`

```python
def _fit_lines(lines: list[str], header: str, character_budget: int) -> tuple[str, int]:
    ...
    if not body and lines:
        body = [lines[0][:budget]]
        used = len(body[0])
        return "\n".join([header] + body), len(header) + used
```

When no lines fit and the first line is longer than the budget, it's truncated with `lines[0][:budget]`. This could cut a hash, locator, or other important data mid-way, making it unreadable.

**Fix:** Return just the header when no lines fit, or truncate at a word boundary.

---

### M8. `import_course` has a potential issue with `_discard`

**File:** `src/backend/common/course_archive.py:267-274`

```python
def _discard(course_id: UUID) -> None:
    courses_repo.move_to_trash(course_id)
    courses_repo.purge_course(course_id)
    with connection() as conn:
        conn.execute("DELETE FROM course_memories WHERE course_id = ?", (course_id,))
        conn.commit()
```

If `_discard` fails (e.g., due to a DB error), the course is left in an inconsistent state — it may be trashed but not purged, or purged but with the course_memory keepsake still present.

**Fix:** Wrap `_discard` in a try/except and log any failures.

---

### M9. `submit` has a recursive call that could be confusing

**File:** `src/backend/student_model/learning.py:174-178`

```python
if inserted.rowcount == 0:
    existing = rows(conn, "run", course_id=course_id, run_id=payload.run_id)
    if not existing:
        raise ValueError("this submission ID belongs to another course")
    return submit(conn, course_id, suite_id, payload)
```

This recursive call is confusing. The second call will hit the `if existing:` check at the top and return `run_view(conn, existing[0])`. This works, but it's not obvious.

**Fix:** Replace the recursive call with `return run_view(conn, existing[0])`.

---

### M10. `targets` has O(n^2) complexity

**File:** `src/backend/student_model/learning.py:258-342`

```python
for observation in rows(conn, "observations", course_id=course_id):
    grouped[(observation["topic"].casefold(), observation["capability"])].append(observation)
...
for record in rows(conn, "suites", course_id=course_id):
    for question in record["questions"]:
        topic = question.get("topic") or question["prompt"]
        known_topics.setdefault(topic.casefold(), topic)
```

The nested loops over observations and suites could be slow for large datasets. The `known_topics` construction is particularly wasteful — it iterates over all suites and all questions just to build a set of topic names.

**Fix:** Use a single query to fetch all known topics, or use a set comprehension.

---

### M11. `_usable_quiz` has complex validation logic with potential edge cases

**File:** `src/backend/tutor/compose.py:543-648`

The `_usable_quiz` function has extremely complex validation logic for quiz questions, including date validation, name matching, and option deduplication. The date validation logic in particular is very dense and hard to follow:

```python
dates = re.findall(r"\b\d{4}\b", selected)
if any(date not in evidence for date in dates):
    return False
if dates and re.search(r"\b(?:when|what year|which year)\b", prompt.casefold()):
    ...
```

This could have false positives (e.g., a question about "What is 2020?" where 2020 is not a date) or false negatives (e.g., a question about "When did WWII end?" where the answer is "1945" but the evidence says "the war ended in 1945").

**Fix:** Simplify the validation logic or add more test cases.

---

### M12. `extract_workspace_items` uses regex to parse JSON

**File:** `src/backend/tutor/workspace.py:30-33`

```python
WORKSPACE_BLOCK_RE = re.compile(
    r"```workspace[ \t]*\r?\n(.*?)(?:^```[ \t]*(?=\r?$)|\Z)",
    re.DOTALL | re.MULTILINE,
)
```

This regex extracts JSON from a fenced code block. It handles most cases, but could fail if the JSON contains a line that starts with ``` (e.g., in a string value). This is unlikely but possible.

**Fix:** Use a more robust parsing approach, or document the limitation.

---

### M13. `_normalize_layout_tables` has complex table detection heuristic

**File:** `src/backend/ingest/extract.py:462-509`

The table detection logic uses a heuristic based on column alignment. This could have false positives (e.g., justified prose with consistent word spacing) or false negatives (e.g., tables with merged cells).

**Fix:** Add more test cases and consider using a dedicated table extraction library.

---

### M14. `_overview` calls `providers.resolve` for each task class

**File:** `src/backend/api/settings.py:170-202`

```python
def _overview() -> ProvidersView:
    ...
    for cls in TaskClass:
        endpoint = providers.resolve(cls)
        ...
```

Each call to `providers.resolve` may involve multiple DB queries (e.g., `saved_choice`, `get_connection`, `secrets.get_api_key`). For 3 task classes, this is at least 9 DB queries. This could be slow.

**Fix:** Batch the queries or cache the results.

---

### M15. `course_memory.refresh` has a complex flow with multiple DB queries

**File:** `src/backend/common/course_memory.py:165-231`

The `refresh` function fetches all material, assembles a summary, fetches learning targets and experiments, and then upserts the memory node. This involves at least 6 DB queries and could be slow for large courses.

**Fix:** Consider caching or incremental updates.

---

### M16. `practice_from_saved` has a complex flow with multiple DB connections

**File:** `src/backend/api/learning.py:77-154`

The `practice_from_saved` endpoint opens a connection, then inside the `with connection()` block, it calls `learning.create_suite` which may open more connections. This is wasteful.

**Fix:** Pass the existing connection to `learning.create_suite`.

---

### M17. `send_message` has a complex flow with multiple DB connections

**File:** `src/backend/api/conversations.py:234-318`

The `send_message` endpoint opens a connection to fetch history, then opens another connection to send the message. Inside the second connection, `tutor_answer.answer_question` may open more connections.

**Fix:** Reuse the existing connection.

---

## Low Issues

### L1. `request_body` imports base64 inside the function

**File:** `src/backend/common/provider.py:242`

```python
def request_body(...) -> dict[str, Any]:
    import base64
```

The `base64` import should be at module level, not inside the function. This is called on every model generation request.

**Fix:** Move the import to the top of the file.

---

### L2. `_load_dotenv` doesn't handle quoted values properly

**File:** `src/backend/common/config.py:19-31`

```python
def _load_dotenv(path: Path) -> None:
    ...
    value = value.strip().strip('"').strip("'")
```

This strips quotes but doesn't handle escaped characters (e.g., `key="value with \"quotes\""` would be parsed incorrectly).

**Fix:** Use a proper `.env` parser or `shlex.split`.

---

### L3. `connection()` context manager doesn't explicitly rollback

**File:** `src/backend/common/db.py:107-115`

```python
@contextmanager
def connection() -> Iterator[Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
```

The docstring says "An uncommitted transaction is rolled back on close", but there's no explicit `conn.rollback()`. SQLite does rollback on close, but this is implementation-dependent.

**Fix:** Add an explicit `conn.rollback()` before `conn.close()`.

---

### L4. `check_same_thread=False` allows cross-thread usage

**File:** `src/backend/common/db.py:92`

```python
conn = sqlite3.connect(
    target,
    ...
    check_same_thread=False,
)
```

This allows the connection to be used from multiple threads, but SQLite connections are not thread-safe by default. This could lead to crashes or data corruption.

**Fix:** Remove `check_same_thread=False` or document the thread-safety requirements.

---

### L5. `course_directories` limit check is off by one

**File:** `src/backend/common/storage.py:266-281`

```python
def course_directories(*, limit: int | None = None) -> list[UUID]:
    ...
    for entry in root.iterdir():
        if limit is not None and len(directories) >= limit:
            break
        ...
        directories.append(UUID(entry.name))
```

The limit check is at the top of the loop, so if `limit` is 100 and we have 100 directories, we break before appending the 101st. This is correct, but the check could be simplified.

**Fix:** No change needed, just noting that the logic is correct but could be clearer.

---

### L6. `resolve_choice` creates a temporary Connection object

**File:** `src/backend/common/providers.py:324-356`

```python
def resolve_choice(choice: ProviderChoice) -> ResolvedProvider | None:
    connection = get_connection(choice.connection_id)
    if connection is None:
        if choice.connection is not None or choice.preset is None:
            return None
        preset_config = load_models_config().presets.get(choice.preset)
        if preset_config is None:
            return None
        connection = Connection(
            id=choice.preset, preset=choice.preset, name=preset_config.label
        )
```

This creates a temporary `Connection` object that is not saved to the database. This is inconsistent with `_ensure_connection`, which does save it.

**Fix:** Use `_ensure_connection` instead.

---

### L7. `ask` opens a DB connection inside a try block

**File:** `src/backend/api/tutor.py:95-124`

```python
@router.post("/{course_id}/ask", response_model=AnswerView)
def ask(course_id: UUID, payload: AskRequest) -> AnswerView:
    ...
    try:
        query_embedding = tutor_answer.embed_search(search) if searches else None
        with connection() as conn:
            result = tutor_answer.answer_question(...)
            conn.commit()
    except tutor_answer.NothingRelevantFoundError as err:
        ...
```

The `with connection()` is inside the try block. If `answer_question` raises an exception, the connection is closed by the context manager and SQLite rolls back. This is correct, but the `conn.commit()` at the end might not be reached if an exception occurs.

**Fix:** No change needed, just noting that the logic is correct.

---

### L8. `get_api_key` catches all exceptions

**File:** `src/backend/common/secrets.py:15-22`

```python
def get_api_key(provider: str) -> str | None:
    try:
        import keyring
        return keyring.get_password(SERVICE_NAME, provider)
    except Exception:
        logger.exception("could not read the %s key from the OS keyring", provider)
        return None
```

This catches all exceptions, including programming errors (e.g., `TypeError`). This could mask real bugs.

**Fix:** Catch only `keyring.errors.KeyringError` or similar.

---

### L9. `require_app_token` doesn't distinguish between missing and invalid tokens

**File:** `src/backend/api/deps.py:40-45`

```python
if x_app_token is None or not hmac.compare_digest(
    x_app_token.encode("utf-8"), expected.encode("utf-8")
):
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED, "missing or invalid app token"
    )
```

The error message is the same for both cases. This makes debugging harder.

**Fix:** Use different error messages for missing vs. invalid tokens.

---

### L10. `json_ids` doesn't handle non-UUID types

**File:** `src/backend/common/db.py:118-121`

```python
def json_ids(ids: Any) -> str:
    return json.dumps([str(item) for item in ids])
```

If `ids` contains non-UUID types (e.g., integers), `str(item)` might not produce a valid UUID string. This could lead to SQL errors.

**Fix:** Validate that all items are UUIDs or can be converted to UUIDs.

---

### L11. `OnnxEmbedder.encode` keeps `hidden` array in memory

**File:** `src/backend/common/encoders.py:139-156`

```python
def encode(self, texts: list[str], ...) -> np.ndarray:
    ...
    for start in range(0, len(texts), batch_size):
        encodings = self._tokenizer.encode_batch(texts[start : start + batch_size])
        hidden = self._session.run(None, _feeds(self._session, encodings))[0]
        vectors = hidden[:, 0, :].astype(np.float32)
        ...
        batches.append(vectors)
    return np.concatenate(batches) if batches else np.zeros((0, 0), np.float32)
```

The `hidden` array (the full model output) is kept in memory until the next iteration. For long texts, this could be large.

**Fix:** Delete `hidden` after extracting `vectors`: `del hidden`.

---

### L12. `import_work` uses `chunk_map.setdefault` which could create random UUIDs

**File:** `src/backend/common/work_archive.py:84-89`

```python
for citation in reply["citations"]:
    cid = UUID(citation["chunk_id"])
    sid = UUID(citation["source_id"]) if citation["source_id"] else None
    citation["chunk_id"] = str(chunk_map.setdefault(cid, uuid4()))
    mapped_source = source_map.get(sid) if sid else None
    citation["source_id"] = str(mapped_source) if mapped_source else None
```

If a chunk_id is not in `chunk_map`, `setdefault` creates a new random UUID. This could lead to citations pointing to non-existent chunks.

**Fix:** Raise an error if a chunk_id is not in `chunk_map`.

---

### L13. `import_notebook` uses `chunk_map[chunk]` which could raise KeyError

**File:** `src/backend/common/archive_notebook.py:355`

```python
mapped = [str(chunk_map[chunk]) for chunk in artifact.sources]
```

If an artifact source is not in `chunk_map`, this raises `KeyError`. The `chunk_map` is pre-populated with all cited_ids from the notebook, which should include artifact sources. But if there's a bug in the cited_ids construction, this could fail.

**Fix:** Use `chunk_map.get(chunk, chunk)` to fall back to the original chunk_id.

---

### L14. `practice_from_saved` has a complex validation

**File:** `src/backend/api/learning.py:77-154`

The validation logic for `practice_from_saved` is complex and hard to follow. The `bool(payload.message_id) == bool(payload.artifact_id)` check is correct but confusing.

**Fix:** Add comments explaining the validation logic.

---

### L15. `proficient_items` has `ge=5` but no upper bound

**File:** `src/backend/common/learning_config.py:16`

```python
proficient_items: int = Field(ge=5)
```

There's no upper bound on `proficient_items`. If it's set to a very large number (e.g., 1000), the proficiency system would be useless.

**Fix:** Add an upper bound: `Field(ge=5, le=100)`.

---

### L16. `_assemble_summary` can truncate the header

**File:** `src/backend/common/course_memory.py:61-83`

```python
def _fit_lines(lines: list[str], header: str, character_budget: int) -> tuple[str, int]:
    if character_budget < len(header):
        return header[: max(character_budget, 0)], min(
            len(header), max(character_budget, 0)
        )
```

If `character_budget` is less than the header length, the header is truncated. This could produce a malformed summary.

**Fix:** Return an empty string if the budget is too small for the header.

---

### L17. `reveal` uses `target.resolve()` which could resolve symlinks

**File:** `src/backend/api/data.py:158-167`

```python
@router.post("/settings/reveal", status_code=status.HTTP_204_NO_CONTENT)
def reveal(payload: RevealRequest) -> None:
    ...
    target = Path(payload.path)
    roots = [Path(settings.data_dir), Path(settings.export_dir)]
    if not target.exists() or not any(_is_within(target, root) for root in roots):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "nothing to show there")
    _open_in_file_manager(target.resolve())
```

The `_is_within` function resolves symlinks, so the check is safe. But `target.resolve()` is called again in `_open_in_file_manager`, which is redundant.

**Fix:** Resolve once and pass the resolved path.

---

### L18. `ensure_files` doesn't verify sha256 for files without size

**File:** `src/backend/common/encoders.py:55-79`

(Already covered in C2, but worth noting again as a low-priority issue if the files are small.)

---

### L19. `OnnxCrossEncoder.predict` doesn't handle empty pairs

**File:** `src/backend/common/encoders.py:167-177`

```python
def predict(self, pairs: list[tuple[str, str]], batch_size: int = 16) -> list[float]:
    scores: list[float] = []
    for start in range(0, len(pairs), batch_size):
        ...
    return scores
```

If `pairs` is empty, this returns an empty list. The caller (`rerank_scores`) handles this case, but it's worth noting.

**Fix:** Add an early return for empty pairs.

---

### L20. `compose_chat` doesn't handle empty course_name

**File:** `src/backend/tutor/compose.py:838-857`

```python
def compose_chat(
    question: str,
    generate: Generate,
    *,
    conversation: str = "",
    course_name: str = "",
    teaching: str = "",
) -> str:
    parts: list[str] = []
    if course_name:
        parts.append(f"The student is studying: {course_name}")
    ...
```

If `course_name` is empty, the prompt doesn't include the course name. This is correct, but the model might benefit from knowing the course name even if it's empty.

**Fix:** No change needed, just noting the behavior.

---

## Additional Observations

### Positive aspects

1. **Good documentation:** The codebase is well-documented with docstrings and comments explaining the "why" behind decisions.
2. **Consistent patterns:** The codebase follows consistent patterns for DB access, error handling, and API design.
3. **Security-conscious:** The codebase has good security practices — path traversal prevention, decompression limits, prompt injection fencing, and API token authentication.
4. **Test coverage:** There's a substantial test suite (~50 test files).
5. **Versioned configs:** Using versioned TOML configs for prompts, retrieval, and other policies is a good practice.

### Areas for improvement

1. **Connection management:** The codebase opens many short-lived DB connections. Consider using a connection pool or reusing connections within a request.
2. **Caching:** Several functions are called frequently with the same arguments (e.g., `get_settings()`, `load_models_config()`). Consider caching with invalidation.
3. **Error handling:** Some functions catch too broad exceptions (e.g., `except Exception`), which can mask bugs.
4. **Memory usage:** Several functions load large datasets into memory. Consider streaming or batching.
5. **Type safety:** The codebase uses type hints consistently, which is good. Consider using a stricter type checker (e.g., `mypy` in strict mode).

---

## Conclusion

This is a well-architected codebase with good documentation and security practices. However, there are numerous bugs and issues that need to be addressed, particularly around memory management, connection handling, and config caching. The critical issues (C1-C3) should be fixed immediately, followed by the high-priority issues (H1-H10).

The codebase would benefit from:
- A connection pool or request-scoped connection management
- Bounded caches for config files and adaptations
- Streaming file I/O for large files
- More specific exception handling
- Better test coverage for edge cases

---

*End of review.*
