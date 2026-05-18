"""Relation metadata + select-string builder.

PostgREST resource embedding: a model field whose annotation is a SupabaseModel
(or list[SupabaseModel]) becomes an embedded resource in the generated
``select`` string. Use ``Annotated[T, Relation(...)]`` to add hints.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic.fields import FieldInfo


@dataclass(frozen=True)
class Relation:
    """Metadata describing a relation embedded into a SupabaseModel field.

    Example:
        ```python
        class Pet(SupabaseModel, table="pets"):
            id: UUID
            name: str
            owner: Annotated[Owner, Relation(join="inner", fk="pets_owner_fkey")]
            tags: Annotated[
                list[Tag], Relation(through="pet_tags", filter={"deleted": False})
            ]
        ```

    Args:
        join: ``"left"`` (default) or ``"inner"`` — translates to ``!inner``.
        fk: Foreign-key constraint name for disambiguation. PostgREST uses
            ``alias:target!fk_name(...)``.
        through: Junction-table or FK hint when PostgREST can't auto-resolve
            the relationship. Same syntax slot as ``fk``.
        filter: Per-relation filter dict (e.g. ``{"is_deleted": False}``).
            Operator suffixes like ``views__gte`` are honored.
    """

    join: Literal["left", "inner"] = "left"
    fk: str | None = None
    through: str | None = None
    filter: dict[str, Any] | None = None


def _is_supabase_model(tp: Any) -> bool:
    # Duck-typed marker rather than ``issubclass`` so the shared embed
    # module doesn't reach into one specific impl tree — the async and
    # sync ``SupabaseModel`` classes both set ``__supabase_model__`` on
    # the base via ``_base.py``.
    return isinstance(tp, type) and getattr(tp, "__supabase_model__", False)


def _unwrap_optional(tp: Any) -> Any:
    """Strip ``Optional[T]`` / ``T | None`` → T."""
    origin = get_origin(tp)
    if origin in (Union, UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def _resolve_field(field_info: FieldInfo) -> tuple[type | None, bool, Relation]:
    """Inspect a Pydantic FieldInfo. Returns (model_cls, is_list, relation_meta).

    ``model_cls`` is None when the field is a scalar column. Pydantic v2
    flattens ``Annotated[T, meta...]`` into ``annotation=T`` and
    ``metadata=[meta...]``, so we read both directly.
    """
    relation = Relation()
    for meta in getattr(field_info, "metadata", None) or ():
        if isinstance(meta, Relation):
            relation = meta
            break

    tp = _unwrap_optional(field_info.annotation)

    is_list = False
    if get_origin(tp) in (list, set, tuple):
        inner = get_args(tp)
        if inner:
            tp = _unwrap_optional(inner[0])
            is_list = True

    if _is_supabase_model(tp):
        return tp, is_list, relation
    return None, False, relation


def build_select(model_cls: type, _seen: frozenset[type] = frozenset()) -> str:
    """Build the PostgREST ``select`` string for ``model_cls``.

    Recurses into related SupabaseModel fields. Cycles raise.
    """
    if model_cls in _seen:
        raise ValueError(
            f"Relation cycle detected at {model_cls.__name__}. "
            "Break the cycle with a leaner projection model."
        )
    seen = _seen | {model_cls}

    parts: list[str] = []
    for name, field_info in model_cls.model_fields.items():
        related_cls, _is_list, relation = _resolve_field(field_info)
        if related_cls is None:
            parts.append(name)
            continue

        target_table = getattr(related_cls, "__table__", None)
        if target_table is None:
            raise ValueError(
                f"{model_cls.__name__}.{name}: related type "
                f"{related_cls.__name__} is not a SupabaseModel with a table."
            )

        nested = build_select(related_cls, seen)
        head = target_table
        hint = relation.fk or relation.through
        if hint:
            head = f"{head}!{hint}"
        if relation.join == "inner":
            head = f"{head}!inner"
        prefix = f"{name}:" if name != target_table else ""
        parts.append(f"{prefix}{head}({nested})")

    return ",".join(parts)


def collect_relations(
    model_cls: type,
) -> dict[str, tuple[type, bool, Relation]]:
    """Map of {python_field_name: (related_cls, is_list, relation_meta)}."""
    out: dict[str, tuple[type, bool, Relation]] = {}
    for name, fi in model_cls.model_fields.items():
        related_cls, is_list, relation = _resolve_field(fi)
        if related_cls is not None:
            out[name] = (related_cls, is_list, relation)
    return out
