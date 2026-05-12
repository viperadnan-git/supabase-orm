"""ORM public API.

    from supabase_orm import SupabaseModel, Relation, lifespan, rpc

    class Pet(SupabaseModel, table="pets"):
        id: UUID
        name: str
        species: str
        adopted: bool

Internals live in underscore-prefixed modules; only names re-exported here
are part of the supported surface.
"""

from ._base import SupabaseModel
from ._client import get_client, lifespan, set_client, use_client
from ._embed import Relation
from ._exceptions import (
    SupabaseORMDoesNotExist,
    SupabaseORMError,
    SupabaseORMMultipleObjectsReturned,
    SupabaseORMUsageError,
)
from ._filters import register_op
from ._predicates import Column, Order, Predicate
from ._query import QueryBuilder
from ._rpc import rpc, rpc_maybe_one, rpc_one, rpc_scalar
from ._serializers import register_serializer, serialize
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
