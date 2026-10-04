"""Model files on this machine: where they live, which catalog models are
installed, and background downloads with live progress.

Files the user already has are reused instead of downloaded again: a GGUF
with the catalog's exact name and size in LM Studio's or Hugging Face's
cache is verified against the pinned sha256 once, and the verification is
remembered (keyed by path, size and mtime) so it never re-hashes."""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.backend.common import settings_repo
from src.backend.common.config import get_settings
from src.backend.runtime import user_models
from src.backend.runtime.config import CatalogModel
from src.backend.runtime.downloads import (
    DownloadCancelled,
    download_verified,
    sha256_of,
)

logger = logging.getLogger(__name__)

VERIFIED_SETTING = "runtime.verified_external_models"
_verification_lock = threading.RLock()


def models_dir() -> Path:
    return Path(get_settings().data_dir) / "models"


def owned_path(model: CatalogModel) -> Path:
    identity = hashlib.sha256(model.id.encode()).hexdigest()[:16]
    return models_dir() / f"{identity}-{model.sha256}" / Path(model.file).name


def _external_roots() -> list[Path]:
    home = Path.home()
    return [
        home / ".lmstudio" / "models",
        home / ".cache" / "huggingface" / "hub",
    ]


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"


def _external_candidates(model: CatalogModel) -> list[Path]:
    """Same-name, same-size files in other apps' model folders."""
    found: list[Path] = []
    for root in _external_roots():
        if root.is_dir():
            found.extend(
                candidate
                for candidate in root.rglob(Path(model.file).name)
                if candidate.is_file() and candidate.stat().st_size == model.size_bytes
            )
    return found


def locate(model: CatalogModel, *, verify: bool) -> tuple[Path | None, str]:
    """Where a catalog model's file is: ("app" | "external" |
    "external-unverified" | "missing"). `verify=True` hashes an external
    candidate once (seconds for a multi-GB file) and remembers the result;
    `verify=False` stays instant, for listings. A model the user added from
    a file on this computer is used where it is, if it is unchanged."""
    if model.local_path is not None:
        return _added_local_file(model, verify=verify)
    own = owned_path(model)
    if (
        own.is_file()
        and own.stat().st_size == model.size_bytes
        and (not verify or _verified(own, model))
    ):
        return own, "app"
    legacy = models_dir() / Path(model.file).name
    if (
        legacy.is_file()
        and legacy.stat().st_size == model.size_bytes
        and (not verify or _verified(legacy, model))
    ):
        return legacy, "app"
    remembered: dict[str, Any] = settings_repo.get_setting(VERIFIED_SETTING, {}) or {}
    unverified: Path | None = None
    for candidate in _external_candidates(model):
        record = {"sha256": model.sha256, "fingerprint": _fingerprint(candidate)}
        if remembered.get(str(candidate)) == record:
            return candidate, "external"
        if not verify:
            unverified = unverified or candidate
            continue
        if sha256_of(candidate) == model.sha256:
            remembered[str(candidate)] = record
            with _verification_lock:
                latest = settings_repo.get_setting(VERIFIED_SETTING, {}) or {}
                latest[str(candidate)] = record
                settings_repo.put_setting(VERIFIED_SETTING, latest)
            return candidate, "external"
    if unverified is not None:
        return unverified, "external-unverified"
    return None, "missing"


def _verified(path: Path, model: CatalogModel) -> bool:
    before = _fingerprint(path)
    record = {"sha256": model.sha256, "fingerprint": before}
    remembered = settings_repo.get_setting(VERIFIED_SETTING, {}) or {}
    if remembered.get(str(path)) == record:
        return True
    if sha256_of(path) != model.sha256 or _fingerprint(path) != before:
        return False
    with _verification_lock:
        latest = settings_repo.get_setting(VERIFIED_SETTING, {}) or {}
        latest[str(path)] = record
        settings_repo.put_setting(VERIFIED_SETTING, latest)
    return True


def _added_local_file(model: CatalogModel, *, verify: bool) -> tuple[Path | None, str]:
    assert model.local_path is not None
    path = Path(model.local_path)
    if (
        path.is_file()
        and path.stat().st_size == model.size_bytes
        and (not verify or _verified(path, model))
    ):
        return path, "external"
    return None, "missing"


def installed_path(model: CatalogModel) -> Path | None:
    """A verified file for this model, or None."""
    path, where = locate(model, verify=True)
    return path if where in ("app", "external") else None


@dataclass
class DownloadState:
    model_id: str
    total: int
    done: int = 0
    status: str = "downloading"  # downloading | verifying | done | failed | cancelled
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


_downloads: dict[str, DownloadState] = {}
_lock = threading.Lock()


def download_status(model_id: str) -> DownloadState | None:
    with _lock:
        return _downloads.get(model_id)


def start_download(model_id: str) -> DownloadState:
    """Start (or return the running) background download for a model. A
    model added from a local file has nothing to download."""
    model = user_models.find_model(model_id)
    if model is None or model.local_path is not None:
        raise KeyError(model_id)
    with _lock:
        existing = _downloads.get(model_id)
        if existing is not None and existing.status in ("downloading", "verifying"):
            return existing
        state = DownloadState(model_id=model_id, total=model.size_bytes)
        _downloads[model_id] = state
    threading.Thread(
        target=_run_download,
        args=(model, state),
        name=f"download-{model_id}",
        daemon=True,
    ).start()
    return state


def cancel_download(model_id: str) -> None:
    with _lock:
        state = _downloads.get(model_id)
        if state is not None:
            state.cancel.set()


def _run_download(model: CatalogModel, state: DownloadState) -> None:
    def progress(done: int, total: int) -> None:
        state.done = done
        if done >= total:
            state.status = "verifying"

    try:
        download_verified(
            model.download_url,
            owned_path(model),
            sha256=model.sha256,
            size_bytes=model.size_bytes,
            progress=progress,
            cancel=state.cancel,
        )
        state.done = state.total
        state.status = "done"
    except DownloadCancelled:
        state.status = "cancelled"
    except Exception as err:
        logger.exception("model download failed: %s", model.id)
        state.status = "failed"
        state.error = str(err)


def delete_model(model: CatalogModel) -> bool:
    """Delete the app's own copy (never a file in another app's folder)."""
    own = owned_path(model)
    legacy = models_dir() / Path(model.file).name
    removed = False
    paths = [own, own.with_name(own.name + ".part")]
    if legacy.is_file() and sha256_of(legacy) == model.sha256:
        paths.append(legacy)
    # Hold the lock across the check and the deletion so a concurrent
    # start_download cannot slip a fresh DownloadState (and writes) in
    # between the guard and the unlink.
    with _lock:
        state = _downloads.get(model.id)
        if state is not None and state.status in ("downloading", "verifying"):
            raise ValueError("Cancel the download before removing this model.")
        _downloads.pop(model.id, None)
        for path in paths:
            if path.exists():
                path.unlink()
                removed = True
    return removed
