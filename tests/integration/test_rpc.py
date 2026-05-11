"""RPC round-trips against real Postgres functions."""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel

from supabase_orm import rpc, rpc_one, rpc_scalar

from .conftest import Owner, Pet


class _PetCount(BaseModel):
    owner_id: UUID
    n: int


async def test_rpc_scalar(clean):
    await Owner.bulk_create([{"email": f"a-{uuid4()}@x.test"} for _ in range(3)])
    n = await rpc_scalar("orm_test_count_active_owners", int)
    assert n == 3


async def test_rpc_setof(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    for _ in range(2):
        await Pet.create(
            owner_id=owner.id,
            name="n",
            species="cat",
            adopted=False,
            tags=[],
            amount=0,
        )
    rows = await rpc("orm_test_owner_pet_count", _PetCount, p_owner=owner.id)
    assert len(rows) == 1 and rows[0].owner_id == owner.id and rows[0].n == 2


async def test_rpc_one(clean):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    await Pet.create(
        owner_id=owner.id,
        name="n",
        species="cat",
        adopted=False,
        tags=[],
        amount=0,
    )
    row = await rpc_one("orm_test_owner_pet_count", _PetCount, p_owner=owner.id)
    assert row.n == 1
