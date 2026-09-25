"""Models the user adds themselves (docs/plan-notebook.md §4.8): a GGUF
from a Hugging Face link, or a `.gguf` file already on this computer.

An added model becomes one more catalog entry (stored in app_settings), so
download, checksum, reuse, start and delete work exactly as for the
built-in catalog. Hugging Face publishes each file's sha256 and size, so a
download is verified like any other; a local file is hashed once when it
is added. Whether the bundled llama.cpp build can *run* the model is only
known when it starts — the start error says so plainly.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from src.backend.common import settings_repo
from src.backend.runtime.config import CatalogModel, Tier, load_runtime_config
from src.backend.runtime.downloads import sha256_of

SETTING = "runtime.user_models"
HF_HOST = "huggingface.co"
_REPO_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SLUG = re.compile(r"[^a-z0-9.]+")
# RAM a GGUF needs beyond its own size (context, runtime, the OS).
_RAM_HEADROOM_GB = 2.0

HttpGet = Callable[[str], Any]


class AddModelError(ValueError):
    """The link or file can't be added; the message says why."""


@dataclass(frozen=True)
class GgufFile:
    file: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class HuggingFaceLink:
    repo: str
    revision: str
    file: str | None


def _http_get(url: str) -> Any:
    response = httpx.get(url, timeout=httpx.Timeout(20.0), follow_redirects=True)
    response.raise_for_status()
    return response.json()


def user_models() -> list[CatalogModel]:
    raw: Any = settings_repo.get_setting(SETTING) or []
    return [CatalogModel.model_validate(item) for item in raw]


def all_models() -> list[CatalogModel]:
    return [*load_runtime_config().models, *user_models()]


def find_model(model_id: str) -> CatalogModel | None:
    return next((m for m in all_models() if m.id == model_id), None)


def parse_link(url: str) -> HuggingFaceLink:
    """`huggingface.co/<org>/<repo>` (pick a file next) or a link to one
    file (`…/blob/<rev>/<file>.gguf` or `…/resolve/<rev>/<file>.gguf`)."""
    parsed = urlparse(url.strip() if "://" in url else f"https://{url.strip()}")
    if parsed.hostname not in (HF_HOST, f"www.{HF_HOST}"):
        raise AddModelError("paste a huggingface.co link to a GGUF model")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or not all(_REPO_PART.match(p) for p in parts[:2]):
        raise AddModelError("that link doesn't name a Hugging Face model repository")
    repo = f"{parts[0]}/{parts[1]}"
    if len(parts) >= 5 and parts[2] in ("blob", "resolve"):
        file = "/".join(parts[4:])
        if not file.lower().endswith(".gguf"):
            raise AddModelError("that link points to a file that isn't a .gguf model")
        return HuggingFaceLink(repo=repo, revision=parts[3], file=file)
    return HuggingFaceLink(repo=repo, revision="main", file=None)


def gguf_files(
    link: HuggingFaceLink, http_get: HttpGet | None = None
) -> list[GgufFile]:
    """The repository's GGUF files with their published sha256 and size."""
    fetch = http_get or _http_get
    directory = link.file.rsplit("/", 1)[0] if link.file and "/" in link.file else ""
    url = f"https://{HF_HOST}/api/models/{link.repo}/tree/{quote(link.revision)}" + (
        f"/{quote(directory)}" if directory else ""
    )
    try:
        entries = fetch(url)
    except httpx.HTTPStatusError as err:
        if err.response.status_code in (401, 403, 404):
            raise AddModelError(
                "Hugging Face didn't find that repository (it may be private or gated)"
            ) from err
        raise AddModelError(
            f"Hugging Face answered {err.response.status_code}"
        ) from err
    except (httpx.HTTPError, ValueError) as err:
        raise AddModelError(f"couldn't reach Hugging Face: {err}") from err
    files: list[GgufFile] = []
    for entry in entries if isinstance(entries, list) else []:
        path = str(entry.get("path", ""))
        lfs = entry.get("lfs") or {}
        sha = str(lfs.get("oid", ""))
        if path.lower().endswith(".gguf") and re.fullmatch(r"[0-9a-f]{64}", sha):
            files.append(
                GgufFile(
                    file=path,
                    size_bytes=int(lfs.get("size") or entry["size"]),
                    sha256=sha,
                )
            )
    return sorted(files, key=lambda f: f.size_bytes)


def _tier(size_bytes: int) -> Tier:
    gigabytes = size_bytes / 1e9
    if gigabytes < 2.5:
        return "starter"
    if gigabytes < 5.5:
        return "standard"
    return "large"


def _new_id(file: str) -> str:
    stem = Path(file).name.removesuffix(".gguf").removesuffix(".GGUF")
    base = _SLUG.sub("-", stem.lower()).strip("-") or "model"
    taken = {m.id for m in all_models()}
    candidate, counter = base, 2
    while candidate in taken:
        candidate, counter = f"{base}-{counter}", counter + 1
    return candidate


def _store(models: list[CatalogModel]) -> None:
    settings_repo.put_setting(
        SETTING, [m.model_dump(exclude_none=True) for m in models]
    )


def _add(model: CatalogModel) -> CatalogModel:
    existing = user_models()
    duplicate = next((m for m in all_models() if m.sha256 == model.sha256), None)
    if duplicate is not None:
        raise AddModelError(f"that model is already in your list ({duplicate.label})")
    _store([*existing, model])
    return model


def add_from_huggingface(
    url: str, file: str | None = None, http_get: HttpGet | None = None
) -> CatalogModel:
    link = parse_link(url)
    chosen = file or link.file
    if not chosen:
        raise AddModelError("choose which GGUF file to add")
    match = next((f for f in gguf_files(link, http_get) if f.file == chosen), None)
    if match is None:
        raise AddModelError(f"{chosen} isn't a GGUF file in {link.repo}")
    name = Path(match.file).name
    return _add(
        CatalogModel(
            id=_new_id(name),
            label=name.removesuffix(".gguf"),
            tier=_tier(match.size_bytes),
            repo=link.repo,
            file=match.file,
            revision=link.revision,
            sha256=match.sha256,
            size_bytes=match.size_bytes,
            min_ram_gb=math.ceil(match.size_bytes / 1e9 + _RAM_HEADROOM_GB),
            license="See the model card",
            notes=f"Added from huggingface.co/{link.repo}",
            added_by_user=True,
        )
    )


def add_from_file(path: Path) -> CatalogModel:
    """Register a .gguf already on this computer. It stays where it is;
    its hash is taken now so the file is recognised as unchanged later."""
    if path.suffix.lower() != ".gguf" or not path.is_file():
        raise AddModelError("choose a .gguf model file")
    size = path.stat().st_size
    return _add(
        CatalogModel(
            id=_new_id(path.name),
            label=path.stem,
            tier=_tier(size),
            repo="",
            file=path.name,
            local_path=str(path),
            sha256=sha256_of(path),
            size_bytes=size,
            min_ram_gb=math.ceil(size / 1e9 + _RAM_HEADROOM_GB),
            license="See the model's source",
            notes=f"Added from {path.parent}",
            added_by_user=True,
        )
    )


def remove(model_id: str) -> bool:
    """Forget an added model. The app's own downloaded copy is deleted by
    the caller (model_store.delete_model); a local file the user pointed
    at is never touched."""
    models = user_models()
    kept = [m for m in models if m.id != model_id]
    if len(kept) == len(models):
        return False
    _store(kept)
    return True
