"""Asynchronous implementation — canonical source for the orm.

The sync mirror under ``supabase_orm._sync`` is generated from this
tree by ``scripts/gen_sync.py``. Public re-export lives at
``supabase_orm`` (async, default) and ``supabase_orm.sync`` (generated).

Tests import from ``supabase_orm._async`` directly so the unasync
rewrite (``_async`` → ``_sync``) gives the matching sync test tree an
automatic, correct-by-construction import path.
"""

from .._embed import Relation
from .._exceptions import (
    SupabaseORMDoesNotExist,
    SupabaseORMError,
    SupabaseORMMultipleObjectsReturned,
    SupabaseORMUsageError,
)
from .._filters import register_op
from .._predicates import Column, Order, Predicate
from .._serializers import register_serializer, serialize
from .._version import __version__
from ._base import SupabaseModel
from ._client import get_client, init, lifespan, set_client, shutdown, use_client
from ._query import QueryBuilder
from ._rpc import rpc, rpc_maybe_one, rpc_one, rpc_scalar

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
