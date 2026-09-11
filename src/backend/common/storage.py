"""File storage for uploaded course sources.

Security invariants:
- Uploads stream to disk under a tier-specific raw-body ceiling; an oversized
  body is cut mid-stream and never fully enters memory. Stored-byte quotas are
  checked after optional compression.
- Disk names are server-generated (`source_id`); user filenames are sanitized
  for display only, so path traversal is structurally impossible.
- The database is the accounting truth. `size_bytes` always records the bytes
  actually stored (post-compression), and every write happens in one
  transaction; a failure after the file is written removes the orphan.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import shutil
import tempfile
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from src.backend.common.config import get_settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
COMPRESSION_LEVEL = 6
COMPRESSION_MIN_SAVINGS_PERCENT = 10

_COMPRESSIBLE_PREFIXES = ("text/",)
_COMPRESSIBLE_EXACT = {
    "application/json",
    "application/xml",
    "application/yaml",
    "application/toml",
    "text/csv",
    "text/markdown",
}
_INCOMPRESSIBLE_PREFIXES = ("image/", "video/", "audio/")
_INCOMPRESSIBLE_EXACT = {
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-gzip",
    "application/x-7z-compressed",
    "application/vnd.rar",
    "application/octet-stream",
}


class RawUploadLimitExceededError(RuntimeError):
    """The request body exceeded the raw per-request upload ceiling. This is
    a body-size rejection (413), distinct from budget.StorageLimitExceededError,
    which is a quota rejection (403) against stored bytes."""

    def __init__(self, allowed_bytes: int, received_bytes: int) -> None:
        self.allowed_bytes = allowed_bytes
        self.received_bytes = received_bytes
        super().__init__(
            f"upload exceeds the per-request raw body ceiling: "
            f"{received_bytes} bytes received, {allowed_bytes} allowed"
        )


class EmptyUploadError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("uploaded file is empty")


class DecompressionLimitExceededError(RuntimeError):
    """A stored file expanded past the configured decompression ceiling while
    being read back. Not a quota rejection — the stored bytes passed quota at
    upload time; this is a read-time safety cap so no parser can expand a
    stored file unboundedly."""

    def __init__(
        self, source_id: UUID, allowed_bytes: int, expanded_bytes: int
    ) -> None:
        self.source_id = source_id
        self.allowed_bytes = allowed_bytes
        self.expanded_bytes = expanded_bytes
        super().__init__(
            f"stored source {source_id} expands past the decompression "
            f"ceiling: {expanded_bytes}+ bytes produced, {allowed_bytes} allowed"
        )


def storage_root() -> Path:
    root = Path(get_settings().storage_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def source_disk_path(course_id: UUID, source_id: UUID) -> Path:
    return storage_root() / str(course_id) / f"{source_id}.bin"


def stream_to_temp(
    stream: BinaryIO,
    *,
    max_bytes: int,
    chunk_size: int = CHUNK_SIZE,
) -> tuple[Path, str, int]:
    """Stream the request body into a temp file while hashing it.

    Returns (temp_path, sha256_hex, byte_count). Raises StorageLimitExceeded
    mid-stream when the ceiling is exceeded, and EmptyUploadError for a
    zero-byte body. The temp file is removed on any failure; on success the
    caller owns it and must discard it via discard_temp()."""
    digest = hashlib.sha256()
    received = 0
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed in try/with below
        prefix="upload-", suffix=".tmp", delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                received += len(chunk)
                if received > max_bytes:
                    raise RawUploadLimitExceededError(max_bytes, received)
                digest.update(chunk)
                handle.write(chunk)
        if received == 0:
            raise EmptyUploadError()
        return temp_path, digest.hexdigest(), received
    except BaseException:
        discard_temp(temp_path)
        raise


def discard_temp(temp_path: Path) -> None:
    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove temp upload %s", temp_path)


def is_compressible(mime_type: str) -> bool:
    if any(mime_type.startswith(prefix) for prefix in _INCOMPRESSIBLE_PREFIXES):
        return False
    if mime_type in _INCOMPRESSIBLE_EXACT:
        return False
    return any(mime_type.startswith(p) for p in _COMPRESSIBLE_PREFIXES) or (
        mime_type in _COMPRESSIBLE_EXACT
    )


def compress_for_storage(data: bytes, mime_type: str) -> tuple[bytes, str]:
    """gzip only when both the mimetype allows it and it saves >=10%.
    Returns (stored_bytes, encoding) with encoding in {'identity', 'gzip'}.
    PDFs/images/video are skipped: gzip gains near zero on them."""
    if not data or not is_compressible(mime_type):
        return data, "identity"
    compressed = gzip.compress(data, compresslevel=COMPRESSION_LEVEL)
    savings = 100 - (len(compressed) * 100) // len(data)
    if savings >= COMPRESSION_MIN_SAVINGS_PERCENT:
        return compressed, "gzip"
    return data, "identity"


def compress_temp_for_storage(temp_path: Path, mime_type: str) -> tuple[Path, str, int]:
    original_size = temp_path.stat().st_size
    if original_size == 0 or not is_compressible(mime_type):
        return temp_path, "identity", original_size
    compressed_path: Path | None = None
    try:
        with (
            tempfile.NamedTemporaryFile(
                prefix="upload-compressed-", suffix=".tmp", delete=False
            ) as handle,
            temp_path.open("rb") as source,
            gzip.GzipFile(
                fileobj=handle, mode="wb", compresslevel=COMPRESSION_LEVEL
            ) as target,
        ):
            compressed_path = Path(handle.name)
            shutil.copyfileobj(source, target, length=CHUNK_SIZE)
        compressed_size = compressed_path.stat().st_size
        savings = 100 - (compressed_size * 100) // original_size
        if savings < COMPRESSION_MIN_SAVINGS_PERCENT:
            discard_temp(compressed_path)
            return temp_path, "identity", original_size
        discard_temp(temp_path)
        return compressed_path, "gzip", compressed_size
    except BaseException:
        if compressed_path is not None:
            discard_temp(compressed_path)
        raise


def _atomic_write(path: Path, source: BinaryIO) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            staging_path = Path(handle.name)
            shutil.copyfileobj(source, handle, length=CHUNK_SIZE)
        staging_path.replace(path)
    except BaseException:
        if staging_path is not None:
            discard_temp(staging_path)
        raise


def write_stored(course_id: UUID, source_id: UUID, data: bytes) -> Path:
    """Write final stored bytes to the canonical path. The parent course
    directory is created only here."""
    path = source_disk_path(course_id, source_id)
    _atomic_write(path, BytesIO(data))
    return path


def write_stored_from_temp(
    course_id: UUID, source_id: UUID, temp_path: Path
) -> Path:
    path = source_disk_path(course_id, source_id)
    with temp_path.open("rb") as source:
        _atomic_write(path, source)
    discard_temp(temp_path)
    return path


def copy_stored(
    source_course_id: UUID,
    source_id: UUID,
    target_course_id: UUID,
    target_source_id: UUID,
) -> Path:
    source_path = source_disk_path(source_course_id, source_id)
    target_path = source_disk_path(target_course_id, target_source_id)
    with source_path.open("rb") as source:
        _atomic_write(target_path, source)
    return target_path


def remove_course_directory(course_id: UUID) -> None:
    path = storage_root() / str(course_id)
    if path.exists():
        shutil.rmtree(path)


def course_source_files(course_id: UUID) -> list[tuple[UUID, Path]]:
    """Stored .bin files for a course directory, parsed as (source_id, path).
    Staging debris (.{uuid}-*.tmp) and other non-UUID names are not returned."""
    course_dir = storage_root() / str(course_id)
    if not course_dir.is_dir():
        return []
    files: list[tuple[UUID, Path]] = []
    for entry in course_dir.iterdir():
        if not entry.is_file() or _is_staging_name(entry.name):
            continue
        try:
            files.append((UUID(entry.stem), entry))
        except ValueError:
            logger.warning(
                "non-source file in course directory %s: %s",
                course_id,
                entry.name,
            )
    return files


def _is_staging_name(name: str) -> bool:
    """Matches NamedTemporaryFile staging writes: .{source_id}-{rand}.tmp."""
    return name.startswith(".") and name.endswith(".tmp")


def course_staging_files(course_id: UUID) -> list[Path]:
    """Interrupted _atomic_write staging files in a course directory. A
    staging file older than the sweep grace is debris by construction: an
    in-flight write is always seconds old."""
    course_dir = storage_root() / str(course_id)
    if not course_dir.is_dir():
        return []
    return [
        entry
        for entry in course_dir.iterdir()
        if entry.is_file() and _is_staging_name(entry.name)
    ]


def course_directories(*, limit: int | None = None) -> list[UUID]:
    """Server-generated UUID directory names under the storage root. Any
    entry that is not a bare UUID is foreign (operator files, staging
    debris) and is not returned, so sweeps never touch what they don't own."""
    root = storage_root()
    directories: list[UUID] = []
    for entry in root.iterdir():
        if limit is not None and len(directories) >= limit:
            break
        if not entry.is_dir():
            continue
        try:
            directories.append(UUID(entry.name))
        except ValueError:
            logger.warning("non-course directory in storage root: %s", entry.name)
    return directories


def remove_stored(course_id: UUID, source_id: UUID) -> None:
    path = source_disk_path(course_id, source_id)
    path.unlink(missing_ok=True)
    with suppress(OSError):
        path.parent.rmdir()


def read_stored(
    course_id: UUID,
    source_id: UUID,
    stored_encoding: str | None,
    *,
    max_decompressed_bytes: int,
) -> bytes:
    """Read a stored file back, decompressing in bounded chunks. The
    decompression ceiling is mandatory (the whole-buffer read this replaces
    is the seam a zip-bomb would exploit); identity-encoded files are capped
    at their on-disk size. Callers resolve the cap from the versioned
    lifecycle policy; the policy value must stay >= every tier's raw upload
    ceiling, which test_config.py pins."""
    path = source_disk_path(course_id, source_id)
    if stored_encoding != "gzip":
        expanded = path.stat().st_size
        if expanded > max_decompressed_bytes:
            raise DecompressionLimitExceededError(
                source_id, max_decompressed_bytes, expanded
            )
        return path.read_bytes()
    produced = 0
    parts: list[bytes] = []
    try:
        with path.open("rb") as raw_stream, gzip.GzipFile(fileobj=raw_stream) as gunzip:
            while True:
                chunk = gunzip.read(CHUNK_SIZE)
                if not chunk:
                    break
                produced += len(chunk)
                if produced > max_decompressed_bytes:
                    raise DecompressionLimitExceededError(
                        source_id, max_decompressed_bytes, produced
                    )
                parts.append(chunk)
    except (EOFError, gzip.BadGzipFile) as error:
        raise ValueError(f"stored gzip stream is corrupt: {source_id}") from error
    return b"".join(parts)


def sanitize_display_name(name: str) -> str:
    stripped = Path(name.replace("\\", "/")).name.strip()
    if not stripped or stripped in {".", ".."}:
        return "upload"
    return stripped[:255]
