"""Typed RPC helper.

Keyword args become SQL function parameters — the names must match the
function's signature exactly (PostgREST passes them through verbatim)::

    owner_id: UUID = ...
    rows = await rpc("get_pet_stats", PetStats, p_owner_id=owner_id)
    one  = await rpc_one("get_owner_summary", OwnerSummary, p_owner_id=owner_id)
    val  = await rpc_scalar("count_adopted_pets", int)
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter

from .._serializers import serialize
from ._client import get_client
from ._log import execute_logged

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


async def rpc(name: str, model: type[T], **params: Any) -> list[T]:
    """Call a Postgres function returning ``setof``. Validates each row.

    Args:
        name: SQL function name (must exist in the configured schema).
        model: Pydantic model used to validate each returned row.
        **params: Named arguments — must match the function's parameter names.
    """
    resp = await execute_logged(get_client().rpc(name, _serialize_params(params)))
    rows = resp.data or []
    if not isinstance(rows, list):
        rows = [rows]
    return _list_adapter(model).validate_python(rows)


async def rpc_one(name: str, model: type[T], **params: Any) -> T:
    """Like :func:`rpc` but expects exactly one row; raises otherwise.

    Args:
        name: SQL function name.
        model: Pydantic model used to validate the row.
        **params: Named arguments matching the function signature.
    """
    rows = await rpc(name, model, **params)
    if not rows:
        raise ValueError(f"rpc({name!r}) returned no rows")
    return rows[0]


async def rpc_maybe_one(name: str, model: type[T], **params: Any) -> T | None:
    """Like :func:`rpc` but returns the first row, or ``None`` if empty.

    Args:
        name: SQL function name.
        model: Pydantic model used to validate the row.
        **params: Named arguments matching the function signature.
    """
    rows = await rpc(name, model, **params)
    return rows[0] if rows else None


async def rpc_scalar(name: str, result_type: type[S], **params: Any) -> S:
    """Call a function returning a scalar (int, str, bool, ...).

    Args:
        name: SQL function name.
        result_type: The scalar Python type to coerce the result into.
        **params: Named arguments matching the function signature.
    """
    resp = await execute_logged(get_client().rpc(name, _serialize_params(params)))
    return _scalar_adapter(result_type).validate_python(resp.data)
