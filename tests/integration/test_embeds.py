"""Resource embedding round-trips."""

from __future__ import annotations

from uuid import uuid4

from .conftest import Owner, Pet, PetWithOwnerInner, PetWithOwnerLeft


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
