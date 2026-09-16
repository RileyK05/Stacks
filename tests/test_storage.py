import io
import os
from uuid import uuid4

import pytest
from src.backend.common import storage
from src.backend.common.lifecycle_config import load_lifecycle_policy


@pytest.fixture(autouse=True)
def _temp_uploads(monkeypatch, tmp_path_factory):
    import tempfile

    base = os.path.join(os.environ.get("TEMP", "/tmp"), "course-proj-uploads")
    os.makedirs(base, exist_ok=True)
    tempfile.tempdir = base
    yield
    for leftover in os.listdir(base):
        if leftover.startswith("upload-"):
            os.unlink(os.path.join(base, leftover))


def test_stream_hashes_and_counts() -> None:
    data = b"hello course materials" * 100
    path, digest, count = storage.stream_to_temp(
        io.BytesIO(data), max_bytes=10_000
    )
    try:
        import hashlib

        assert digest == hashlib.sha256(data).hexdigest()
        assert count == len(data)
        assert path.read_bytes() == data
    finally:
        storage.discard_temp(path)


def test_stream_cuts_off_at_ceiling() -> None:
    data = b"x" * 2000
    with pytest.raises(storage.RawUploadLimitExceededError):
        storage.stream_to_temp(io.BytesIO(data), max_bytes=100)


def test_stream_rejects_empty() -> None:
    with pytest.raises(storage.EmptyUploadError):
        storage.stream_to_temp(io.BytesIO(b""), max_bytes=100)


def test_compressible_text_gzips() -> None:
    data = b"the quick brown fox " * 500
    stored, encoding = storage.compress_for_storage(data, "text/plain")
    assert encoding == "gzip"
    assert len(stored) < len(data) // 2
    import gzip

    assert gzip.decompress(stored) == data


def test_incompressible_mime_skips_gzip() -> None:
    data = b"%PDF-1.4 fake pdf bytes " * 100
    stored, encoding = storage.compress_for_storage(data, "application/pdf")
    assert encoding == "identity"
    assert stored == data


def test_compressible_but_inefficient_stays_identity() -> None:
    import random

    rng = random.Random(42)
    data = bytes(rng.getrandbits(8) for _ in range(16384))
    stored, encoding = storage.compress_for_storage(data, "application/json")
    assert encoding == "identity"
    assert stored == data


def test_temp_file_compression_streams_and_replaces_input() -> None:
    data = b"large course notes " * 100_000
    original, _, _ = storage.stream_to_temp(
        io.BytesIO(data), max_bytes=len(data) + 1
    )
    stored_path, encoding, stored_size = storage.compress_temp_for_storage(
        original, "text/plain"
    )
    try:
        assert encoding == "gzip"
        assert stored_size == stored_path.stat().st_size
        assert stored_size < len(data) // 2
        assert not original.exists()
        import gzip

        with gzip.open(stored_path, "rb") as stored:
            assert stored.read() == data
    finally:
        storage.discard_temp(stored_path)


def test_write_and_read_roundtrip_with_gzip() -> None:
    from uuid import uuid4

    course_id = uuid4()
    source_id = uuid4()
    data = b"stored content " * 100
    stored, encoding = storage.compress_for_storage(data, "text/plain")
    path = storage.write_stored(course_id, source_id, stored)
    try:
        assert path.exists()
        assert (
            storage.read_stored(
                course_id,
                source_id,
                encoding,
                max_decompressed_bytes=load_lifecycle_policy().max_decompressed_bytes,
            )
            == data
        )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_sanitize_display_name_blocks_traversal() -> None:
    assert storage.sanitize_display_name("../../.env") == ".env"
    assert storage.sanitize_display_name("..\\..\\secret.pdf") == "secret.pdf"
    assert storage.sanitize_display_name("") == "upload"
    assert storage.sanitize_display_name("..") == "upload"


def test_remove_course_directory(monkeypatch) -> None:
    import shutil
    import uuid as uuid_module

    sandbox = os.path.join(
        os.environ.get("TEMP", "/tmp"), f"course-proj-{uuid4().hex}"
    )
    os.makedirs(sandbox, exist_ok=True)
    monkeypatch.setattr(
        "src.backend.common.config.get_settings",
        lambda: type("S", (), {"storage_root": sandbox})(),
    )
    course_id = uuid_module.uuid4()
    target = storage.write_stored(course_id, uuid_module.uuid4(), b"x")
    try:
        assert target.exists()
        storage.remove_course_directory(course_id)
        assert not os.path.exists(os.path.join(sandbox, str(course_id)))
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_gzip_read_blocked_at_decompression_ceiling() -> None:
    course_id = uuid4()
    source_id = uuid4()
    data = b"x" * 10_000_000
    stored, encoding = storage.compress_for_storage(data, "text/plain")
    assert encoding == "gzip"
    assert len(stored) < len(data) // 10
    path = storage.write_stored(course_id, source_id, stored)
    try:
        with pytest.raises(storage.DecompressionLimitExceededError):
            storage.read_stored(
                course_id, source_id, encoding, max_decompressed_bytes=1_000_000
            )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_identity_read_blocked_at_decompression_ceiling() -> None:
    course_id = uuid4()
    source_id = uuid4()
    data = b"y" * 2_000_000
    path = storage.write_stored(course_id, source_id, data)
    try:
        with pytest.raises(storage.DecompressionLimitExceededError):
            storage.read_stored(
                course_id, source_id, "identity", max_decompressed_bytes=1_000_000
            )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_gzip_read_allows_exactly_at_ceiling() -> None:
    course_id = uuid4()
    source_id = uuid4()
    data = b"z" * 500_000
    stored, encoding = storage.compress_for_storage(data, "text/plain")
    path = storage.write_stored(course_id, source_id, stored)
    try:
        assert (
            storage.read_stored(
                course_id, source_id, encoding, max_decompressed_bytes=500_000
            )
            == data
        )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_corrupt_gzip_raises_value_error() -> None:
    course_id = uuid4()
    source_id = uuid4()
    path = storage.write_stored(course_id, source_id, b"not gzip")
    try:
        with pytest.raises(ValueError):
            storage.read_stored(
                course_id, source_id, "gzip", max_decompressed_bytes=1_000_000
            )
    finally:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_corrupt_deflate_body_reads_as_value_error() -> None:
    """A valid gzip header with a garbage payload is the likeliest real
    corruption, and it raises zlib.error — neither BadGzipFile nor EOFError.
    It must still surface as the documented ValueError, not leak out raw."""
    import gzip as gzip_module

    good = gzip_module.compress(b"course notes " * 5000)
    corrupt = good[:12] + bytes(b ^ 0xFF for b in good[12:-8]) + good[-8:]
    course_id, source_id = uuid4(), uuid4()
    path = storage.source_disk_path(course_id, source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(corrupt)
    with pytest.raises(ValueError, match="corrupt"):
        storage.read_stored(
            course_id, source_id, "gzip", max_decompressed_bytes=10_000_000
        )


def test_sanitize_display_name_strips_nul_bytes() -> None:
    """Postgres text columns reject NUL outright, so a filename carrying one
    turned an ordinary upload into a 500 from inside the insert."""
    assert storage.sanitize_display_name("a\x00b.pdf") == "ab.pdf"
    assert storage.sanitize_display_name("\x00") == "upload"
