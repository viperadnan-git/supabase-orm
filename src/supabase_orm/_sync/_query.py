# DO NOT EDIT — generated from src/supabase_orm/_async/_query.py by scripts/gen_sync.py.
# Run `python scripts/gen_sync.py` (or rebuild the package) to regenerate.

"""Chainable QueryBuilder.

The typed operator surface lives on ``_Filterable`` — a mixin shared by both
``QueryBuilder`` (mutates a postgrest builder) and ``_PredicateGroup``
(accumulates predicate strings inside ``or_()`` / ``not_()`` lambdas). One
declaration, two implementations of ``_apply_op``.

The builder is stateful: each chain call mutates and returns ``self``.
Don't reuse a builder after a terminal call; create a fresh one off ``Model.query``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from enum import StrEnum
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Literal,
    Self,
    TypeVar,
    cast,
    overload,
)


class _Op(StrEnum):
    """Op-log discriminators.

    ``StrEnum`` so legacy string comparisons (e.g. ``op[0] == "or"``) keep
    working — but new code should use the enum members for autocomplete
    and to keep ``_replay`` / ``_has_filter`` in sync.
    """

    OP = "op"
    OR = "or"
    MATCH = "match"
    ORDER = "order"
    LIMIT = "limit"
    OFFSET = "offset"
    RANGE = "range"
    FILTER = "filter"


# Set of op kinds that count as a "narrowing" filter for the bulk
# delete/update foot-gun guard.
_FILTERING_OPS = frozenset({_Op.OP, _Op.OR, _Op.MATCH})

# Op kinds that conflict with iter() — iter owns ordering and pagination.
_ITER_FORBIDDEN_OPS = frozenset({_Op.ORDER, _Op.LIMIT, _Op.OFFSET, _Op.RANGE})

from pydantic import BaseModel, TypeAdapter

from .._exceptions import (
    SupabaseORMDoesNotExist,
    SupabaseORMMultipleObjectsReturned,
    SupabaseORMUsageError,
)
from .._explain import ExplainResult
from .._explain import from_builder as _explain_from_builder
from .._filters import apply_op, compile_predicate
from .._predicates import Column, Order, Predicate
from .._returning import ReturnMode, validate_returning
from .._serializers import serialize
from ._client import get_client
from ._log import execute_logged

if TYPE_CHECKING:
    from ._base import SupabaseModel

# Result-row type. Bound to BaseModel so ``as_()`` can rebind the validator
# to any Pydantic model (not just SupabaseModel subclasses).
T = TypeVar("T", bound=BaseModel)
U = TypeVar("U", bound=BaseModel)


# Cache ``TypeAdapter(list[Model])`` per target — adapter creation is non-trivial
# and ``as_()`` is hot.
_BASEMODEL_ADAPTERS: dict[type[BaseModel], TypeAdapter] = {}


def _adapter_for(model: type[BaseModel]) -> TypeAdapter:
    a = _BASEMODEL_ADAPTERS.get(model)
    if a is None:
        a = TypeAdapter(list[model])
        _BASEMODEL_ADAPTERS[model] = a
    return a


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

    # Two ways to compose OR/NOT branches:
    #
    #   1. Predicate objects (preferred, since 0.2.0) ─ typed & composable::
    #
    #          Pet.query.or_(
    #              Pet.f.species == "cat",
    #              (Pet.f.species == "dog") & (Pet.f.age >= 5),
    #          )
    #
    #   2. Lambda callbacks (legacy, kept for backward compat with 0.1.x)::
    #
    #          Pet.query.or_(lambda q: q.eq("species", "cat"))
    #
    # The two forms can't be mixed in a single call — we raise ``UsageError``
    # rather than silently picking one. ``@overload`` gives type checkers
    # the precise signature for each form.

    @overload
    def or_(self, *predicates: Predicate) -> Self: ...
    @overload
    def or_(
        self, *branches: Callable[["_PredicateGroup"], "_PredicateGroup"]
    ) -> Self: ...
    def or_(self, *args: Any) -> Self:
        if not args:
            raise SupabaseORMUsageError("or_() requires at least one branch.")
        is_pred = [isinstance(a, Predicate) for a in args]
        if all(is_pred):
            compiled = ",".join(cast(Predicate, a)._compile() for a in args)
            return self._apply_predicate_group(f"or({compiled})")
        if not any(is_pred):
            compiled = _compile_branches(self._model, args)
            return self._apply_predicate_group(f"or({compiled})")
        raise SupabaseORMUsageError(
            "or_() can't mix Predicate args with lambda branches in a single call."
        )

    @overload
    def not_(self, predicate: Predicate) -> Self: ...
    @overload
    def not_(
        self, branch: Callable[["_PredicateGroup"], "_PredicateGroup"]
    ) -> Self: ...
    def not_(self, arg: Any) -> Self:
        if isinstance(arg, Predicate):
            # Route through ``~`` (i.e. _PredicateNot._compile) so atoms get
            # wrapped in ``not.and(...)`` — bare ``not.col.op.val`` doesn't
            # parse inside PostgREST's logic tree.
            return self._apply_predicate_group((~arg)._compile())
        # Legacy lambda form.
        sub = _PredicateGroup(self._model)
        arg(sub)
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


def _fmt_op(op: tuple) -> str:
    """Format a single recorded op-log tuple for ``QueryBuilder.__repr__``."""
    kind = op[0]
    if kind is _Op.OP:
        return f"{op[1]}({op[2]!r}, {op[3]!r})"
    if kind is _Op.OR:
        return f"or({op[1]})"
    if kind is _Op.MATCH:
        return f"match({op[1]!r})"
    if kind is _Op.ORDER:
        o = op[1]
        d = "desc" if o.desc else "asc"
        n = f" nulls={o.nulls}" if o.nulls else ""
        return f"order({o.column}.{d}{n})"
    if kind is _Op.LIMIT:
        return f"limit({op[1]})"
    if kind is _Op.OFFSET:
        return f"offset({op[1]})"
    if kind is _Op.RANGE:
        return f"range({op[1]}, {op[2]})"
    if kind is _Op.FILTER:
        return f"filter({op[1]!r}, {op[2]!r}, {op[3]!r})"
    return str(op)


# postgrest-py's filter builder (update/delete return) lacks order/limit/
# offset/range; PostgREST honors the URL params directly on PATCH/DELETE.
def _replay_order(target: Any, order: Order) -> None:
    if hasattr(target, "order"):
        kw: dict[str, Any] = {"desc": order.desc}
        if order.nulls is not None:
            kw["nullsfirst"] = order.nulls == "first"
        target.order(order.column, **kw)
        return
    suffix = (
        f".{'nullsfirst' if order.nulls == 'first' else 'nullslast'}"
        if order.nulls is not None
        else ""
    )
    direction = "desc" if order.desc else "asc"
    existing = target.request.params.get("order")
    value = f"{existing + ',' if existing else ''}{order.column}.{direction}{suffix}"
    target.request.params = target.request.params.set("order", value)


def _replay_limit(target: Any, size: int) -> None:
    if hasattr(target, "limit"):
        target.limit(size)
        return
    target.request.params = target.request.params.add("limit", size)


def _replay_offset(target: Any, size: int) -> None:
    if hasattr(target, "offset"):
        target.offset(size)
        return
    target.request.params = target.request.params.add("offset", size)


def _replay_range(target: Any, start: int, end: int) -> None:
    if hasattr(target, "range"):
        target.range(start, end)
        return
    target.request.params = target.request.params.add("offset", start)
    target.request.params = target.request.params.add("limit", end - start + 1)


def _coerce_order(spec: "str | Column | Order") -> Order:
    """Normalize an ``order_by`` arg to an :class:`Order` instance."""
    if isinstance(spec, Order):
        return spec
    if isinstance(spec, Column):
        return Order(spec._name, desc=False)
    return Order.parse(spec)


# ─── QueryBuilder ──────────────────────────────────────────────────────────


class QueryBuilder(_Filterable, Generic[T]):
    """Chainable query builder. Subclass to add project-specific methods.

    Default chain shape::

        Pet.query.eq("species", "cat").gte("age", 3).limit(10).all()

    Subclass example — add a ``paginate(page, size)`` shortcut and bind it via
    ``query_class=`` so every ``Model.query`` returns the custom builder::

        class PaginatedQB(QueryBuilder):
            def paginate(self, page: int, size: int = 50) -> "PaginatedQB":
                return self.range(page * size, (page + 1) * size - 1)

        class Pet(SupabaseModel, table="pets", query_class=PaginatedQB):
            id: UUID
            name: str

        page_two = Pet.query.eq("adopted", False).paginate(2).all()
    """

    _model: type[T]

    def __init__(self, model: type[T]) -> None:
        self._model = model
        self._select: str = model.__select__
        # When set by ``as_(plain BaseModel)``, overrides row validation —
        # source still owns table/predicates/select/iter PK.
        self._validator: TypeAdapter | None = None
        # Chain calls only append here. Terminals resolve ``get_client()``
        # fresh and replay this log — so chains built before a
        # ``use_client()`` block still see the current binding at execute time.
        self._ops: list[tuple] = []

    def __repr__(self) -> str:
        parts = [f"QueryBuilder[{self._model.__name__}]", f"select={self._select!r}"]
        if self._ops:
            parts.append(f"ops=[{', '.join(_fmt_op(op) for op in self._ops)}]")
        return f"<{' '.join(parts)}>"

    # ─── Filter mixin hooks ────────────────────────────────────────────────

    def _apply_op(self, name: str, column: str, value: Any) -> Self:
        self._model._validate_column(column)
        self._ops.append((_Op.OP, name, column, value))
        return self

    def _apply_predicate_group(self, group: str) -> Self:
        # postgrest-py's ``or_`` accepts the body of either an or-group or a
        # not.and-group; we build the wrapped string in ``_Filterable.or_/not_``.
        inner = group[3:-1] if group.startswith("or(") else group
        self._ops.append((_Op.OR, inner))
        return self

    # ─── Selection & ordering ──────────────────────────────────────────────

    def match(self, query: dict[str, Any]) -> Self:
        """Filter rows where every ``column == value`` pair in ``query`` holds.

        PostgREST's ``match`` is multi-column by design — it has no single
        ``column`` argument. Use it for compound equality filters::

            Pet.query.match({"species": "cat", "adopted": False}).all()

        Equivalent to chaining ``.eq()`` per pair. Not available inside
        ``or_()`` / ``not_()`` (no predicate-string form).
        """
        for col in query:
            self._model._validate_column(col)
        serialized = {k: serialize(v) for k, v in query.items()}
        self._ops.append((_Op.MATCH, serialized))
        return self

    def order_by(self, *columns: "str | Column | Order") -> Self:
        """Order results by one or more columns.

        Three accepted forms — mix freely::

            Pet.query.order_by("-created_at", "name")           # string shorthand
            Pet.query.order_by(Pet.f.created_at.desc())         # typed
            Pet.query.order_by(Pet.f.last_login.desc(nulls="last"))

        Strings use the Django ``"-col"`` prefix for descending. The typed
        form unlocks ``nulls="first"`` / ``"last"`` ordering, which strings
        don't expose.
        """
        for c in columns:
            order = _coerce_order(c)
            self._model._validate_column(order.column)
            self._ops.append((_Op.ORDER, self._order_for_relation(order)))
        return self

    def _order_for_relation(self, order: Order) -> Order:
        """Rewrite ``rel.col`` ordering to PostgREST's embed form ``rel(col)``.

        Whether the shape is orderable is PostgREST's call — a bad *column* is
        still caught early by ``_validate_column``.
        """
        head, dot, rest = order.column.partition(".")
        if not dot or head not in self._model.__relations__:
            return order
        return Order(column=f"{head}({rest})", desc=order.desc, nulls=order.nulls)

    def limit(self, n: int) -> Self:
        self._ops.append((_Op.LIMIT, n))
        return self

    def offset(self, n: int) -> Self:
        self._ops.append((_Op.OFFSET, n))
        return self

    def range(self, start: int, end: int) -> Self:
        self._ops.append((_Op.RANGE, start, end))
        return self

    # ─── Projection / rebind ───────────────────────────────────────────────

    def as_(self, target: type[U]) -> "QueryBuilder[U]":
        """Rebind the response shape.

        Two modes:

        - **Same-table SupabaseModel** — narrows the wire ``select`` to the
          target's ``__select__`` and validates against it.
        - **Plain BaseModel** — validation only, wire ``select`` unchanged.
          Use when filtering on source columns the lean target doesn't expose.

        Cross-table SupabaseModel targets raise.

        Args:
            target: A Pydantic ``BaseModel`` subclass; a same-table
                :class:`SupabaseModel` to narrow projection, or any plain
                ``BaseModel`` for validation-only rebinding.
        """
        # Late import — _base imports from _query, so we can't import at
        # module load.
        from ._base import SupabaseModel

        if not (isinstance(target, type) and issubclass(target, BaseModel)):
            raise SupabaseORMUsageError(
                f"as_({target!r}) requires a Pydantic BaseModel subclass."
            )

        if issubclass(target, SupabaseModel):
            if target.__table__ != self._model.__table__:
                raise SupabaseORMUsageError(
                    f"as_({target.__name__}): different table "
                    f"({target.__table__!r} != {self._model.__table__!r}). "
                    "Either point both SupabaseModels at the same __table__, "
                    "or pass a plain BaseModel for validation-only rebinding."
                )
            self._model = cast("type[T]", target)
            self._select = target.__select__
            self._validator = None
            return cast("QueryBuilder[U]", self)

        self._validator = _adapter_for(target)
        return cast("QueryBuilder[U]", self)

    def values(self, *columns: str) -> list[dict[str, Any]]:
        """Run the query with an ad-hoc column projection. Returns raw dicts.

        No Pydantic validation, no autocomplete — caller deals with
        ``row["col"]``. Use for exports or ad-hoc admin queries.

        Args:
            *columns: One or more column names. May include PostgREST embed
                syntax (e.g. ``"pets(id,name)"``).
        """
        if not columns:
            raise SupabaseORMUsageError(".values() requires at least one column.")
        b = self._make_select(select=",".join(columns))
        resp = execute_logged(b)
        return resp.data or []

    # ─── Debug ─────────────────────────────────────────────────────────────

    def explain(self, *, redact: bool = True) -> ExplainResult:
        """Resolved HTTP request — no execute.

        Args:
            redact: When True (default), auth headers (``apikey``,
                ``Authorization``, ``Cookie``) are replaced with
                ``***REDACTED***``.
        """
        return _explain_from_builder(self._make_select(), redact=redact)

    # ─── Escape hatch ──────────────────────────────────────────────────────

    def raw(self) -> Any:
        """Return the underlying postgrest builder for ops we don't model.

        Resolves the client at call time, so the builder is bound to the
        current ContextVar — pair with ``use_client()`` in a request
        scope and the escape hatch sees the same client as the rest of
        your handler. Pair with :func:`supabase_orm.serialize` if you
        need wire-value coercion for non-JSON-native python types.
        """
        return self._make_select()

    # ─── Build helpers ─────────────────────────────────────────────────────

    def _make_select(self, *, select: str | None = None, **select_kw: Any) -> Any:
        """Build a fresh select-style postgrest builder, replay the op log."""
        b = (
            get_client()
            .table(self._model.__table__)
            .select(select if select is not None else self._select, **select_kw)
        )
        b = self._replay(b)
        return self._apply_relation_filters_on(b)

    # ─── Internal replay ───────────────────────────────────────────────────

    def _replay(self, target: Any) -> Any:
        """Replay the recorded op log onto ``target`` (a postgrest builder)."""
        for op in self._ops:
            kind = op[0]
            if kind is _Op.OP:
                _, name, col, val = op
                target = apply_op(target, name, col, val)
            elif kind is _Op.OR:
                target = target.or_(op[1])
            elif kind is _Op.ORDER:
                _replay_order(target, op[1])
            elif kind is _Op.LIMIT:
                _replay_limit(target, op[1])
            elif kind is _Op.OFFSET:
                _replay_offset(target, op[1])
            elif kind is _Op.RANGE:
                _replay_range(target, op[1], op[2])
            elif kind is _Op.MATCH:
                target = target.match(op[1])
            elif kind is _Op.FILTER:
                _, col, operator, value = op
                target = target.filter(col, operator, value)
        return target

    def _apply_relation_filters_on(self, target: Any) -> Any:
        """Apply pre-baked ``Relation(filter=...)`` clauses to ``target``."""
        for col, op, value in self._model.__relation_filter_specs__:
            target = target.filter(col, op, value)
        return target

    def _has_filter(self) -> bool:
        """``True`` if any narrowing op (filter / or-group) is recorded.

        Used by ``delete()``/``update()`` as a foot-gun guard so an
        unfiltered ``.query.delete()`` raises rather than wiping the table.
        """
        return any(op[0] in _FILTERING_OPS for op in self._ops)

    # ─── Read terminals ────────────────────────────────────────────────────

    def all(self) -> list[T]:
        resp = execute_logged(self._make_select())
        return self._validate_rows(resp.data or [])

    def all_with_count(self) -> tuple[list[T], int]:
        """Run the query and ask PostgREST for an exact total in one round-trip.

        Useful for paginated endpoints — saves a separate ``.count()`` call.
        ``count="exact"`` is computed on the FILTERED row set, ignoring
        ``limit``/``offset``, which is the standard pagination semantics.
        """
        resp = execute_logged(self._make_select(count="exact"))
        rows = self._validate_rows(resp.data or [])
        return rows, getattr(resp, "count", None) or 0

    def _take(self, n: int) -> list[T]:
        """Ad-hoc ``.limit(n)`` without polluting the op log."""
        resp = execute_logged(self._make_select().limit(n))
        return self._validate_rows(resp.data or [])

    def first(self) -> T | None:
        rows = self._take(1)
        return rows[0] if rows else None

    def one(self) -> T:
        rows = self._take(2)
        if not rows:
            raise SupabaseORMDoesNotExist(f"No {self._model.__name__} matched query")
        if len(rows) > 1:
            raise SupabaseORMMultipleObjectsReturned(
                f"Multiple {self._model.__name__} rows matched; expected exactly one"
            )
        return rows[0]

    def maybe_one(self) -> T | None:
        rows = self._take(2)
        if not rows:
            return None
        if len(rows) > 1:
            raise SupabaseORMMultipleObjectsReturned(
                f"Multiple {self._model.__name__} rows matched; "
                "use .first() if you want the first"
            )
        return rows[0]

    def count(self) -> int:
        """Exact count, head-only request. Embed-aware select keeps ``!inner`` joins."""
        b = self._make_select(count="exact", head=True)
        resp = execute_logged(b)
        return getattr(resp, "count", None) or 0

    def exists(self) -> bool:
        """``True`` iff any row matches. Embed-aware select + ``limit=1``, no validation."""
        b = self._make_select().limit(1)
        resp = execute_logged(b)
        return bool(resp.data)

    def iter(self, *, batch_size: int = 1000) -> Iterator[T]:
        """Yield every matching row using PK keyset pagination.

        Constant-time per batch (uses the PK index). Owns ordering and
        pagination — chaining ``.order_by()`` / ``.limit()`` / ``.offset()``
        / ``.range()`` before ``.iter()`` raises.

        Snapshot semantics are loose: rows with ``pk > cursor`` inserted
        mid-iteration are picked up; rows with ``pk < cursor`` are missed.
        With monotonic PKs (UUIDv7, serial) the latter can't happen.
        Race-safe for concurrent deletes.

        Args:
            batch_size: Rows per round-trip.
        """
        model = self._model
        pk = model.__pk__
        if pk not in model.model_fields:
            raise SupabaseORMUsageError(
                f"{model.__name__}.iter() needs __pk__ {pk!r} to be a model field."
            )
        for op in self._ops:
            if op[0] in _ITER_FORBIDDEN_OPS:
                raise SupabaseORMUsageError(
                    f"iter() owns ordering and pagination — drop the chained "
                    f".{op[0].value}() call."
                )
        return self._iter_impl(pk, batch_size)

    def _iter_impl(self, pk: str, batch_size: int) -> Iterator[T]:
        cursor: Any = None
        while True:
            b = self._make_select()
            if cursor is not None:
                b = b.gt(pk, serialize(cursor))
            b = b.order(pk, desc=False).limit(batch_size)
            resp = execute_logged(b)
            data = resp.data or []
            if not data:
                return
            rows = self._validate_rows(data)
            for row in rows:
                yield row
            if len(data) < batch_size:
                return
            # Cursor from raw dict, not the validated row — works when
            # ``as_(plain BaseModel)`` strips the PK from the row type.
            cursor = data[-1][pk]

    # ─── Write terminals ───────────────────────────────────────────────────

    @overload
    def delete(
        self,
        *,
        allow_unfiltered: bool = ...,
        returning: Literal["representation"] = ...,
    ) -> list[T]: ...
    @overload
    def delete(
        self, *, allow_unfiltered: bool = ..., returning: Literal["minimal"]
    ) -> None: ...
    def delete(
        self,
        *,
        allow_unfiltered: bool = False,
        returning: ReturnMode = "representation",
    ) -> list[T] | None:
        """Bulk-delete every matching row.

        Args:
            allow_unfiltered: Required to delete every row when no filter is
                chained; PostgREST also rejects unfiltered DELETE server-side.
            returning: ``"minimal"`` skips the body and returns ``None``.

        Returns:
            The deleted rows, or ``None`` when ``returning="minimal"``.
        """
        validate_returning(returning)
        if not allow_unfiltered and not self._has_filter():
            raise SupabaseORMUsageError(
                "Refusing unfiltered .delete() — chain at least one filter or "
                "pass allow_unfiltered=True to wipe the table."
            )
        b = get_client().table(self._model.__table__).delete(returning=returning)
        b = self._replay(b)
        b = self._apply_relation_filters_on(b)
        resp = execute_logged(b)
        if returning == "minimal":
            return None
        return self._validate_rows(resp.data or [])

    @overload
    def update(
        self,
        *,
        allow_unfiltered: bool = ...,
        returning: Literal["representation"] = ...,
        **values: Any,
    ) -> list[T]: ...
    @overload
    def update(
        self,
        *,
        allow_unfiltered: bool = ...,
        returning: Literal["minimal"],
        **values: Any,
    ) -> None: ...
    def update(
        self,
        *,
        allow_unfiltered: bool = False,
        returning: ReturnMode = "representation",
        **values: Any,
    ) -> list[T] | None:
        """Bulk-update every matching row.

        Args:
            allow_unfiltered: Required to update every row when no filter is
                chained.
            returning: ``"minimal"`` skips the body and returns ``None``.
            **values: Column=value pairs to set.

        Returns:
            The updated rows, or ``None`` when ``returning="minimal"``.
        """
        validate_returning(returning)
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
        b = (
            get_client()
            .table(self._model.__table__)
            .update(payload, returning=returning)
        )
        b = self._replay(b)
        b = self._apply_relation_filters_on(b)
        resp = execute_logged(b)
        if returning == "minimal":
            return None
        return self._validate_rows(resp.data or [])

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _validate_rows(self, data: list[dict[str, Any]]) -> list[T]:
        if self._validator is not None:
            return self._validator.validate_python(data)
        adapter = self._model.__list_adapter__
        if adapter is not None:
            return adapter.validate_python(data)
        return [self._model.model_validate(r) for r in data]
