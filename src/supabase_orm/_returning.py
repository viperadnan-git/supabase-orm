"""``returning`` modes for write methods — PostgREST's ``Prefer: return=``."""

from __future__ import annotations

from typing import Literal

from ._exceptions import SupabaseORMUsageError

ReturnMode = Literal["representation", "minimal"]

_VALID: frozenset[str] = frozenset({"representation", "minimal"})


def validate_returning(mode: str) -> None:
    if mode not in _VALID:
        raise SupabaseORMUsageError(
            f"returning must be 'representation' or 'minimal', got {mode!r}"
        )
