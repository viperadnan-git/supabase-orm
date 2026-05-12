# DO NOT EDIT — generated from src/supabase_orm/_async/_rpc.py by scripts/gen_sync.py.
# Run `python scripts/gen_sync.py` (or rebuild the package) to regenerate.

"""Typed RPC helper.

Keyword args become SQL function parameters — the names must match the
function's signature exactly (PostgREST passes them through verbatim)::

    owner_id: UUID = ...
    rows = rpc("get_pet_stats", PetStats, p_owner_id=owner_id)
    one  = rpc_one("get_owner_summary", OwnerSummary, p_owner_id=owner_id)
    val  = rpc_scalar("count_adopted_pets", int)
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter

from .._serializers import serialize
from ._client import get_client

T = TypeVar("T", bound=BaseModel)
S = TypeVar("S")

# Cache one ``TypeAdapter(list[Model])`` per model so batch validation runs
# through Pydantic's Rust core instead of N separate Python-level calls.
_LIST_ADAPTERS: dict[type[BaseModel], TypeAdapter] = {}
_SCALAR_ADAPTERS: dict[Any, TypeAdapter] = {}


def _list_adapter(model: type[T]) -> TypeAdapter:
    adapter = _LIST_ADAPTERS.get(model)
    if adapter is None:
        adapter = TypeAdapter(list[model])
        _LIST_ADAPTERS[model] = adapter
    return adapter


def _scalar_adapter(result_type: Any) -> TypeAdapter:
    adapter = _SCALAR_ADAPTERS.get(result_type)
    if adapter is None:
        adapter = TypeAdapter(result_type)
        _SCALAR_ADAPTERS[result_type] = adapter
    return adapter


def _serialize_params(params: dict[str, Any]) -> dict[str, Any]:
    return {k: serialize(v) for k, v in params.items()}


def rpc(name: str, model: type[T], **params: Any) -> list[T]:
    """Call a Postgres function returning ``setof``. Validates each row."""
    resp = get_client().rpc(name, _serialize_params(params)).execute()
    rows = resp.data or []
    if not isinstance(rows, list):
        rows = [rows]
    return _list_adapter(model).validate_python(rows)


def rpc_one(name: str, model: type[T], **params: Any) -> T:
    rows = rpc(name, model, **params)
    if not rows:
        raise ValueError(f"rpc({name!r}) returned no rows")
    return rows[0]


def rpc_maybe_one(name: str, model: type[T], **params: Any) -> T | None:
    rows = rpc(name, model, **params)
    return rows[0] if rows else None


def rpc_scalar(name: str, result_type: type[S], **params: Any) -> S:
    """Call a function returning a scalar (int, str, bool, ...)."""
    resp = get_client().rpc(name, _serialize_params(params)).execute()
    return _scalar_adapter(result_type).validate_python(resp.data)
