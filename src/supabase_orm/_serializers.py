"""Type → wire-value serialization registry.

Postgrest-py accepts JSON-serializable values; we coerce non-JSON types here.
Register custom types with ``register_serializer(MyType, fn)``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable
from uuid import UUID

from pydantic import BaseModel

Serializer = Callable[[Any], Any]

_REGISTRY: dict[type, Serializer] = {}


def register_serializer(tp: type, fn: Serializer) -> None:
    _REGISTRY[tp] = fn


_JSON_NATIVE: tuple[type, ...] = (str, int, float, bool, type(None))


def serialize(value: Any) -> Any:
    # Fast-path: JSON-native scalars are by far the most common values flowing
    # through filter operators and write payloads. Skip the registry walk.
    if type(value) in _JSON_NATIVE:
        return value
    tp = type(value)
    fn = _REGISTRY.get(tp)
    if fn is not None:
        return fn(value)
    for base, fn in _REGISTRY.items():
        if isinstance(value, base):
            return fn(value)
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize(v) for v in value]
    return value


# Builtins.
register_serializer(UUID, str)
register_serializer(datetime, lambda v: v.isoformat())
register_serializer(date, lambda v: v.isoformat())
register_serializer(Decimal, str)
register_serializer(Enum, lambda v: v.value)
register_serializer(BaseModel, lambda v: v.model_dump(mode="json"))
