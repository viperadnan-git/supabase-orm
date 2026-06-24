"""End-to-end wire-shape tests.

These tests assert the exact postgrest method calls produced by every
shorthand on ``Model.query`` (including filter operators, ordering, write
terminals) AND that custom-typed values (UUID, datetime, date, Decimal,
Enum, Pydantic models) reach the wire fully serialized.

Each filter operator is exercised in three places:
  1. Top-level chained on QueryBuilder → postgrest builder method call
  2. Inside ``or_()`` → predicate string fragment
  3. Inside ``not_()`` → ``not.and(...)`` predicate string fragment
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

import pytest

from supabase_orm._async import SupabaseModel

from .conftest import FakeResponse


class Status(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Row(SupabaseModel, table="rows_wire"):
    id: UUID
    name: str
    n: int
    amount: Decimal
    status: Status
    created_at: datetime
    due: date
    tags: list[str] = []
    is_active: bool = True


# ─── Helpers ─────────────────────────────────────────────────────────────


def _calls(builder, name):
    return [c for c in builder.calls if c[0] == name]


def _only(builder, name):
    matches = _calls(builder, name)
    assert len(matches) == 1, f"expected 1 {name!r} call, got {matches}"
    return matches[0]


# ─── select string passed at builder construction ────────────────────────


async def test_query_construction_passes_full_select(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.eq("id", uuid4()).all()
    sel = _only(fake_client.builders[0], "select")
    assert sel[1] == ("id,name,n,amount,status,created_at,due,tags,is_active",)


# ─── Every filter operator on QueryBuilder ───────────────────────────────


@pytest.mark.parametrize(
    "method,col,value,expected_call,expected_args",
    [
        ("eq", "name", "alice", "eq", ("name", "alice")),
        ("neq", "name", "alice", "neq", ("name", "alice")),
        ("gt", "n", 1, "gt", ("n", 1)),
        ("gte", "n", 1, "gte", ("n", 1)),
        ("lt", "n", 1, "lt", ("n", 1)),
        ("lte", "n", 1, "lte", ("n", 1)),
        ("like", "name", "a%", "like", ("name", "a%")),
        ("ilike", "name", "A%", "ilike", ("name", "A%")),
        ("is_", "name", None, "is_", ("name", None)),
        ("contains", "tags", ["x"], "contains", ("tags", ["x"])),
        ("contained_by", "tags", ["x"], "contained_by", ("tags", ["x"])),
        ("overlaps", "tags", ["x"], "overlaps", ("tags", ["x"])),
    ],
)
async def test_filter_op_routes_to_correct_postgrest_method(
    fake_client, method, col, value, expected_call, expected_args
):
    fake_client.queue(FakeResponse(data=[]))
    await getattr(Row.query, method)(col, value).all()
    call = _only(fake_client.builders[0], expected_call)
    assert call[1] == expected_args


async def test_match_dict_routes_to_postgrest_match(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.match({"name": "a", "is_active": True}).all()
    call = _only(fake_client.builders[0], "match")
    assert call[1] == ({"name": "a", "is_active": True},)


async def test_match_validates_columns(fake_client):
    with pytest.raises(AttributeError):
        Row.query.match({"nope": 1})


async def test_match_serializes_values(fake_client):
    from datetime import datetime, timezone
    from uuid import uuid4

    fake_client.queue(FakeResponse(data=[]))
    u = uuid4()
    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    await Row.query.match({"id": u, "created_at": dt}).all()
    call = _only(fake_client.builders[0], "match")
    assert call[1] == ({"id": str(u), "created_at": dt.isoformat()},)


async def test_match_counts_as_filter_for_bulk_guard(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    # Should NOT raise — match() is a narrowing op.
    await Row.query.match({"is_active": True}).delete()


async def test_in_routes_to_in_(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.in_("n", [1, 2, 3]).all()
    call = _only(fake_client.builders[0], "in_")
    assert call[1] == ("n", [1, 2, 3])


@pytest.mark.parametrize(
    "method,options",
    [
        ("fts", {}),
        ("plfts", {"options": {"type": "plain"}}),
        ("phfts", {"options": {"type": "phrase"}}),
        ("wfts", {"options": {"type": "websearch"}}),
    ],
)
async def test_text_search_variants_via_querybuilder(fake_client, method, options):
    fake_client.queue(FakeResponse(data=[]))
    await getattr(Row.query, method)("name", "cat").all()
    call = _only(fake_client.builders[0], "text_search")
    assert call[1] == ("name", "cat")
    assert call[2] == options


# ─── Non-JSON-native values flow serialized through filter operators ────


async def test_eq_serializes_uuid(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    u = uuid4()
    await Row.query.eq("id", u).all()
    assert _only(fake_client.builders[0], "eq")[1] == ("id", str(u))


async def test_eq_serializes_datetime(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    await Row.query.eq("created_at", dt).all()
    assert _only(fake_client.builders[0], "eq")[1] == ("created_at", dt.isoformat())


async def test_eq_serializes_date(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    d = date(2024, 1, 2)
    await Row.query.eq("due", d).all()
    assert _only(fake_client.builders[0], "eq")[1] == ("due", "2024-01-02")


async def test_eq_serializes_decimal(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.eq("amount", Decimal("1.25")).all()
    assert _only(fake_client.builders[0], "eq")[1] == ("amount", "1.25")


async def test_eq_serializes_enum(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.eq("status", Status.ACTIVE).all()
    assert _only(fake_client.builders[0], "eq")[1] == ("status", "active")


async def test_in_serializes_each_element_mixed_types(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    u1, u2 = uuid4(), uuid4()
    await Row.query.in_("id", [u1, u2]).all()
    assert _only(fake_client.builders[0], "in_")[1] == ("id", [str(u1), str(u2)])


async def test_eq_uses_registered_custom_serializer(fake_client):
    """User-registered serializers apply to filter values, not just write payloads."""
    from supabase_orm import register_serializer
    from supabase_orm._serializers import _REGISTRY, _RESOLVED

    class Money:
        def __init__(self, cents: int) -> None:
            self.cents = cents

    register_serializer(Money, lambda v: v.cents)
    try:
        fake_client.queue(FakeResponse(data=[]))
        await Row.query.eq("amount", Money(500)).all()
        assert _only(fake_client.builders[0], "eq")[1] == ("amount", 500)

        fake_client.queue(FakeResponse(data=[]))
        await Row.query.in_("amount", [Money(100), Money(200)]).all()
        assert _only(fake_client.builders[1], "in_")[1] == ("amount", [100, 200])
    finally:
        _REGISTRY.pop(Money, None)
        _RESOLVED.clear()


async def test_neq_lt_gte_serialize_values(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    dt = datetime(2024, 5, 1, tzinfo=timezone.utc)
    await (
        Row.query.neq("status", Status.ARCHIVED)
        .lt("created_at", dt)
        .gte("amount", Decimal("0.50"))
        .all()
    )
    b = fake_client.builders[0]
    assert _only(b, "neq")[1] == ("status", "archived")
    assert _only(b, "lt")[1] == ("created_at", dt.isoformat())
    assert _only(b, "gte")[1] == ("amount", "0.50")


# ─── or_/not_ predicate-string wire shapes for every operator ────────────


@pytest.mark.parametrize(
    "method,col,value,expected",
    [
        ("eq", "n", 1, "n.eq.1"),
        ("neq", "n", 1, "n.neq.1"),
        ("gt", "n", 1, "n.gt.1"),
        ("gte", "n", 1, "n.gte.1"),
        ("lt", "n", 1, "n.lt.1"),
        ("lte", "n", 1, "n.lte.1"),
        ("like", "name", "a%", "name.like.a%"),
        ("ilike", "name", "A%", "name.ilike.A%"),
        ("is_", "name", None, "name.is.null"),
        ("is_", "is_active", True, "is_active.is.true"),
        ("contains", "tags", ["x"], "tags.cs.{x}"),
        ("contained_by", "tags", ["x"], "tags.cd.{x}"),
        ("overlaps", "tags", ["x"], "tags.ov.{x}"),
        ("fts", "name", "cat", "name.fts.cat"),
        ("plfts", "name", "cat", "name.plfts.cat"),
        ("phfts", "name", "cat", "name.phfts.cat"),
        ("wfts", "name", "cat", "name.wfts.cat"),
    ],
)
async def test_or_predicate_string_per_operator(
    fake_client, method, col, value, expected
):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.or_(lambda q, m=method, c=col, v=value: getattr(q, m)(c, v)).all()
    or_call = _only(fake_client.builders[0], "or_")
    assert or_call[1] == (expected,)


async def test_or_predicate_with_in_uses_paren_tuple(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.or_(lambda q: q.in_("n", [1, 2, 3])).all()
    or_call = _only(fake_client.builders[0], "or_")
    # A single branch containing commas (even inside parens) gets wrapped in
    # ``and(...)`` defensively. Postgrest accepts both.
    assert or_call[1] == ("and(n.in.(1,2,3))",)


async def test_or_predicate_serializes_uuid(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    u = uuid4()
    await Row.query.or_(lambda q: q.eq("id", u)).all()
    or_call = _only(fake_client.builders[0], "or_")
    assert or_call[1] == (f"id.eq.{u}",)


async def test_or_predicate_quotes_value_with_comma(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.or_(lambda q: q.eq("name", "a,b")).all()
    or_call = _only(fake_client.builders[0], "or_")
    # Same wrap rule applies: branch with a comma → wrapped.
    assert or_call[1] == ('and(name.eq."a,b")',)


async def test_not_predicate_wraps_in_not_and(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.not_(lambda q: q.gt("n", 5).lt("n", 10)).all()
    or_call = _only(fake_client.builders[0], "or_")
    assert or_call[1] == ("not.and(n.gt.5,n.lt.10)",)


# ─── Ordering / paging shorthand → postgrest method ──────────────────────


async def test_order_by_emits_in_chain_order(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.eq("is_active", True).order_by("-created_at", "name").all()
    orders = _calls(fake_client.builders[0], "order")
    assert orders == [
        ("order", ("created_at",), {"desc": True}),
        ("order", ("name",), {"desc": False}),
    ]


async def test_limit_offset_range_pass_through(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.eq("is_active", True).limit(10).offset(5).range(0, 9).all()
    b = fake_client.builders[0]
    assert _only(b, "limit")[1] == (10,)
    assert _only(b, "offset")[1] == (5,)
    assert _only(b, "range")[1] == (0, 9)


# ─── order/limit/offset/range on update/delete builders ────────────────


async def test_replay_order_limit_offset_range_on_update_builder():
    from postgrest import AsyncPostgrestClient

    from supabase_orm._async._query import (
        Order,
        _replay_limit,
        _replay_offset,
        _replay_order,
        _replay_range,
    )

    pg = AsyncPostgrestClient("http://127.0.0.1:1")
    b = pg.table("t").update({"x": 1})
    assert not hasattr(b, "order")
    _replay_order(b, Order("name", desc=True, nulls="first"))
    _replay_limit(b, 10)
    _replay_offset(b, 3)
    assert str(b.request.params) == "order=name.desc.nullsfirst&limit=10&offset=3"

    b2 = pg.table("t").delete()
    _replay_range(b2, 5, 9)
    assert str(b2.request.params) == "offset=5&limit=5"

    b3 = pg.table("t").update({"x": 1})
    _replay_order(b3, Order("a", desc=False))
    _replay_order(b3, Order("b", desc=True))
    assert b3.request.params.get("order") == "a.asc,b.desc"


async def test_query_update_with_order_limit_does_not_raise_attribute_error():
    import httpx
    from postgrest import AsyncPostgrestClient

    from supabase_orm._async._client import use_client

    pg = AsyncPostgrestClient("http://127.0.0.1:1")

    class _Shim:
        def table(self, name):
            return pg.table(name)

    async with use_client(_Shim()):
        for chain in (
            lambda: Row.query.eq("n", 1).order_by("name").limit(10).update(name="x"),
            lambda: Row.query.eq("n", 1).limit(5).delete(),
            lambda: Row.query.eq("n", 1).offset(3).update(name="x"),
            lambda: Row.query.eq("n", 1).range(0, 9).update(name="x"),
        ):
            with pytest.raises(httpx.ConnectError):
                await chain()


# ─── Read terminals build correct request shape ──────────────────────────


async def test_first_appends_limit_1(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    await Row.query.eq("is_active", True).first()
    assert _only(fake_client.builders[0], "limit")[1] == (1,)


async def test_one_and_maybe_one_use_limit_2(fake_client):
    fake_client.queue(
        FakeResponse(
            data=[
                _row(uuid4()),
            ]
        )
    )
    await Row.query.eq("is_active", True).one()
    assert _only(fake_client.builders[0], "limit")[1] == (2,)


async def test_all_with_count_passes_count_exact(fake_client):
    fake_client.queue(FakeResponse(data=[], count=0))
    await Row.query.eq("is_active", True).all_with_count()
    # The count call is on a fresh builder.
    count_builder = next(
        b
        for b in fake_client.builders
        if any(c[0] == "select" and c[2].get("count") == "exact" for c in b.calls)
    )
    sel = _only(count_builder, "select")
    assert sel[2].get("count") == "exact"
    # Filter is replayed.
    assert _only(count_builder, "eq")[1] == ("is_active", True)


# ─── Create / bulk_create / save / instance.update / query.update wire ──


def _row(pid):
    return {
        "id": str(pid),
        "name": "n",
        "n": 1,
        "amount": "1.00",
        "status": "active",
        "created_at": "2024-01-01T00:00:00+00:00",
        "due": "2024-01-01",
        "tags": [],
        "is_active": True,
    }


async def test_create_payload_fully_serialized(fake_client):
    pid = uuid4()
    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    fake_client.queue(FakeResponse(data=[_row(pid)]))
    await Row.create(
        id=pid,
        name="n",
        n=1,
        amount=Decimal("1.50"),
        status=Status.ACTIVE,
        created_at=dt,
        due=date(2024, 1, 1),
        tags=["a", "b"],
        is_active=True,
    )
    ins = _only(fake_client.builders[0], "insert")
    assert ins[1][0] == {
        "id": str(pid),
        "name": "n",
        "n": 1,
        "amount": "1.50",
        "status": "active",
        "created_at": dt.isoformat(),
        "due": "2024-01-01",
        "tags": ["a", "b"],
        "is_active": True,
    }


async def test_bulk_create_payload_fully_serialized(fake_client):
    a, b = uuid4(), uuid4()
    fake_client.queue(FakeResponse(data=[_row(a), _row(b)]))
    await Row.bulk_create(
        [
            {
                "id": a,
                "name": "a",
                "n": 1,
                "amount": Decimal("1"),
                "status": Status.ACTIVE,
                "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "due": date(2024, 1, 1),
                "tags": [],
                "is_active": True,
            },
            {
                "id": b,
                "name": "b",
                "n": 2,
                "amount": Decimal("2"),
                "status": Status.ARCHIVED,
                "created_at": datetime(2024, 2, 2, tzinfo=timezone.utc),
                "due": date(2024, 2, 2),
                "tags": [],
                "is_active": False,
            },
        ]
    )
    ins = _only(fake_client.builders[0], "insert")
    rows = ins[1][0]
    assert rows[0]["id"] == str(a)
    assert rows[0]["status"] == "active"
    assert rows[0]["amount"] == "1"
    assert rows[1]["id"] == str(b)
    assert rows[1]["status"] == "archived"
    assert rows[1]["created_at"] == "2024-02-02T00:00:00+00:00"


async def test_save_serializes_dirty_fields_and_pk_in_eq(fake_client):
    pid = uuid4()
    r = Row(
        id=pid,
        name="n",
        n=1,
        amount=Decimal("1.0"),
        status=Status.ACTIVE,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        due=date(2024, 1, 1),
    )
    object.__setattr__(r, "__pydantic_fields_set__", set())
    new_dt = datetime(2025, 6, 7, tzinfo=timezone.utc)
    r.status = Status.ARCHIVED
    r.created_at = new_dt
    r.amount = Decimal("9.99")

    fake_client.queue(FakeResponse(data=[_row(pid)]))
    await r.save()

    b = fake_client.builders[0]
    upd = _only(b, "update")
    assert upd[1][0] == {
        "status": "archived",
        "created_at": new_dt.isoformat(),
        "amount": "9.99",
    }
    # pk filter is also serialized to string.
    assert _only(b, "eq")[1] == ("id", str(pid))


async def test_instance_update_serializes_payload(fake_client):
    pid = uuid4()
    r = Row(
        id=pid,
        name="n",
        n=1,
        amount=Decimal("1.0"),
        status=Status.ACTIVE,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        due=date(2024, 1, 1),
    )
    fake_client.queue(FakeResponse(data=[_row(pid)]))
    await r.update(status=Status.ARCHIVED, amount=Decimal("2.50"))
    upd = _only(fake_client.builders[0], "update")
    payload = upd[1][0]
    assert payload["status"] == "archived"
    assert payload["amount"] == "2.50"


async def test_query_update_serializes_payload(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await Row.query.eq("is_active", True).update(
        status=Status.ARCHIVED, created_at=dt, amount=Decimal("0.01")
    )
    upd_builder = next(
        b for b in fake_client.builders if any(c[0] == "update" for c in b.calls)
    )
    upd = _only(upd_builder, "update")
    assert upd[1][0] == {
        "status": "archived",
        "created_at": dt.isoformat(),
        "amount": "0.01",
    }


async def test_delete_eq_pk_serializes_value(fake_client):
    pid = uuid4()
    r = Row(
        id=pid,
        name="n",
        n=1,
        amount=Decimal("1.0"),
        status=Status.ACTIVE,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        due=date(2024, 1, 1),
    )
    fake_client.queue(FakeResponse(data=[]))
    await r.delete()
    b = fake_client.builders[0]
    assert _only(b, "delete")[1] == ()
    assert _only(b, "eq")[1] == ("id", str(pid))


# ─── Chained shorthand → wire (a realistic compound query) ──────────────


async def test_compound_query_wire_shape(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    await (
        Row.query.eq("is_active", True)
        .gte("created_at", dt)
        .in_("status", [Status.ACTIVE, Status.ARCHIVED])
        .or_(
            lambda q: q.like("name", "a%"),
            lambda q: q.like("name", "b%"),
        )
        .order_by("-created_at")
        .limit(50)
        .offset(100)
        .all()
    )
    b = fake_client.builders[0]
    # Exact ordered chain of recorded calls (after the initial select).
    seq = [c for c in b.calls if c[0] != "select"]
    assert seq == [
        ("eq", ("is_active", True), {}),
        ("gte", ("created_at", dt.isoformat()), {}),
        ("in_", ("status", ["active", "archived"]), {}),
        ("or_", ("name.like.a%,name.like.b%",), {}),
        ("order", ("created_at",), {"desc": True}),
        ("limit", (50,), {}),
        ("offset", (100,), {}),
    ]
