"""Config files parsed once per version on disk.

Every request read the same TOML files again (124 parses for one chat
message: the retrieval, prompt, learning and generation policies are loaded
wherever they are used). The parsed table is cached by path, modification
time and size, so editing a config still takes effect on the next call, and
each caller gets its own copy to change freely.
"""

from __future__ import annotations

import copy
import threading
import tomllib
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


def load_toml(path: Path) -> dict[str, Any]:
    stat = path.stat()
    key = str(path)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == stat.st_mtime_ns and hit[1] == stat.st_size:
            return copy.deepcopy(hit[2])
    with path.open("rb") as handle:
        parsed = tomllib.load(handle)
    with _LOCK:
        _CACHE[key] = (stat.st_mtime_ns, stat.st_size, parsed)
    return copy.deepcopy(parsed)
