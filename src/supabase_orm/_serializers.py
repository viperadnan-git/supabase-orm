"""Type → wire-value serialization registry.

Postgrest-py accepts JSON-serializable values; we coerce non-JSON types here.
Register custom types via :func:`register_serializer`.

Pydantic ``BaseModel`` values dump via ``model_dump(mode="json", exclude_unset=True)``
— sparse storage that mirrors the column-level dirty tracking ``save()`` uses.
For different behavior on a specific model, register a custom serializer::

    register_serializer(Metadata, lambda v: v.model_dump(mode="json"))  # lossless
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable
from uuid import UUID
from weakref import WeakKeyDictionary

from pydantic import BaseModel

Serializer = Callable[[Any], Any]

# Exact-type → serializer (the registration the user wrote).
_REGISTRY: dict[type, Serializer] = {}
# Resolved-type cache. ``WeakKeyDictionary`` keyed on the type object so
# dynamically-generated classes (Pydantic ``create_model``, factory-built
# enums, etc.) don't pin themselves in memory once they go out of scope.
_RESOLVED: "WeakKeyDictionary[type, Serializer]" = WeakKeyDictionary()


def register_serializer(tp: type, fn: Serializer) -> None:
    """Register a wire-value serializer for ``tp`` and its subclasses.

    The serializer ``fn`` is called by :func:`serialize` whenever it
    encounters a value of type ``tp`` (or a subclass). Registration is
    process-global; the resolved-subclass cache is cleared so previously
    cached dispatch decisions get re-evaluated against the new entry.

    Example:
        ```python
        from supabase_orm import register_serializer

        class Money:
            def __init__(self, cents: int) -> None:
                self.cents = cents

        register_serializer(Money, lambda v: v.cents)
        ```

    Args:
        tp: The exact Python type to register. Subclasses dispatch via
            ``isinstance`` walk on first encounter (then cached).
        fn: Callable that takes a value and returns a JSON-native form
            (``str`` / ``int`` / ``float`` / ``bool`` / ``None`` / ``list`` /
            ``dict``).
    """
    _REGISTRY[tp] = fn
    _RESOLVED.clear()


_JSON_NATIVE: tuple[type, ...] = (str, int, float, bool, type(None))


def serialize(value: Any) -> Any:
    """Coerce ``value`` to a JSON-native form using the registered serializers.

    Dispatch order:

    1. ``str`` / ``int`` / ``float`` / ``bool`` / ``None`` — returned as-is.
    2. Exact-type or resolved-subclass cache hit — registered serializer fires.
    3. First-time subclass — walk the registry, cache the match.
    4. ``dict`` / ``list`` / ``tuple`` / ``set`` — recurse element-by-element.
    5. Unknown — returned unchanged (postgrest-py decides).

    Built-in registrations: ``UUID`` → str, ``datetime`` / ``date`` →
    ISO 8601 strings, ``Decimal`` → str, ``Enum`` → ``.value``,
    Pydantic ``BaseModel`` → ``model_dump(mode="json", **__model_dump_kwargs__)``.

    Args:
        value: Any Python value the ORM is about to send on the wire.

    Returns:
        A JSON-serializable form of ``value``.
    """
    tp = type(value)
    # Fast-path: JSON-native scalars are by far the most common values
    # flowing through filter operators and write payloads.
    if tp in _JSON_NATIVE:
        return value
    # Exact-type and resolved-subclass caches — both O(1) dict lookups.
    fn = _REGISTRY.get(tp) or _RESOLVED.get(tp)
    if fn is not None:
        return fn(value)
    # First time we see this type: walk the registry once, cache the result.
    for base, fn in _REGISTRY.items():
        if isinstance(value, base):
            _RESOLVED[tp] = fn
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
register_serializer(BaseModel, lambda v: v.model_dump(mode="json", exclude_unset=True))
