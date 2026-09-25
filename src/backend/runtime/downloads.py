"""Resumable, checksum-verified downloads for model files and the
llama.cpp runtime. A file only ever reaches its final path after its
sha256 matches the pinned value; a partial download is kept as `.part`
and resumed with an HTTP Range request."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from pathlib import Path

import httpx

CHUNK_BYTES = 1 << 20

ProgressFn = Callable[[int, int], None]


class DownloadError(RuntimeError):
    pass


class DownloadCancelled(DownloadError):  # noqa: N818 - reads as an event
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def download_verified(
    url: str,
    dest: Path,
    *,
    sha256: str,
    size_bytes: int,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download `url` to `dest`, resuming a previous partial download,
    and verify it. Raises DownloadError on a checksum mismatch (the bad
    file is deleted so the next attempt starts clean)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == size_bytes:
        return dest
    part = dest.with_name(dest.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    if done > size_bytes:
        part.unlink()
        done = 0
    if done < size_bytes:
        headers = {"Range": f"bytes={done}-"} if done else {}
        with httpx.stream(
            "GET",
            url,
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=15.0),
        ) as response:
            if done and response.status_code != 206:
                done = 0  # server ignored the range: start over
            response.raise_for_status()
            with part.open("ab" if done else "wb") as handle:
                for block in response.iter_bytes(CHUNK_BYTES):
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled(f"cancelled: {dest.name}")
                    handle.write(block)
                    done += len(block)
                    if progress is not None:
                        progress(done, size_bytes)
    if part.stat().st_size != size_bytes:
        raise DownloadError(
            f"{dest.name}: expected {size_bytes} bytes, got {part.stat().st_size}"
        )
    actual = sha256_of(part)
    if actual != sha256:
        part.unlink()
        raise DownloadError(f"{dest.name}: checksum mismatch ({actual})")
    part.replace(dest)
    return dest
