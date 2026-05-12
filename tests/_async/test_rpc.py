"""RPC helpers."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from supabase_orm._async import rpc, rpc_maybe_one, rpc_one, rpc_scalar

from .conftest import FakeResponse


class Stat(BaseModel):
    id: UUID
    n: int


async def test_rpc_validates_list(fake_client):
    a, b = uuid4(), uuid4()
    fake_client.queue(
        FakeResponse(data=[{"id": str(a), "n": 1}, {"id": str(b), "n": 2}])
    )
    out = await rpc("get_stats", Stat, p_uid=a)
    assert [r.n for r in out] == [1, 2]
    # Params serialized to wire types.
    call = fake_client.rpc_calls[0]
    assert call.name == "get_stats"
    assert call.params == {"p_uid": str(a)}


async def test_rpc_wraps_scalar_response_in_list(fake_client):
    uid = uuid4()
    fake_client.queue(FakeResponse(data={"id": str(uid), "n": 7}))
    out = await rpc("get_stat", Stat)
    assert len(out) == 1 and out[0].n == 7


async def test_rpc_one_raises_when_empty(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    with pytest.raises(ValueError, match="returned no rows"):
        await rpc_one("get_stat", Stat)


async def test_rpc_one_returns_first(fake_client):
    uid = uuid4()
    fake_client.queue(FakeResponse(data=[{"id": str(uid), "n": 3}]))
    out = await rpc_one("get_stat", Stat)
    assert out.n == 3


async def test_rpc_maybe_one_returns_none_or_first(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    assert await rpc_maybe_one("get_stat", Stat) is None

    uid = uuid4()
    fake_client.queue(FakeResponse(data=[{"id": str(uid), "n": 4}]))
    out = await rpc_maybe_one("get_stat", Stat)
    assert out is not None and out.n == 4


async def test_rpc_scalar_validates_type(fake_client):
    fake_client.queue(FakeResponse(data=42))
    assert await rpc_scalar("count_active_users", int) == 42


async def test_rpc_scalar_coerces_str_to_int(fake_client):
    fake_client.queue(FakeResponse(data="42"))
    assert await rpc_scalar("count_active_users", int) == 42
