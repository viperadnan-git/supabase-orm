"""Typed predicate builder.

Lets callers express filters as Python expressions instead of lambda
callbacks::

    await Pet.query.or_(
        Pet.f.species == "cat",
        (Pet.f.species == "dog") & (Pet.f.age >= 5),
    ).all()

Implementation:

* :class:`Column` — exposes every PostgREST operator as a typed method,
  with ``==`` / ``!=`` / ``<`` / ``<=`` / ``>`` / ``>=`` overloads that
  return a :class:`Predicate` instead of ``bool``.
* :class:`Predicate` — composable AST node. ``|`` builds an OR group,
  ``&`` an AND group, ``~`` a NOT. Each node compiles to a single
  PostgREST predicate string (``and(...)`` / ``or(...)`` / ``not.<x>``).
* :class:`_FieldsAccess` — runtime namespace exposed as
  ``Model.f``. ``Model.f.<column>`` resolves to a typed
  :class:`Column`. Statically declared with ``__getattr__`` so type
  checkers accept any field name without losing operator return
  types.

The ``_PredicateAtom``/``_PredicateAnd``/``_PredicateOr``/
``_PredicateNot`` subclasses live in this module too. They're private
to the compile pipeline — callers should only ever see :class:`Predicate`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ._filters import compile_predicate

if TYPE_CHECKING:
    from ._base import SupabaseModel

T = TypeVar("T")


# ─── Predicate AST ────────────────────────────────────────────────────────


class Predicate:
    """Composable boolean expression that compiles to a PostgREST predicate.

    Build with :class:`Column` operators (``==`` / ``>=`` / ``.in_()`` /
    ``.like()`` / ...) and combine with ``|`` / ``&`` / ``~``::

        (Pet.f.species == "cat") | (Pet.f.age >= 5)
        ~(Pet.f.adopted == True)

    Pass to :meth:`QueryBuilder.or_` or :meth:`QueryBuilder.not_`.
    """

    def _compile(self) -> str:
        raise NotImplementedError  # pragma: no cover — abstract

    def __or__(self, other: Predicate) -> Predicate:
        if not isinstance(other, Predicate):
            return NotImplemented
        return _PredicateOr(
            _flatten(self, _PredicateOr) + _flatten(other, _PredicateOr)
        )

    def __and__(self, other: Predicate) -> Predicate:
        if not isinstance(other, Predicate):
            return NotImplemented
        return _PredicateAnd(
            _flatten(self, _PredicateAnd) + _flatten(other, _PredicateAnd)
        )

    def __invert__(self) -> Predicate:
        return _PredicateNot(self)

    # Predicates aren't hashable and aren't booleans. ``bool(pred)`` would be
    # a foot-gun (``if Pet.f.age >= 5:`` reads natural but never runs the
    # query) — fail loudly instead.
    def __bool__(self) -> bool:
        raise TypeError(
            "Predicate is not a bool. Pass it to .or_() / .not_() instead of "
            "evaluating it directly."
        )


def _flatten(p: Predicate, kind: type[Predicate]) -> list[Predicate]:
    """Flatten same-kind nesting so ``a | b | c`` compiles to
    ``or(a,b,c)`` instead of ``or(or(a,b),c)``."""
    if isinstance(p, kind):
        # ``parts`` is set by the And/Or subclasses below; safe to read here.
        return list(p.parts)  # type: ignore[attr-defined]
    return [p]


class _PredicateAtom(Predicate):
    """Single ``column.op.value`` filter."""

    __slots__ = ("op", "column", "value")

    def __init__(self, op: str, column: str, value: Any) -> None:
        self.op = op
        self.column = column
        self.value = value

    def _compile(self) -> str:
        return compile_predicate(self.op, self.column, self.value)


class _PredicateGroupBase(Predicate):
    """Shared body for ``and(...)`` / ``or(...)`` AST nodes — same shape,
    different keyword. Subclasses set :attr:`_kw` to ``"and"`` or ``"or"``."""

    __slots__ = ("parts",)
    _kw: str = ""

    def __init__(self, parts: list[Predicate]) -> None:
        self.parts = parts

    def _compile(self) -> str:
        return f"{self._kw}(" + ",".join(p._compile() for p in self.parts) + ")"


class _PredicateAnd(_PredicateGroupBase):
    _kw = "and"


class _PredicateOr(_PredicateGroupBase):
    _kw = "or"


class _PredicateNot(Predicate):
    __slots__ = ("inner",)

    def __init__(self, inner: Predicate) -> None:
        self.inner = inner

    def _compile(self) -> str:
        # PostgREST logic trees accept ``not.and(...)`` / ``not.or(...)`` but
        # *not* a bare ``not.col.op.val`` atom. Wrap atoms in a single-element
        # ``and()`` so ``~(Pet.f.species == "cat")`` parses correctly inside
        # ``or=(...)``.
        if isinstance(self.inner, _PredicateAtom):
            return "not.and(" + self.inner._compile() + ")"
        return "not." + self.inner._compile()


# ─── Column ───────────────────────────────────────────────────────────────


class Column(Generic[T]):
    """Typed column reference. Operators build :class:`Predicate` nodes.

    Don't construct directly — access via ``Model.f.<column>``.
    """

    __slots__ = ("_name", "_model")

    def __init__(self, name: str, model: type[SupabaseModel]) -> None:
        self._name = name
        self._model = model

    def __repr__(self) -> str:
        return f"<Column {self._model.__name__}.{self._name}>"

    def _atom(self, op: str, value: Any) -> Predicate:
        """Single source of truth for ``Column → Predicate`` construction."""
        return _PredicateAtom(op, self._name, value)

    # ─── Symbolic operators ────────────────────────────────────────────────

    # ``__eq__`` / ``__ne__`` deliberately return Predicate, not bool — same
    # trick SQLAlchemy uses. Type checkers want ``bool`` here, so we suppress
    # the override warning per method.

    def __eq__(self, other: T) -> Predicate:  # type: ignore[override]
        return self._atom("eq", other)

    def __ne__(self, other: T) -> Predicate:  # type: ignore[override]
        return self._atom("neq", other)

    def __lt__(self, other: T) -> Predicate:
        return self._atom("lt", other)

    def __le__(self, other: T) -> Predicate:
        return self._atom("lte", other)

    def __gt__(self, other: T) -> Predicate:
        return self._atom("gt", other)

    def __ge__(self, other: T) -> Predicate:
        return self._atom("gte", other)

    # Disable hashing — predicate-building objects mustn't be dict keys.
    __hash__ = None  # type: ignore[assignment]

    # ─── Method-form operators (no symbol available) ───────────────────────

    def in_(self, values: Sequence[T]) -> Predicate:
        return self._atom("in_", values)

    def is_(self, value: bool | None) -> Predicate:
        return self._atom("is_", value)

    def is_null(self) -> Predicate:
        """Sugar for ``col.is_(None)`` — checks ``IS NULL``."""
        return self._atom("is_", None)

    def like(self, pattern: str) -> Predicate:
        return self._atom("like", pattern)

    def ilike(self, pattern: str) -> Predicate:
        return self._atom("ilike", pattern)

    def contains(self, value: Any) -> Predicate:
        return self._atom("contains", value)

    def contained_by(self, value: Any) -> Predicate:
        return self._atom("contained_by", value)

    def overlaps(self, value: Any) -> Predicate:
        return self._atom("overlaps", value)

    def fts(self, query: str) -> Predicate:
        return self._atom("fts", query)

    def plfts(self, query: str) -> Predicate:
        return self._atom("plfts", query)

    def phfts(self, query: str) -> Predicate:
        return self._atom("phfts", query)

    def wfts(self, query: str) -> Predicate:
        return self._atom("wfts", query)


# ─── f namespace ──────────────────────────────────────────────────────────


class _FieldsAccess:
    """Runtime namespace exposing typed :class:`Column`\\s for a model.

    Created once per :class:`SupabaseModel` subclass and attached as
    ``Model.f``. Statically typed with ``__getattr__`` so callers can
    use any column name without triggering "unknown attribute" errors
    from type checkers — the operators on the returned ``Column[Any]``
    are still fully typed, so ``Pet.f.age >= 5`` resolves to
    :class:`Predicate`, never ``bool``.
    """

    __slots__ = ("_model", "_columns")

    def __init__(self, model: type[SupabaseModel]) -> None:
        self._model = model
        self._columns: dict[str, Column[Any]] = {
            name: Column(name, model) for name in model.model_fields
        }

    def __getattr__(self, name: str) -> Column[Any]:
        try:
            return self._columns[name]
        except KeyError:
            raise AttributeError(
                f"{self._model.__name__} has no column {name!r}. "
                f"Known: {sorted(self._columns)}"
            ) from None

    def __repr__(self) -> str:
        return f"<{self._model.__name__}.f: {sorted(self._columns)}>"

    # Help IDEs that walk ``dir()`` for autocomplete.
    def __dir__(self) -> list[str]:
        return list(self._columns)
