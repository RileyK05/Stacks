"""API keys in the OS credential store (Windows Credential Manager, macOS
Keychain, Secret Service on Linux) via `keyring`. Keys never touch SQLite
or a plaintext file. One entry per provider preset."""

from __future__ import annotations

import logging
from contextlib import suppress

logger = logging.getLogger(__name__)

SERVICE_NAME = "course-assistant"


def get_api_key(provider: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE_NAME, provider)
    except Exception:
        logger.exception("could not read the %s key from the OS keyring", provider)
        return None


def set_api_key(provider: str, key: str) -> None:
    import keyring

    keyring.set_password(SERVICE_NAME, provider, key)


def delete_api_key(provider: str) -> None:
    import keyring
    from keyring.errors import PasswordDeleteError

    with suppress(PasswordDeleteError):
        keyring.delete_password(SERVICE_NAME, provider)
