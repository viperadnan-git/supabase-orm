"""Resource embedding round-trips."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from supabase_orm import Relation, SupabaseModel

from .conftest import Owner, Pet, PetWithOwnerInner, PetWithOwnerLeft


class OwnerWithPets(SupabaseModel, table="orm_test_owners"):
    id: UUID
    email: str
    pets: Annotated[list[Pet], Relation(join="inner")] = []


class PetSlim(SupabaseModel, table="orm_test_pets"):
    id: UUID
    name: str


class PetSlimWithOwner(PetSlim):
    owner: Annotated[Owner | None, Relation()] = None


class PetSlimAdopted(PetSlim):
    adopted: bool


class PetSlimFull(PetSlimWithOwner, PetSlimAdopted):
    pass


async def test_left_join_includes_orphans(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    with_owner = await Pet.create(
        owner_id=owner.id,
        name="hasowner",
        species="cat",
        adopted=False,
        tags=[],
        amount=0,
    )
    orphan = await Pet.create(
        owner_id=None,
        name="orphan",
        species="cat",
        adopted=False,
        tags=[],
        amount=0,
    )
    rows = await PetWithOwnerLeft.query.in_("id", [with_owner.id, orphan.id]).all()
    by_id = {r.id: r for r in rows}
    assert by_id[with_owner.id].owner is not None
    assert by_id[with_owner.id].owner.email == owner.email
    assert by_id[orphan.id].owner is None


async def test_inner_join_drops_orphans(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    with_owner = await Pet.create(
        owner_id=owner.id,
        name="hasowner",
        species="cat",
        adopted=False,
        tags=[],
        amount=0,
    )
    orphan = await Pet.create(
        owner_id=None,
        name="orphan",
        species="cat",
        adopted=False,
        tags=[],
        amount=0,
    )
    rows = await PetWithOwnerInner.query.in_("id", [with_owner.id, orphan.id]).all()
    assert {r.id for r in rows} == {with_owner.id}


async def test_projection_chain_select_strings():
    assert PetSlim.__select__ == "id,name"
    assert (
        PetSlimWithOwner.__select__
        == "id,name,owner:orm_test_owners(id,email,is_active)"
    )
    assert PetSlimAdopted.__select__ == "id,name,adopted"
    # MRO merges owner + adopted into the diamond child.
    assert (
        PetSlimFull.__select__
        == "id,name,adopted,owner:orm_test_owners(id,email,is_active)"
    )


async def test_projection_chain_live_round_trip(clean):
    owner = await Owner.create(email=f"chain-{uuid4()}@x.test")
    src = await Pet.create(
        owner_id=owner.id,
        name="chainpet",
        species="cat",
        adopted=True,
        tags=[],
        amount=0,
    )

    bare = await Pet.query.eq("id", src.id).as_(PetSlim).one()
    assert isinstance(bare, PetSlim)
    assert bare.name == "chainpet"
    assert not hasattr(bare, "owner")

    with_owner = await Pet.query.eq("id", src.id).as_(PetSlimWithOwner).one()
    assert isinstance(with_owner, PetSlimWithOwner)
    assert with_owner.owner is not None
    assert with_owner.owner.email == owner.email

    adopted = await Pet.query.eq("id", src.id).as_(PetSlimAdopted).one()
    assert isinstance(adopted, PetSlimAdopted)
    assert adopted.adopted is True

    full = await Pet.query.eq("id", src.id).as_(PetSlimFull).one()
    assert isinstance(full, PetSlimFull)
    assert full.adopted is True
    assert full.owner is not None
    assert full.owner.email == owner.email


async def test_create_with_relations_refetches_with_embed(clean):
    """create() on a relation model does a follow-up GET — confirm it works."""
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    p = await PetWithOwnerInner.create(
        owner_id=owner.id,
        name="ref",
        species="cat",
        adopted=False,
        tags=[],
        amount=0,
    )
    assert p.owner.id == owner.id
    assert p.owner.email == owner.email


async def _seed_two_owners(clean) -> tuple[Owner, Owner]:
    """Owner A with 2 pets, owner B with 1 pet."""
    oa = await Owner.create(email=f"a-{uuid4()}@x.test")
    ob = await Owner.create(email=f"b-{uuid4()}@x.test")
    for i in range(2):
        await Pet.create(
            owner_id=oa.id,
            name=f"pa{i}",
            species="cat",
            adopted=False,
            tags=[],
            amount=0,
        )
    await Pet.create(
        owner_id=ob.id, name="pb0", species="dog", adopted=False, tags=[], amount=0
    )
    return oa, ob


async def test_count_honors_embedded_column_filter(clean):
    oa, _ = await _seed_two_owners(clean)
    q = PetWithOwnerInner.query.eq("owner.email", oa.email)
    assert len(await q.all()) == 2
    # count() must agree with all() on the same chain (embed kept).
    assert await PetWithOwnerInner.query.eq("owner.email", oa.email).count() == 2
    assert await PetWithOwnerInner.query.eq("owner.email", "nobody@x.test").count() == 0


async def test_exists_honors_embedded_column_filter(clean):
    oa, _ = await _seed_two_owners(clean)
    assert await PetWithOwnerInner.query.eq("owner.email", oa.email).exists() is True
    assert (
        await PetWithOwnerInner.query.eq("owner.email", "nobody@x.test").exists()
        is False
    )


async def test_order_by_to_one_embedded_column(clean):
    oa, ob = await _seed_two_owners(clean)
    asc = [
        p.owner.email
        for p in await PetWithOwnerInner.query.order_by("owner.email").all()
    ]
    assert asc == sorted(asc)
    desc = [
        p.owner.email
        for p in await PetWithOwnerInner.query.order_by("-owner.email").all()
    ]
    assert desc == sorted(desc, reverse=True)


async def test_count_to_many_inner_embed_counts_parents(clean):
    """count() over a to-many !inner embed returns parent rows, not joined rows."""
    oa = await Owner.create(email=f"a-{uuid4()}@x.test")
    ob = await Owner.create(email=f"b-{uuid4()}@x.test")
    await Owner.create(email=f"c-{uuid4()}@x.test")  # no pets → dropped by !inner
    for _ in range(3):
        await Pet.create(
            owner_id=oa.id, name="x", species="cat", adopted=False, tags=[], amount=0
        )
    await Pet.create(
        owner_id=ob.id, name="y", species="dog", adopted=False, tags=[], amount=0
    )
    assert len(await OwnerWithPets.query.all()) == 2
    assert await OwnerWithPets.query.count() == 2
    assert await OwnerWithPets.query.exists() is True
