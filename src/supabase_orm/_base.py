"""SupabaseModel — Pydantic + PostgREST ORM base.

Subclass with ``table=``:

    class Pet(SupabaseModel, table="pets"):
        id: UUID
        name: str
        species: str
        adopted: bool

Then chain queries off ``Model.query``:

    rows = await Pet.query.eq("species", "cat").order_by("-created_at").limit(10).all()
    one  = await Pet.get(id)
    p    = await Pet.create(name="Whiskers", species="cat", adopted=False)
    p.name = "Mr. Whiskers"; await p.save()
    await p.delete()
    await Pet.query.eq("adopted", False).delete()                 # bulk
    await Pet.query.eq("adopted", False).update(adopted=True)     # bulk
"""

from __future__ import annotations

from typing import Any, ClassVar, Self, TypeVar

from pydantic import BaseModel, ConfigDict, TypeAdapter

from ._client import get_client
from ._embed import Relation, build_select, collect_relations
from ._exceptions import SupabaseORMDoesNotExist, SupabaseORMUsageError
from ._filters import compile_value
from ._predicates import _FieldsAccess
from ._query import QueryBuilder
from ._serializers import serialize

_T = TypeVar("_T", bound="SupabaseModel")


def _compile_relation_filter_specs(
    relations: dict[str, tuple[type, bool, Relation]],
) -> tuple[tuple[str, str, str], ...]:
    """Pre-bake ``Relation(filter=...)`` specs into ``(col, op, wire)`` triples
    ready to feed into postgrest's ``.filter(col, op, value)``."""
    specs: list[tuple[str, str, str]] = []
    for fname, (_cls, _is_list, relation) in relations.items():
        if not relation.filter:
            continue
        for key, val in relation.filter.items():
            col, _, op = key.partition("__")
            op = op or "eq"
            specs.append((f"{fname}.{col}", op, compile_value(op, val)))
    return tuple(specs)


class _QueryDescriptor:
    """Returns a fresh ``QueryBuilder[Owner]`` per access.

    Typed via the ``owner`` parameter, so ``Pet.query`` is inferred as
    ``QueryBuilder[Pet]`` by static checkers — every operator on the chain
    has a real signature and works with autocomplete.
    """

    def __get__(self, instance: Any, owner: type[_T]) -> "QueryBuilder[_T]":
        if not owner.__table__:
            raise SupabaseORMUsageError(
                f"{owner.__name__} has no __table__. Declare with "
                f'`class {owner.__name__}(SupabaseModel, table="..."):`'
            )
        return owner.__query_class__(owner)


class SupabaseModel(BaseModel):
    """Base class for tables. Configure per-subclass via class kwargs.

    Class kwargs:
        table:        PostgREST table / view name. Required on concrete subclasses.
        pk:           Primary key field name. Default ``"id"``.
        select:       Override the auto-derived select string (escape hatch).
        query_class:  Use a custom :class:`QueryBuilder` subclass for ``.query``.
                      Inherited via MRO, so a project-wide base model can set it
                      once and every subclass picks it up::

                          class _AppModel(SupabaseModel):
                              __query_class__ = MyQueryBuilder

                          class User(_AppModel, table="users"):
                              ...
    """

    model_config = ConfigDict(
        validate_assignment=True,
        extra="ignore",
    )

    __table__: ClassVar[str] = ""
    __pk__: ClassVar[str] = "id"
    __select__: ClassVar[str] = ""
    __select_override__: ClassVar[str | None] = None
    # Populated by ``__pydantic_init_subclass__`` so hot paths don't reflect
    # over ``model_fields`` on every query.
    __relations__: ClassVar[dict[str, tuple[type, bool, Relation]]] = {}
    # Pre-compiled ``(col, op, wire)`` triples ready to feed straight into
    # postgrest's ``.filter(...)``. Built once per subclass.
    __relation_filter_specs__: ClassVar[tuple[tuple[str, str, str], ...]] = ()
    __list_adapter__: ClassVar[TypeAdapter | None] = None
    # Custom QueryBuilder subclass (MRO-inherited). Override per-project
    # via a base class or per-model via ``query_class=`` kwarg.
    __query_class__: ClassVar[type["QueryBuilder"]] = QueryBuilder

    query: ClassVar[_QueryDescriptor] = _QueryDescriptor()
    # Typed predicate namespace — ``Pet.f.age >= 5`` returns a Predicate.
    # The actual ``_FieldsAccess`` instance is attached per subclass in
    # ``__pydantic_init_subclass__``; declared here for type checkers.
    f: ClassVar[_FieldsAccess]

    def __init_subclass__(
        cls,
        *,
        table: str | None = None,
        pk: str = "id",
        select: str | None = None,
        query_class: type["QueryBuilder"] | None = None,
        **kw: Any,
    ) -> None:
        # Pydantic populates model_fields AFTER this hook runs, so we just
        # capture the table-level kwargs here. ``__pydantic_init_subclass__``
        # below builds the cached metadata once fields are available.
        super().__init_subclass__(**kw)
        if query_class is not None:
            cls.__query_class__ = query_class
        if table is None:
            return
        cls.__table__ = table
        cls.__pk__ = pk
        cls.__select_override__ = select

    @classmethod
    def __pydantic_init_subclass__(cls, **kw: Any) -> None:
        if not cls.__table__:
            return
        cls.__select__ = (
            cls.__select_override__
            if cls.__select_override__ is not None
            else build_select(cls)
        )
        cls.__relations__ = collect_relations(cls)
        cls.__relation_filter_specs__ = _compile_relation_filter_specs(
            cls.__relations__
        )
        cls.__list_adapter__ = TypeAdapter(list[cls])
        cls.f = _FieldsAccess(cls)

    # ─── Builder entry point ───────────────────────────────────────────────

    @classmethod
    def _validate_column(cls, name: str) -> None:
        """Surface typos at call time. Allows scalar fields and any
        ``relation.column`` form (PostgREST embed-filter syntax)."""
        head, _, _ = name.partition(".")
        if head in cls.model_fields:
            return
        raise AttributeError(
            f"{cls.__name__} has no column {head!r}. Known: {sorted(cls.model_fields)}"
        )

    # ─── PK shortcuts ──────────────────────────────────────────────────────

    @classmethod
    async def get(cls, pk_value: Any) -> Self:
        """Fetch by primary key. Raises ``SupabaseORMDoesNotExist`` on miss."""
        row = await cls.query.eq(cls.__pk__, pk_value).maybe_one()
        if row is None:
            raise SupabaseORMDoesNotExist(
                f"{cls.__name__}({cls.__pk__}={pk_value!r}) not found"
            )
        return row

    @classmethod
    async def find(cls, pk_value: Any) -> Self | None:
        """Fetch by primary key. Returns ``None`` on miss."""
        return await cls.query.eq(cls.__pk__, pk_value).maybe_one()

    # ─── Writes ────────────────────────────────────────────────────────────

    @classmethod
    async def create(cls, **values: Any) -> Self:
        """Insert a row in a single round-trip.

        Uses postgrest's ``insert(...).execute()`` which returns the inserted
        row. For models with relations we still need a second round-trip to
        fetch embeds, since ``insert`` only returns columns from the
        inserted table.
        """
        payload = {k: serialize(v) for k, v in values.items()}
        client = get_client()
        ins = await client.table(cls.__table__).insert(payload).execute()
        if not ins.data:
            raise ValueError(f"{cls.__name__}.create returned no rows")
        if cls.__relations__:
            return await cls.get(ins.data[0][cls.__pk__])
        return cls.model_validate(ins.data[0])

    @classmethod
    async def bulk_create(cls, rows: list[dict[str, Any]]) -> list[Self]:
        if not rows:
            return []
        payload = [{k: serialize(v) for k, v in r.items()} for r in rows]
        client = get_client()
        ins = await client.table(cls.__table__).insert(payload).execute()
        data = ins.data or []
        if not data:
            return []
        if cls.__relations__:
            ids = [r[cls.__pk__] for r in data]
            return await cls.query.in_(cls.__pk__, ids).all()
        adapter = cls.__list_adapter__
        return (
            adapter.validate_python(data)
            if adapter
            else [cls.model_validate(r) for r in data]
        )

    async def update(self, **values: Any) -> Self:
        """Assign the given fields and persist in one call.

        Equivalent to setting each attribute and calling :meth:`save`. Reads
        more naturally for short updates::

            await user.update(email="new@example.com", name="New Name")

        Each assignment runs through Pydantic's validator (because
        ``validate_assignment=True`` is set on ``SupabaseModel``), so
        type errors surface before the round-trip. Raises
        ``SupabaseORMUsageError`` if no values are passed.
        """
        if not values:
            raise SupabaseORMUsageError(
                "instance.update() requires at least one key=value."
            )
        cls = type(self)
        for k in values:
            if k == cls.__pk__:
                raise SupabaseORMUsageError(
                    f"Cannot update primary key {cls.__pk__!r} via .update()."
                )
            if k in cls.__relations__:
                raise SupabaseORMUsageError(
                    f"{k!r} is a relation, not a column on {cls.__table__!r}."
                )
        for k, v in values.items():
            setattr(self, k, v)
        return await self.save()

    async def save(self) -> Self:
        """Persist dirty fields and refresh local state in one round-trip.

        For flat models the UPDATE returns the new row directly. For models
        with relations we still need a follow-up GET to populate embeds.
        """
        cls = type(self)
        dirty = self.__pydantic_fields_set__ - {cls.__pk__} - cls.__relations__.keys()
        if not dirty:
            return self
        payload = {f: serialize(getattr(self, f)) for f in dirty}
        client = get_client()
        pk_val = serialize(getattr(self, cls.__pk__))
        resp = await (
            client.table(cls.__table__).update(payload).eq(cls.__pk__, pk_val).execute()
        )
        if not resp.data:
            raise SupabaseORMDoesNotExist(
                f"{cls.__name__}({cls.__pk__}={getattr(self, cls.__pk__)!r}) "
                "not found during save"
            )
        if cls.__relations__:
            fresh = await cls.get(getattr(self, cls.__pk__))
        else:
            fresh = cls.model_validate(resp.data[0])
        self.__dict__.update(fresh.__dict__)
        object.__setattr__(self, "__pydantic_fields_set__", set())
        return self

    async def delete(self) -> None:
        """Delete this single row by primary key."""
        cls = type(self)
        client = get_client()
        await (
            client.table(cls.__table__)
            .delete()
            .eq(cls.__pk__, serialize(getattr(self, cls.__pk__)))
            .execute()
        )

    async def refresh(self) -> Self:
        cls = type(self)
        fresh = await cls.get(getattr(self, cls.__pk__))
        self.__dict__.update(fresh.__dict__)
        object.__setattr__(self, "__pydantic_fields_set__", set())
        return self
