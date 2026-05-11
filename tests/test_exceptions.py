"""Exception hierarchy."""

from __future__ import annotations

from supabase_orm import (
    SupabaseORMDoesNotExist,
    SupabaseORMError,
    SupabaseORMMultipleObjectsReturned,
    SupabaseORMUsageError,
)


def test_all_exceptions_inherit_from_base():
    for sub in (
        SupabaseORMDoesNotExist,
        SupabaseORMMultipleObjectsReturned,
        SupabaseORMUsageError,
    ):
        assert issubclass(sub, SupabaseORMError)


def test_base_is_exception():
    assert issubclass(SupabaseORMError, Exception)
