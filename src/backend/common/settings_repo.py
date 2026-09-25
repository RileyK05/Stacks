"""User-changeable settings (app_settings table): provider choice, model,
budget. JSON values keyed by dotted names. Secrets never live here — API
keys go to the OS credential store (`common/secrets.py`)."""

from __future__ import annotations

import json
from typing import Any

from src.backend.common.db import connection
from src.backend.common.queries import get

_FILE = "settings"


def get_setting(key: str, default: Any = None) -> Any:
    with connection() as conn:
        row = conn.execute(get(_FILE, "get_setting"), {"key": key}).fetchone()
    return row["value"] if row else default


def put_setting(key: str, value: Any) -> None:
    with connection() as conn:
        conn.execute(
            get(_FILE, "put_setting"), {"key": key, "value": json.dumps(value)}
        )
        conn.commit()


def delete_setting(key: str) -> None:
    with connection() as conn:
        conn.execute(get(_FILE, "delete_setting"), {"key": key})
        conn.commit()
