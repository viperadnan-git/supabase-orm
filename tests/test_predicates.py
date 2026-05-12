"""Typed predicate builder — Column[T], Predicate, Model.f."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from supabase_orm import Column, Predicate, SupabaseModel
from supabase_orm._predicates import (
    _FieldsAccess,
    _PredicateAnd,
    _PredicateAtom,
    _PredicateNot,
    _PredicateOr,
)

from .conftest import FakeResponse


class Row(SupabaseModel, table="rows_pred"):
    id: UUID
    name: str
    age: int
    is_active: bool = True
    tags: list[str] = []
    created_at: datetime | None = None


# ─── Model.f namespace ────────────────────────────────────────────────────


def test_f_namespace_is_attached_per_subclass():
    assert isinstance(Row.f, _FieldsAccess)
    # Two different models get their own namespaces.
    assert Row.f is not SupabaseModel.__dict__.get("f")


def test_f_returns_typed_column_per_field():
    col = Row.f.age
    assert isinstance(col, Column)
    assert col._name == "age"
    assert col._model is Row


def test_f_returns_same_column_object_each_access():
    # Cached at construction time — useful so identity comparisons work
    # and we don't allocate per access in tight loops.
    assert Row.f.age is Row.f.age


def test_f_unknown_field_raises_attributeerror():
    with pytest.raises(AttributeError, match="no column 'nope'"):
        _ = Row.f.nope  # type: ignore[attr-defined]


def test_f_dir_lists_columns_for_ide_autocomplete():
    assert set(dir(Row.f)) == set(Row.model_fields)


# ─── Atomic predicates ────────────────────────────────────────────────────


def test_eq_builds_predicate_not_bool():
    p = Row.f.name == "alice"
    assert isinstance(p, Predicate)
    assert isinstance(p, _PredicateAtom)
    assert p._compile() == "name.eq.alice"


def test_ne_builds_neq_predicate():
    p = Row.f.name != "alice"
    assert isinstance(p, Predicate)
    assert p._compile() == "name.neq.alice"


def test_comparison_operators():
    assert (Row.f.age < 18)._compile() == "age.lt.18"
    assert (Row.f.age <= 18)._compile() == "age.lte.18"
    assert (Row.f.age > 18)._compile() == "age.gt.18"
    assert (Row.f.age >= 18)._compile() == "age.gte.18"


def test_method_form_operators():
    assert Row.f.age.in_([1, 2, 3])._compile() == "age.in.(1,2,3)"
    assert Row.f.name.like("a%")._compile() == "name.like.a%"
    assert Row.f.name.ilike("A%")._compile() == "name.ilike.A%"
    # PostgREST's URL-tree wire names are short (cs/cd/ov) and array
    # literals use ``{}`` curly braces, not the ``()`` parens that ``in`` uses.
    assert Row.f.tags.contains(["x"])._compile() == "tags.cs.{x}"
    assert Row.f.tags.contained_by(["x"])._compile() == "tags.cd.{x}"
    assert Row.f.tags.overlaps(["x"])._compile() == "tags.ov.{x}"


def test_is_null_sugar():
    assert Row.f.created_at.is_null()._compile() == "created_at.is.null"
    assert Row.f.created_at.is_(None)._compile() == "created_at.is.null"
    assert Row.f.is_active.is_(True)._compile() == "is_active.is.true"


def test_text_search_operators():
    assert Row.f.name.fts("cat")._compile() == "name.fts.cat"
    assert Row.f.name.plfts("cat")._compile() == "name.plfts.cat"
    assert Row.f.name.phfts("cat")._compile() == "name.phfts.cat"
    assert Row.f.name.wfts("cat")._compile() == "name.wfts.cat"


def test_predicate_serializes_values_via_filter_layer():
    u = uuid4()
    p = Row.f.id == u
    assert p._compile() == f"id.eq.{u}"

    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert (Row.f.created_at == dt)._compile() == f"created_at.eq.{dt.isoformat()}"


# ─── Composition: |, &, ~ ────────────────────────────────────────────────


def test_or_composition():
    p = (Row.f.name == "a") | (Row.f.name == "b")
    assert isinstance(p, _PredicateOr)
    assert p._compile() == "or(name.eq.a,name.eq.b)"


def test_and_composition():
    p = (Row.f.name == "a") & (Row.f.age > 5)
    assert isinstance(p, _PredicateAnd)
    assert p._compile() == "and(name.eq.a,age.gt.5)"


def test_not_composition():
    p = ~(Row.f.is_active == True)  # noqa: E712 (the orm cares about == not is)
    assert isinstance(p, _PredicateNot)
    # Atom-not wraps in single-element and() so it parses inside or=(...).
    assert p._compile() == "not.and(is_active.eq.true)"


def test_or_flattens_same_kind():
    """``a | b | c`` should be ``or(a,b,c)`` not ``or(or(a,b),c)``."""
    p = (Row.f.name == "a") | (Row.f.name == "b") | (Row.f.name == "c")
    assert p._compile() == "or(name.eq.a,name.eq.b,name.eq.c)"


def test_and_flattens_same_kind():
    p = (Row.f.age > 1) & (Row.f.age < 10) & (Row.f.is_active == True)  # noqa: E712
    assert p._compile() == "and(age.gt.1,age.lt.10,is_active.eq.true)"


def test_mixed_and_or_keeps_nesting():
    p = (Row.f.name == "a") | ((Row.f.age >= 5) & (Row.f.is_active == True))  # noqa: E712
    assert p._compile() == "or(name.eq.a,and(age.gte.5,is_active.eq.true))"


def test_not_of_compound_negates_whole_group():
    p = ~((Row.f.name == "a") | (Row.f.name == "b"))
    assert p._compile() == "not.or(name.eq.a,name.eq.b)"


# ─── Foot-gun guards ──────────────────────────────────────────────────────


def test_predicate_is_not_bool():
    """Catches ``if Pet.f.age >= 5:`` mistakes at runtime."""
    p = Row.f.age >= 5
    with pytest.raises(TypeError, match="not a bool"):
        bool(p)


def test_or_with_non_predicate_returns_notimplemented():
    p = Row.f.age >= 5
    # ``__or__`` returning NotImplemented lets Python fall back to the
    # other operand's ``__ror__`` (or raise TypeError if none exists).
    assert p.__or__("x") is NotImplemented  # type: ignore[arg-type]
    assert p.__and__("x") is NotImplemented  # type: ignore[arg-type]


# ─── Integration with QueryBuilder.or_ / not_ ────────────────────────────


async def test_or_accepts_predicate_args(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.or_(
        Row.f.name == "a",
        Row.f.name == "b",
    ).all()
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    assert or_call[1] == ("name.eq.a,name.eq.b",)


async def test_or_predicate_with_and_branch(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.or_(
        Row.f.name == "a",
        (Row.f.name == "b") & (Row.f.age >= 5),
    ).all()
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    assert or_call[1] == ("name.eq.a,and(name.eq.b,age.gte.5)",)


async def test_or_predicate_with_nested_or(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.or_(
        (Row.f.name == "a") | (Row.f.name == "b"),
        Row.f.age >= 5,
    ).all()
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    # Inner ``or(...)`` stays a nested group — PostgREST accepts that.
    assert or_call[1] == ("or(name.eq.a,name.eq.b),age.gte.5",)


async def test_not_accepts_predicate(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.not_(Row.f.is_active == True).all()  # noqa: E712
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    assert or_call[1] == ("not.and(is_active.eq.true)",)


async def test_not_of_or_group(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.not_((Row.f.name == "a") | (Row.f.name == "b")).all()
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    assert or_call[1] == ("not.or(name.eq.a,name.eq.b)",)


async def test_or_requires_at_least_one_branch(fake_client):
    from supabase_orm import SupabaseORMUsageError

    with pytest.raises(SupabaseORMUsageError, match="at least one branch"):
        Row.query.or_()


async def test_or_rejects_mixed_predicate_and_lambda(fake_client):
    from supabase_orm import SupabaseORMUsageError

    with pytest.raises(SupabaseORMUsageError, match="can't mix"):
        Row.query.or_(
            Row.f.name == "a",
            lambda q: q.eq("name", "b"),  # type: ignore[arg-type]
        )


# ─── Backward compat — lambda API still works ────────────────────────────


async def test_or_legacy_lambda_path_still_works(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.or_(
        lambda q: q.eq("name", "a"),
        lambda q: q.eq("name", "b"),
    ).all()
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    assert or_call[1] == ("name.eq.a,name.eq.b",)


async def test_not_legacy_lambda_path_still_works(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.not_(lambda q: q.eq("name", "a")).all()
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    assert or_call[1] == ("not.and(name.eq.a)",)


# ─── Chain integration ───────────────────────────────────────────────────


async def test_predicate_or_composes_with_chain_filters(fake_client):
    """Chain handles AND, predicate-or_ handles OR — they mix freely."""
    fake_client.queue(FakeResponse(data=[]))
    await (
        Row.query.eq("is_active", True)
        .or_(Row.f.name == "a", Row.f.name == "b")
        .order_by("-age")
        .limit(10)
        .all()
    )
    b = fake_client.builders[0]
    calls = [c for c in b.calls if c[0] != "select"]
    assert calls == [
        ("eq", ("is_active", True), {}),
        ("or_", ("name.eq.a,name.eq.b",), {}),
        ("order", ("age",), {"desc": True}),
        ("limit", (10,), {}),
    ]


# ─── Order / .asc() / .desc() ────────────────────────────────────────────


def test_column_asc_returns_order():
    from supabase_orm import Order

    o = Row.f.age.asc()
    assert isinstance(o, Order)
    assert o.column == "age"
    assert o.desc is False
    assert o.nulls is None


def test_column_desc_returns_order():
    o = Row.f.age.desc()
    assert o.column == "age" and o.desc is True


def test_order_with_nulls_position():
    asc = Row.f.created_at.asc(nulls="last")
    desc = Row.f.created_at.desc(nulls="first")
    assert asc.nulls == "last"
    assert desc.nulls == "first"


def test_order_parse_handles_dash_prefix_and_whitespace():
    from supabase_orm import Order

    assert Order.parse("name") == Order("name", desc=False)
    assert Order.parse("-name") == Order("name", desc=True)
    assert Order.parse("  -name  ") == Order("name", desc=True)


async def test_order_by_string_form_unchanged(fake_client):
    """The ``"-col"`` shorthand still works exactly as before."""
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.order_by("-age", "name").all()
    orders = [c for c in fake_client.builders[0].calls if c[0] == "order"]
    assert orders == [
        ("order", ("age",), {"desc": True}),
        ("order", ("name",), {"desc": False}),
    ]


async def test_order_by_typed_column_defaults_to_asc(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.order_by(Row.f.age).all()
    orders = [c for c in fake_client.builders[0].calls if c[0] == "order"]
    assert orders == [("order", ("age",), {"desc": False})]


async def test_order_by_typed_desc(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.order_by(Row.f.age.desc()).all()
    orders = [c for c in fake_client.builders[0].calls if c[0] == "order"]
    assert orders == [("order", ("age",), {"desc": True})]


async def test_order_by_with_nulls_position(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.order_by(
        Row.f.created_at.desc(nulls="last"),
        Row.f.age.asc(nulls="first"),
    ).all()
    orders = [c for c in fake_client.builders[0].calls if c[0] == "order"]
    assert orders == [
        ("order", ("created_at",), {"desc": True, "nullsfirst": False}),
        ("order", ("age",), {"desc": False, "nullsfirst": True}),
    ]


async def test_order_by_mixes_string_and_typed_forms(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.order_by("-age", Row.f.name).all()
    orders = [c for c in fake_client.builders[0].calls if c[0] == "order"]
    assert orders == [
        ("order", ("age",), {"desc": True}),
        ("order", ("name",), {"desc": False}),
    ]


async def test_order_by_validates_string_column():
    """Typos in the string form must surface at call time, not at server time."""
    with pytest.raises(AttributeError, match="no column 'nope'"):
        Row.query.order_by("-nope")


async def test_order_by_validates_order_column():
    """Even when wrapped in Order — validate against model fields."""
    from supabase_orm import Order

    with pytest.raises(AttributeError, match="no column 'nope'"):
        Row.query.order_by(Order("nope", desc=True))
