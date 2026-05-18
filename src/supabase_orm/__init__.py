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

from ._async._base import SupabaseModel
from ._async._client import (
    get_client,
    init,
    lifespan,
    set_client,
    shutdown,
    use_client,
)
from ._async._query import QueryBuilder
from ._async._rpc import rpc, rpc_maybe_one, rpc_one, rpc_scalar
from ._embed import Relation
from ._exceptions import (
    SupabaseORMDoesNotExist,
    SupabaseORMError,
    SupabaseORMMultipleObjectsReturned,
    SupabaseORMUsageError,
)
from ._explain import ExplainResult
from ._filters import register_op
from ._predicates import Column, Order, Predicate
from ._returning import ReturnMode
from ._serializers import register_serializer, serialize
from ._version import __version__

__all__ = [
    "__version__",
    "SupabaseModel",
    "Relation",
    "ExplainResult",
    "QueryBuilder",
    "Column",
    "Predicate",
    "Order",
    "ReturnMode",
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
