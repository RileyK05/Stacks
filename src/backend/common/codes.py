"""Canonical shareable-code format used across the product.

One format, one alphabet, one validation rule: 16 payload characters from a
31-symbol alphabet (look-alikes removed), displayed grouped as
XXXX-XXXX-XXXX-XXXX (20 chars with dashes). Codes are server-generated from
`secrets`; user-supplied codes are normalized then format-checked at the API
boundary so garbage is rejected with a 422 before any lookup.

Security note: standardizing the format is a usability/consistency decision,
not a security one. A join code grants nothing on its own — course visibility
policy and code rotation are the actual controls. Premium codes additionally
hash at rest because they grant paid tier (money), which join codes do not.
"""

from __future__ import annotations

import re
import secrets

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 16
DISPLAY_GROUP = 4

# 16 alphabet chars, optionally grouped with single dashes between groups.
_CODE_RE = re.compile(rf"^[{''.join(CODE_ALPHABET)}]{{16}}$")


def generate_code() -> str:
    """Fresh code in canonical payload form (16 chars, no dashes). Grouping is
    a display concern applied via display_code()."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code: str) -> str:
    """Canonical payload form: uppercase, separators/whitespace removed."""
    return "".join(char for char in code.strip().upper() if char.isalnum())


def display_code(code: str) -> str:
    """Grouped uppercase form for display (e.g. ABCD-EFGH-JKMN-PQRS)."""
    compact = normalize_code(code)
    if len(compact) <= DISPLAY_GROUP:
        return compact
    return "-".join(
        compact[i : i + DISPLAY_GROUP]
        for i in range(0, len(compact), DISPLAY_GROUP)
    )


def is_valid(code: str) -> bool:
    """True when the normalized form is exactly 16 alphabet characters."""
    return bool(_CODE_RE.match(normalize_code(code)))


def require_valid(code: str) -> str:
    """Normalize and validate; raises ValueError with a clear message."""
    normalized = normalize_code(code)
    if not _CODE_RE.match(normalized):
        raise ValueError(
            f"code must be {CODE_LENGTH} characters from "
            f"{CODE_ALPHABET} (grouped display: XXXX-XXXX-XXXX-XXXX)"
        )
    return normalized