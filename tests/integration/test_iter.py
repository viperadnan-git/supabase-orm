"""QueryBuilder.iter() — keyset pagination round-trips against real PostgREST."""

from __future__ import annotations

from uuid import uuid4

import pytest

from supabase_orm import SupabaseORMUsageError

from .conftest import Owner, Pet


async def test_iter_yields_every_row_exactly_once(clean):
    """Seed N rows, iter with a small batch_size, assert each row appears
    exactly once and pk-ordered."""
    n = 25
    seeded = await Owner.bulk_create(
        [{"email": f"i-{i}-{uuid4()}@x.test"} for i in range(n)]
    )
    seeded_ids = {o.id for o in seeded}

    out: list = []
    async for o in Owner.query.iter(batch_size=7):
        out.append(o)

    out_ids = [o.id for o in out]
    assert len(out_ids) == n
    assert set(out_ids) == seeded_ids  # exactly once each
    assert out_ids == sorted(out_ids, key=str)  # pk-ascending order


async def test_iter_with_filter_only_matches(clean):
    await Owner.bulk_create([{"email": f"a-{uuid4()}@x.test"} for _ in range(5)])
    await Owner.bulk_create([{"email": f"b-{uuid4()}@x.test"} for _ in range(5)])

    matched = [o async for o in Owner.query.like("email", "a-%").iter(batch_size=2)]
    assert len(matched) == 5
    assert all(o.email.startswith("a-") for o in matched)


async def test_iter_yields_nothing_for_no_match(clean):
    await Owner.bulk_create([{"email": f"x-{uuid4()}@x.test"} for _ in range(3)])
    out = [o async for o in Owner.query.eq("email", "nope@x.test").iter()]
    assert out == []


async def test_iter_handles_exact_multiple_of_batch_size(clean):
    """When the result-set size is exactly k * batch_size, iter must
    correctly stop on the empty boundary batch (no infinite loop)."""
    n = 6
    await Owner.bulk_create([{"email": f"em-{i}-{uuid4()}@x.test"} for i in range(n)])
    out = [o async for o in Owner.query.like("email", "em-%").iter(batch_size=3)]
    assert len(out) == n


async def test_iter_consistent_with_all(clean):
    """For a stable result-set, iter() and .all() must return the same rows."""
    pets = []
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    for i in range(15):
        pets.append(
            await Pet.create(
                owner_id=owner.id,
                name=f"p-{i}",
                species="cat",
                adopted=False,
                tags=[],
                amount=0,
            )
        )

    via_iter = [p.id async for p in Pet.query.eq("species", "cat").iter(batch_size=4)]
    via_all = [p.id for p in await Pet.query.eq("species", "cat").all()]
    assert sorted(via_iter, key=str) == sorted(via_all, key=str)


async def test_iter_break_stops_cleanly(clean):
    await Owner.bulk_create([{"email": f"br-{uuid4()}@x.test"} for _ in range(20)])
    seen = 0
    async for _ in Owner.query.like("email", "br-%").iter(batch_size=5):
        seen += 1
        if seen >= 3:
            break
    assert seen == 3


async def test_iter_state_clean_after_break(clean):
    await Owner.bulk_create([{"email": f"st-{uuid4()}@x.test"} for _ in range(10)])

    partial = 0
    async for _ in Owner.query.like("email", "st-%").iter(batch_size=4):
        partial += 1
        if partial >= 2:
            break

    full = [o async for o in Owner.query.like("email", "st-%").iter(batch_size=4)]
    assert len(full) == 10
    assert await Owner.query.like("email", "st-%").count() == 10


async def test_iter_explicit_aclose_against_live_client(clean):
    await Owner.bulk_create([{"email": f"ac-{uuid4()}@x.test"} for _ in range(6)])
    gen = Owner.query.like("email", "ac-%").iter(batch_size=2)
    first = await anext(gen)
    assert first.email.startswith("ac-")
    await gen.aclose()
    await gen.aclose()


async def test_iter_rejects_chained_pagination_at_call_time(clean):
    with pytest.raises(SupabaseORMUsageError, match="iter\\(\\) owns ordering"):
        Owner.query.order_by("email").iter()
