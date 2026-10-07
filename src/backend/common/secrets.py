"""API keys in the OS credential store (Windows Credential Manager, macOS
Keychain, Secret Service on Linux) via `keyring`. Keys never touch SQLite
or a plaintext file. One entry per provider preset."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SERVICE_NAME = "course-assistant"


class CredentialStoreUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "The OS credential store is unavailable. "
            "Unlock or enable your system keychain, then retry. "
            "Your saved keys have not been reported as missing."
        )


def _no_keyring(err: BaseException) -> bool:
    """True when the machine has no credential backend at all.

    A locked or failing store is a different error: that key may exist,
    so the caller must not be told it is missing.
    """
    try:
        from keyring.errors import NoKeyringError
    except ImportError:
        return True
    return isinstance(err, NoKeyringError)


def get_api_key(provider: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE_NAME, provider)
    except ImportError:
        return None
    except Exception as err:
        if _no_keyring(err):
            return None
        logger.exception("could not read the %s key from the OS keyring", provider)
        raise CredentialStoreUnavailableError() from err


def set_api_key(provider: str, key: str) -> None:
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, provider, key)
    except Exception as err:
        raise CredentialStoreUnavailableError() from err


def delete_api_key(provider: str) -> None:
    if get_api_key(provider) is None:
        return
    try:
        import keyring

        keyring.delete_password(SERVICE_NAME, provider)
    except Exception as err:
        raise CredentialStoreUnavailableError() from err
