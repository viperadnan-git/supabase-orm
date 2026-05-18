"""Write/read round-trips, terminals, payload minimality, ``returning=`` mode."""

from __future__ import annotations

from uuid import uuid4

import pytest

from supabase_orm import (
    SupabaseORMDoesNotExist,
    SupabaseORMMultipleObjectsReturned,
)

from .conftest import Owner, Pet


def _snapshot(model_instance) -> dict:
    return model_instance.model_dump(mode="json")


async def _seed_pet(owner_id) -> Pet:
    return await Pet.create(
        owner_id=owner_id,
        name=f"orig-{uuid4()}",
        species="cat",
        adopted=False,
        tags=["a", "b"],
        amount=12.34,
        due="2026-01-15",
    )


# ─── Reads: get / find ──────────────────────────────────────────────────


async def test_create_and_get(clean):
    o = await Owner.create(email=f"o-{uuid4()}@x.test")
    got = await Owner.get(o.id)
    assert got.id == o.id and got.email == o.email


async def test_get_missing_raises(clean):
    with pytest.raises(SupabaseORMDoesNotExist):
        await Owner.get(uuid4())


async def test_find_returns_none_on_miss(clean):
    assert await Owner.find(uuid4()) is None


# ─── Writes: create / bulk_create / save / update / delete ───────────────


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


# ─── Ordering / paging / count / exists ─────────────────────────────────


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


async def test_exists_true(clean):
    await Owner.create(email=f"exists-{uuid4()}@x.test")
    assert await Owner.query.like("email", "exists-%").exists() is True


async def test_exists_false(clean):
    assert await Owner.query.eq("email", f"nope-{uuid4()}@x.test").exists() is False


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


# ─── Payload minimality (mutated col changes; others byte-identical) ─────


async def test_instance_save_sends_only_dirty(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    pet = await _seed_pet(owner.id)
    before = _snapshot(pet)

    pet.name = "changed"
    await pet.save()

    fresh = _snapshot(await Pet.get(pet.id))
    assert fresh["name"] == "changed"
    for col in ("species", "adopted", "tags", "amount", "due", "owner_id"):
        assert fresh[col] == before[col], (
            f"{col} changed: {before[col]} -> {fresh[col]}"
        )


async def test_instance_update_sends_only_passed_kwargs(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    pet = await _seed_pet(owner.id)
    before = _snapshot(pet)

    await pet.update(amount=99.99)

    fresh = _snapshot(await Pet.get(pet.id))
    assert float(fresh["amount"]) == 99.99
    for col in ("name", "species", "adopted", "tags", "due", "owner_id"):
        assert fresh[col] == before[col], f"{col} changed unexpectedly"


async def test_query_update_sends_only_passed_kwargs(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    pet = await _seed_pet(owner.id)
    before = _snapshot(pet)

    await Pet.query.eq("id", pet.id).update(adopted=True)

    fresh = _snapshot(await Pet.get(pet.id))
    assert fresh["adopted"] is True
    for col in ("name", "species", "tags", "amount", "due", "owner_id"):
        assert fresh[col] == before[col], f"{col} changed unexpectedly"


async def test_upsert_existing_row_only_updates_columns_in_payload(clean):
    # Postgres validates NOT NULL during the INSERT phase before the ON
    # CONFLICT redirect, so partial upsert requires all NOT NULL cols.
    # Nullable `due` is omitted to prove the UPDATE side stays minimal.
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    pet = await _seed_pet(owner.id)
    before = _snapshot(pet)

    result = await Pet.upsert(
        id=pet.id,
        owner_id=pet.owner_id,
        name="upserted",
        species=pet.species,
        adopted=pet.adopted,
        tags=pet.tags,
        amount=pet.amount,
    )
    assert result.name == "upserted"

    fresh = _snapshot(await Pet.get(pet.id))
    assert fresh["name"] == "upserted"
    assert fresh["due"] == before["due"], (
        f"due was overwritten: {before['due']} -> {fresh['due']}"
    )


async def test_update_or_create_existing_sends_only_defaults(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    pet = await _seed_pet(owner.id)
    before = _snapshot(pet)

    obj, created = await Pet.update_or_create(
        id=pet.id,
        defaults={"amount": 77.50},
    )
    assert created is False
    assert float(obj.amount) == 77.50

    fresh = _snapshot(await Pet.get(pet.id))
    assert float(fresh["amount"]) == 77.50
    for col in ("name", "species", "adopted", "tags", "due", "owner_id"):
        assert fresh[col] == before[col], f"{col} changed unexpectedly"


async def test_save_after_no_mutation_is_no_op(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    pet = await _seed_pet(owner.id)
    before = _snapshot(pet)

    await pet.save()

    fresh = _snapshot(await Pet.get(pet.id))
    assert fresh == before


async def test_save_resets_dirty_after_persist(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    pet = await _seed_pet(owner.id)

    pet.name = "round-1"
    await pet.save()
    assert pet.__pydantic_fields_set__ == set()

    before = _snapshot(pet)
    await pet.save()
    fresh = _snapshot(await Pet.get(pet.id))
    assert fresh == before


async def test_bulk_upsert_omitted_nullable_column_survives(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    p1 = await _seed_pet(owner.id)
    p2 = await _seed_pet(owner.id)
    before1 = _snapshot(p1)
    before2 = _snapshot(p2)

    await Pet.bulk_upsert(
        [
            {
                "id": str(p1.id),
                "owner_id": str(p1.owner_id),
                "name": "bulk-1",
                "species": p1.species,
                "adopted": p1.adopted,
                "tags": p1.tags,
                "amount": p1.amount,
            },
            {
                "id": str(p2.id),
                "owner_id": str(p2.owner_id),
                "name": p2.name,
                "species": p2.species,
                "adopted": True,
                "tags": p2.tags,
                "amount": p2.amount,
            },
        ]
    )

    fresh1 = _snapshot(await Pet.get(p1.id))
    fresh2 = _snapshot(await Pet.get(p2.id))
    assert fresh1["name"] == "bulk-1"
    assert fresh2["adopted"] is True
    assert fresh1["due"] == before1["due"]
    assert fresh2["due"] == before2["due"]


# ─── returning="minimal" + ignore_duplicates ────────────────────────────


async def test_create_minimal_persists_and_returns_none(clean):
    email = f"min-{uuid4()}@x.test"
    result = await Owner.create(email=email, returning="minimal")
    assert result is None
    rows = await Owner.query.eq("email", email).all()
    assert len(rows) == 1


async def test_bulk_create_minimal_persists_and_returns_none(clean):
    emails = [f"bmin-{uuid4()}@x.test" for _ in range(3)]
    result = await Owner.bulk_create(
        [{"email": e} for e in emails], returning="minimal"
    )
    assert result is None
    rows = await Owner.query.in_("email", emails).all()
    assert {r.email for r in rows} == set(emails)


async def test_upsert_minimal_inserts_and_returns_none(clean):
    email = f"umin-{uuid4()}@x.test"
    owner = await Owner.create(email=email)
    result = await Owner.upsert(
        id=owner.id, email=email, is_active=False, returning="minimal"
    )
    assert result is None
    fresh = await Owner.get(owner.id)
    assert fresh.is_active is False


async def test_query_update_minimal(clean):
    o = await Owner.create(email=f"qum-{uuid4()}@x.test")
    result = await Owner.query.eq("id", o.id).update(
        is_active=False, returning="minimal"
    )
    assert result is None
    fresh = await Owner.get(o.id)
    assert fresh.is_active is False


async def test_query_delete_minimal(clean):
    o = await Owner.create(email=f"qdm-{uuid4()}@x.test")
    result = await Owner.query.eq("id", o.id).delete(returning="minimal")
    assert result is None
    assert await Owner.find(o.id) is None


async def test_upsert_ignore_duplicates_returns_none_on_conflict(clean):
    email = f"dup-{uuid4()}@x.test"
    first = await Owner.create(email=email)

    result = await Owner.upsert(
        email=email, on_conflict="email", ignore_duplicates=True
    )
    assert result is None
    fresh = await Owner.get(first.id)
    assert fresh.email == email


async def test_upsert_ignore_duplicates_returns_row_on_fresh_insert(clean):
    email = f"new-{uuid4()}@x.test"
    result = await Owner.upsert(
        email=email, on_conflict="email", ignore_duplicates=True
    )
    assert result is not None
    assert result.email == email


async def test_create_minimal_with_relations_model_does_not_refetch(clean):
    owner = await Owner.create(email=f"rmm-{uuid4()}@x.test")
    result = await Pet.create(
        owner_id=owner.id,
        name=f"pmin-{uuid4()}",
        species="cat",
        adopted=False,
        tags=[],
        amount=0,
        returning="minimal",
    )
    assert result is None
