"""Public exceptions raised by ``supabase_orm``.

All exceptions inherit from :class:`SupabaseORMError`, so callers can do a
single ``except SupabaseORMError`` to catch anything raised by the package.
"""


class SupabaseORMError(Exception):
    """Base class for every exception raised by ``supabase_orm``."""


class SupabaseORMDoesNotExist(SupabaseORMError):
    """A query that expected at least one row matched zero rows."""


class SupabaseORMMultipleObjectsReturned(SupabaseORMError):
    """A query that expected exactly one row matched more than one."""


class SupabaseORMUsageError(SupabaseORMError):
    """The orm was used in an unsupported way.

    Covers both setup-time issues (client not initialized, model declared
    without a table) and runtime misuse (unfiltered bulk delete/update,
    cross-table ``as_()``, primary-key change via ``instance.update()``,
    empty argument lists, etc.).
    """
