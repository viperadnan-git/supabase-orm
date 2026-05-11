"""Chainable async QueryBuilder.

The typed operator surface lives on ``_Filterable`` — a mixin shared by both
``QueryBuilder`` (mutates a postgrest builder) and ``_PredicateGroup``
(accumulates predicate strings inside ``or_()`` / ``not_()`` lambdas). One
declaration, two implementations of ``_apply_op``.

The builder is stateful: each chain call mutates and returns ``self``.
Don't reuse a builder after a terminal call; create a fresh one off ``Model.query``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Callable, Generic, Self, TypeVar, cast

from ._client import get_client
from ._exceptions import (
    SupabaseORMDoesNotExist,
    SupabaseORMMultipleObjectsReturned,
    SupabaseORMUsageError,
)
from ._filters import apply_op, compile_predicate
from ._serializers import serialize

if TYPE_CHECKING:
    from ._base import SupabaseModel

T = TypeVar("T", bound="SupabaseModel")
U = TypeVar("U", bound="SupabaseModel")


# ─── Filter mixin (typed operator surface) ────────────────────────────────


class _Filterable:
    """Typed operator methods.

    Subclasses implement ``_apply_op`` and ``_apply_predicate_group`` to plug
    into their own state (postgrest builder vs. predicate-string list).
    """

    _model: type["SupabaseModel"]

    # ─── Hooks (subclasses implement) ──────────────────────────────────────

    def _apply_op(self, name: str, column: str, value: Any) -> Self:
        raise NotImplementedError

    def _apply_predicate_group(self, group: str) -> Self:
        raise NotImplementedError

    # ─── Filter operators ──────────────────────────────────────────────────

    def eq(self, column: str, value: Any) -> Self:
        return self._apply_op("eq", column, value)

    def neq(self, column: str, value: Any) -> Self:
        return self._apply_op("neq", column, value)

    def gt(self, column: str, value: Any) -> Self:
        return self._apply_op("gt", column, value)

    def gte(self, column: str, value: Any) -> Self:
        return self._apply_op("gte", column, value)

    def lt(self, column: str, value: Any) -> Self:
        return self._apply_op("lt", column, value)

    def lte(self, column: str, value: Any) -> Self:
        return self._apply_op("lte", column, value)

    def like(self, column: str, pattern: str) -> Self:
        return self._apply_op("like", column, pattern)

    def ilike(self, column: str, pattern: str) -> Self:
        return self._apply_op("ilike", column, pattern)

    def in_(self, column: str, values: Sequence[Any]) -> Self:
        return self._apply_op("in_", column, values)

    def is_(self, column: str, value: Any) -> Self:
        return self._apply_op("is_", column, value)

    def contains(self, column: str, value: Any) -> Self:
        return self._apply_op("contains", column, value)

    def contained_by(self, column: str, value: Any) -> Self:
        return self._apply_op("contained_by", column, value)

    def overlaps(self, column: str, value: Any) -> Self:
        return self._apply_op("overlaps", column, value)

    def fts(self, column: str, query: str) -> Self:
        return self._apply_op("fts", column, query)

    def plfts(self, column: str, query: str) -> Self:
        return self._apply_op("plfts", column, query)

    def phfts(self, column: str, query: str) -> Self:
        return self._apply_op("phfts", column, query)

    def wfts(self, column: str, query: str) -> Self:
        return self._apply_op("wfts", column, query)

    # ─── Compound predicates ───────────────────────────────────────────────

    def or_(
        self,
        *branches: Callable[["_PredicateGroup"], "_PredicateGroup"],
    ) -> Self:
        compiled = _compile_branches(self._model, branches)
        return self._apply_predicate_group(f"or({compiled})")

    def not_(
        self,
        branch: Callable[["_PredicateGroup"], "_PredicateGroup"],
    ) -> Self:
        sub = _PredicateGroup(self._model)
        branch(sub)
        return self._apply_predicate_group(f"not.and({sub._compile()})")


# ─── PredicateGroup ────────────────────────────────────────────────────────


class _PredicateGroup(_Filterable):
    """Predicate-string accumulator used inside ``or_()`` / ``not_()``."""

    def __init__(self, model: type["SupabaseModel"]) -> None:
        self._model = model
        self._preds: list[str] = []

    def _apply_op(self, name: str, column: str, value: Any) -> Self:
        self._model._validate_column(column)
        self._preds.append(compile_predicate(name, column, value))
        return self

    def _apply_predicate_group(self, group: str) -> Self:
        self._preds.append(group)
        return self

    def _compile(self) -> str:
        return ",".join(self._preds)


def _compile_branches(
    model: type["SupabaseModel"],
    branches: tuple[Callable[[_PredicateGroup], _PredicateGroup], ...],
) -> str:
    parts: list[str] = []
    for br in branches:
        sub = _PredicateGroup(model)
        br(sub)
        compiled = sub._compile()
        if "," in compiled and not compiled.startswith(("or(", "and(", "not.")):
            parts.append(f"and({compiled})")
        else:
            parts.append(compiled)
    return ",".join(parts)


# ─── QueryBuilder ──────────────────────────────────────────────────────────


class QueryBuilder(_Filterable, Generic[T]):
    """Async chainable query builder.

    Build:        ``Pet.query.eq("species", "cat").gte("age", 3).limit(10)``
    Terminate:    ``.all()`` / ``.first()`` / ``.one()`` / ``.maybe_one()``
                  / ``.count()`` / ``.all_with_count()`` / ``.delete()``
                  / ``.update(...)``
    Escape hatch: ``.raw()`` returns the underlying postgrest async builder.
    """

    _model: type[T]

    def __init__(self, model: type[T]) -> None:
        self._model = model
        self._select: str = model.__select__
        self._client = get_client()
        self._raw = self._client.table(model.__table__).select(self._select)
        # Op log: every chain call records its tuple here so terminals like
        # count() / delete() / update() can replay the same filters onto a
        # fresh request without sharing state.
        self._ops: list[tuple] = []

    # ─── Filter mixin hooks ────────────────────────────────────────────────

    def _apply_op(self, name: str, column: str, value: Any) -> Self:
        self._model._validate_column(column)
        self._ops.append(("op", name, column, value))
        self._raw = apply_op(self._raw, name, column, value)
        return self

    def _apply_predicate_group(self, group: str) -> Self:
        # postgrest-py's ``or_`` accepts the body of either an or-group or a
        # not.and-group; we build the wrapped string in ``_Filterable.or_/not_``.
        if group.startswith("or("):
            inner = group[3:-1]  # strip ``or(`` / ``)``
            self._raw = self._raw.or_(inner)
            self._ops.append(("or", inner))
        else:  # ``not.and(...)``
            self._raw = self._raw.or_(group)
            self._ops.append(("or", group))
        return self

    # ─── Selection & ordering ──────────────────────────────────────────────

    def match(self, query: dict[str, Any]) -> Self:
        """Filter rows where every ``column == value`` pair in ``query`` holds.

        PostgREST's ``match`` is multi-column by design — it has no single
        ``column`` argument. Use it for compound equality filters::

            await Pet.query.match({"species": "cat", "adopted": False}).all()

        Equivalent to chaining ``.eq()`` per pair. Not available inside
        ``or_()`` / ``not_()`` (no predicate-string form).
        """
        for col in query:
            self._model._validate_column(col)
        serialized = {k: serialize(v) for k, v in query.items()}
        self._raw = self._raw.match(serialized)
        self._ops.append(("match", serialized))
        return self

    def order_by(self, *columns: str) -> Self:
        """``"col"`` ascending, ``"-col"`` descending."""
        for c in columns:
            desc = c.startswith("-")
            col = c[1:] if desc else c
            self._raw = self._raw.order(col, desc=desc)
            self._ops.append(("order", col, desc))
        return self

    def limit(self, n: int) -> Self:
        self._raw = self._raw.limit(n)
        self._ops.append(("limit", n))
        return self

    def offset(self, n: int) -> Self:
        self._raw = self._raw.offset(n)
        self._ops.append(("offset", n))
        return self

    def range(self, start: int, end: int) -> Self:
        self._raw = self._raw.range(start, end)
        self._ops.append(("range", start, end))
        return self

    # ─── Projection / rebind ───────────────────────────────────────────────

    def as_(self, model: type[U]) -> "QueryBuilder[U]":
        """Rebind the query to validate rows against ``model`` instead.

        Both classes must point to the same ``__table__``. Useful for swapping
        between a "full" model and a leaner projection that share the table::

            class Pet(SupabaseModel, table="pets"):
                id: UUID
                name: str
                species: str
                created_at: datetime

            class PetMini(SupabaseModel, table="pets"):
                id: UUID
                name: str

            await Pet.query.eq("adopted", False).as_(PetMini).all()
            # → list[PetMini]
        """
        if model.__table__ != self._model.__table__:
            raise SupabaseORMUsageError(
                f"as_({model.__name__}): different table "
                f"({model.__table__!r} != {self._model.__table__!r}). "
                "Both models must point at the same __table__."
            )
        self._model = cast("type[T]", model)
        self._select = model.__select__
        # Postgrest doesn't allow chaining a second .select(), so rebuild from
        # scratch and replay the recorded ops onto the fresh builder.
        self._raw = self._client.table(model.__table__).select(self._select)
        self._raw = self._replay(self._raw)
        return cast("QueryBuilder[U]", self)

    async def values(self, *columns: str) -> list[dict[str, Any]]:
        """Run the query with an ad-hoc column projection. Returns raw dicts.

        No Pydantic validation, no autocomplete — caller deals with
        ``row["col"]``. Use for exports, ad-hoc admin queries, anything where
        defining a projection model would be overkill. ``columns`` may include
        PostgREST embed syntax (e.g. ``"pets(id,name)"``)::

            rows = await Pet.query.eq("adopted", False).values("id", "name")
        """
        if not columns:
            raise SupabaseORMUsageError(".values() requires at least one column.")
        select_str = ",".join(columns)
        b = self._client.table(self._model.__table__).select(select_str)
        b = self._replay(b)
        b = self._apply_relation_filters_on(b)
        resp = await b.execute()
        return resp.data or []

    # ─── Escape hatch ──────────────────────────────────────────────────────

    def raw(self) -> Any:
        """Return the underlying postgrest async builder for ops we don't model.

        Pair with :func:`supabase_orm.serialize` if you need wire-value
        coercion for non-JSON-native python types.
        """
        return self._apply_relation_filters_on(self._raw)

    # ─── Internal replay ───────────────────────────────────────────────────

    def _replay(self, target: Any) -> Any:
        """Replay the recorded op log onto ``target`` (a postgrest builder)."""
        for op in self._ops:
            kind = op[0]
            if kind == "op":
                _, name, col, val = op
                target = apply_op(target, name, col, val)
            elif kind == "or":
                target = target.or_(op[1])
            elif kind == "order":
                target = target.order(op[1], desc=op[2])
            elif kind == "limit":
                target = target.limit(op[1])
            elif kind == "offset":
                target = target.offset(op[1])
            elif kind == "range":
                target = target.range(op[1], op[2])
            elif kind == "match":
                target = target.match(op[1])
            elif kind == "filter":
                _, col, operator, value = op
                target = target.filter(col, operator, value)
        return target

    def _apply_relation_filters_on(self, target: Any) -> Any:
        """Apply ``Relation(filter=...)`` clauses without recording into ops."""
        for fname, (_cls, _is_list, relation) in self._model.__relations__.items():
            if not relation.filter:
                continue
            for key, val in relation.filter.items():
                col, _, op = key.partition("__")
                op = op or "eq"
                pred = compile_predicate(op, col, val)
                _, _, rest = pred.partition(".")
                operator, _, value = rest.partition(".")
                target = target.filter(f"{fname}.{col}", operator, value)
        return target

    def _has_filter(self) -> bool:
        """``True`` if any narrowing op (filter / or-group) is recorded.

        Used by ``delete()``/``update()`` as a foot-gun guard so an
        unfiltered ``.query.delete()`` raises rather than wiping the table.
        """
        return any(op[0] in ("op", "or", "match") for op in self._ops)

    # ─── Read terminals ────────────────────────────────────────────────────

    async def all(self) -> list[T]:
        self._raw = self._apply_relation_filters_on(self._raw)
        resp = await self._raw.execute()
        return self._validate_rows(resp.data or [])

    async def all_with_count(self) -> tuple[list[T], int]:
        """Run the query and ask PostgREST for an exact total in one round-trip.

        Useful for paginated endpoints — saves a separate ``.count()`` call.
        ``count="exact"`` is computed on the FILTERED row set, ignoring
        ``limit``/``offset``, which is the standard pagination semantics.
        """
        # ``count="exact"`` must be passed on the initial select; rebuild
        # from the op log instead of mutating ``self._raw``.
        b = self._client.table(self._model.__table__).select(
            self._select, count="exact"
        )
        b = self._replay(b)
        b = self._apply_relation_filters_on(b)
        resp = await b.execute()
        rows = self._validate_rows(resp.data or [])
        return rows, getattr(resp, "count", None) or 0

    async def first(self) -> T | None:
        self.limit(1)
        rows = await self.all()
        return rows[0] if rows else None

    async def one(self) -> T:
        rows = await self.limit(2).all()
        if not rows:
            raise SupabaseORMDoesNotExist(f"No {self._model.__name__} matched query")
        if len(rows) > 1:
            raise SupabaseORMMultipleObjectsReturned(
                f"Multiple {self._model.__name__} rows matched; expected exactly one"
            )
        return rows[0]

    async def maybe_one(self) -> T | None:
        rows = await self.limit(2).all()
        if not rows:
            return None
        if len(rows) > 1:
            raise SupabaseORMMultipleObjectsReturned(
                f"Multiple {self._model.__name__} rows matched; "
                "use .first() if you want the first"
            )
        return rows[0]

    async def count(self) -> int:
        """Count matching rows on a fresh head-only request, replaying the
        recorded op log so filters (including relation filters) are honored."""
        b = self._client.table(self._model.__table__).select(
            "*", count="exact", head=True
        )
        b = self._replay(b)
        b = self._apply_relation_filters_on(b)
        resp = await b.execute()
        return getattr(resp, "count", None) or 0

    # ─── Write terminals ───────────────────────────────────────────────────

    async def delete(self, *, allow_unfiltered: bool = False) -> list[T]:
        """Bulk-delete every matching row. Returns the deleted rows.

        Raises ``SupabaseORMUsageError`` if no filter has been chained
        unless ``allow_unfiltered=True`` is passed explicitly. PostgREST also
        rejects unfiltered DELETE by default at the server.
        """
        if not allow_unfiltered and not self._has_filter():
            raise SupabaseORMUsageError(
                "Refusing unfiltered .delete() — chain at least one filter or "
                "pass allow_unfiltered=True to wipe the table."
            )
        b = self._client.table(self._model.__table__).delete()
        b = self._replay(b)
        b = self._apply_relation_filters_on(b)
        resp = await b.execute()
        return self._validate_rows(resp.data or [])

    async def update(self, *, allow_unfiltered: bool = False, **values: Any) -> list[T]:
        """Bulk-update every matching row. Returns the updated rows.

        Raises ``SupabaseORMUsageError`` if no filter has been chained
        unless ``allow_unfiltered=True`` is passed explicitly.
        """
        if not allow_unfiltered and not self._has_filter():
            raise SupabaseORMUsageError(
                "Refusing unfiltered .update() — chain at least one filter or "
                "pass allow_unfiltered=True to update every row."
            )
        if not values:
            raise SupabaseORMUsageError(
                "update() requires at least one key=value to set."
            )
        payload = {k: serialize(v) for k, v in values.items()}
        b = self._client.table(self._model.__table__).update(payload)
        b = self._replay(b)
        b = self._apply_relation_filters_on(b)
        resp = await b.execute()
        return self._validate_rows(resp.data or [])

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _validate_rows(self, data: list[dict[str, Any]]) -> list[T]:
        adapter = self._model.__list_adapter__
        if adapter is not None:
            return adapter.validate_python(data)
        return [self._model.model_validate(r) for r in data]
