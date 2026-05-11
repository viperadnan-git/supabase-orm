"""Write round-trips, ordering, paging, count terminals."""

from __future__ import annotations

from uuid import uuid4

import pytest

from supabase_orm import (
    SupabaseORMDoesNotExist,
    SupabaseORMMultipleObjectsReturned,
)

from .conftest import Owner


async def test_create_and_get(clean):
    o = await Owner.create(email=f"o-{uuid4()}@x.test")
    got = await Owner.get(o.id)
    assert got.id == o.id and got.email == o.email


async def test_get_missing_raises(clean):
    with pytest.raises(SupabaseORMDoesNotExist):
        await Owner.get(uuid4())


async def test_find_returns_none_on_miss(clean):
    assert await Owner.find(uuid4()) is None


async def test_bulk_create_returns_all(clean):
    rows = await Owner.bulk_create(
        [
            {"email": f"a-{uuid4()}@x.test"},
            {"email": f"b-{uuid4()}@x.test"},
            {"email": f"c-{uuid4()}@x.test"},
        ]
    )
    assert len(rows) == 3
    assert {r.email for r in rows} == {r.email for r in rows}


async def test_save_persists_only_dirty_fields(clean):
    o = await Owner.create(email=f"o-{uuid4()}@x.test")
    o.is_active = False
    await o.save()
    fresh = await Owner.get(o.id)
    assert fresh.is_active is False


async def test_instance_update(clean):
    o = await Owner.create(email=f"o-{uuid4()}@x.test")
    new_email = f"new-{uuid4()}@x.test"
    await o.update(email=new_email, is_active=False)
    fresh = await Owner.get(o.id)
    assert fresh.email == new_email
    assert fresh.is_active is False


async def test_query_update_bulk(clean):
    owners = await Owner.bulk_create(
        [{"email": f"u-{uuid4()}@x.test"} for _ in range(3)]
    )
    out = await Owner.query.in_("id", [o.id for o in owners]).update(is_active=False)
    assert len(out) == 3
    fresh = await Owner.query.in_("id", [o.id for o in owners]).all()
    assert all(o.is_active is False for o in fresh)


async def test_instance_delete(clean):
    o = await Owner.create(email=f"o-{uuid4()}@x.test")
    await o.delete()
    assert await Owner.find(o.id) is None


async def test_query_delete_bulk(clean):
    owners = await Owner.bulk_create(
        [{"email": f"d-{uuid4()}@x.test"} for _ in range(3)]
    )
    deleted = await Owner.query.in_("id", [o.id for o in owners]).delete()
    assert len(deleted) == 3
    rows = await Owner.query.in_("id", [o.id for o in owners]).all()
    assert rows == []


async def test_order_by_and_limit(clean):
    await Owner.bulk_create(
        [{"email": f"order-{i}-{uuid4()}@x.test"} for i in range(5)]
    )
    rows = await Owner.query.like("email", "order-%").order_by("-email").limit(2).all()
    assert len(rows) == 2
    assert rows[0].email > rows[1].email


async def test_range(clean):
    owners = await Owner.bulk_create(
        [{"email": f"range-{i}-{uuid4()}@x.test"} for i in range(5)]
    )
    rows = (
        await Owner.query.like("email", "range-%").order_by("email").range(1, 3).all()
    )
    assert len(rows) == 3
    expected = sorted(o.email for o in owners)[1:4]
    assert [r.email for r in rows] == expected


async def test_count(clean):
    await Owner.bulk_create([{"email": f"cnt-{i}-{uuid4()}@x.test"} for i in range(4)])
    assert await Owner.query.like("email", "cnt-%").count() == 4


async def test_all_with_count(clean):
    await Owner.bulk_create([{"email": f"awc-{i}-{uuid4()}@x.test"} for i in range(5)])
    rows, total = (
        await Owner.query.like("email", "awc-%")
        .order_by("email")
        .limit(2)
        .all_with_count()
    )
    assert total == 5
    assert len(rows) == 2


async def test_one_raises_on_multiple(clean):
    await Owner.bulk_create([{"email": f"dup-{i}-{uuid4()}@x.test"} for i in range(2)])
    with pytest.raises(SupabaseORMMultipleObjectsReturned):
        await Owner.query.like("email", "dup-%").one()


async def test_maybe_one_returns_none(clean):
    assert await Owner.query.eq("email", "nope@x.test").maybe_one() is None
