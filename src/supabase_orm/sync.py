"""Synchronous public API.

Mirrors :mod:`supabase_orm` 1:1 against ``supabase-py``'s sync ``Client``
instead of ``AsyncClient``. Intended for background workers, cron jobs,
data scripts and any context where running an event loop just to await
one query is overkill::

    from supabase_orm.sync import SupabaseModel, lifespan, rpc

    class Pet(SupabaseModel, table="pets"):
        id: UUID
        name: str
        species: str

    with lifespan(URL, KEY):
        for pet in Pet.query.eq("species", "cat").iter():
            ...

The sync implementation under ``supabase_orm._sync`` is generated from
the async tree by ``scripts/gen_sync.py``; treat the async module as the
canonical source.
"""

from ._embed import Relation
from ._exceptions import (
    SupabaseORMDoesNotExist,
    SupabaseORMError,
    SupabaseORMMultipleObjectsReturned,
    SupabaseORMUsageError,
)
from ._filters import register_op
from ._predicates import Column, Order, Predicate
from ._serializers import register_serializer, serialize
from ._sync._base import SupabaseModel
from ._sync._client import (
    get_client,
    init,
    lifespan,
    set_client,
    shutdown,
    use_client,
)
from ._sync._query import QueryBuilder
from ._sync._rpc import rpc, rpc_maybe_one, rpc_one, rpc_scalar
from ._version import __version__

__all__ = [
    "__version__",
    "SupabaseModel",
    "Relation",
    "QueryBuilder",
    "Column",
    "Predicate",
    "Order",
    "lifespan",
    "init",
    "shutdown",
    "get_client",
    "set_client",
    "use_client",
    "rpc",
    "rpc_one",
    "rpc_maybe_one",
    "rpc_scalar",
    "register_op",
    "register_serializer",
    "serialize",
    "SupabaseORMError",
    "SupabaseORMDoesNotExist",
    "SupabaseORMMultipleObjectsReturned",
    "SupabaseORMUsageError",
]
