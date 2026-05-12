"""Client lifecycle: ContextVar isolation, use_client."""

from __future__ import annotations

import asyncio

import pytest

from supabase_orm import (
    SupabaseORMUsageError,
    get_client,
    set_client,
    use_client,
)
from supabase_orm._client import _client


def test_get_client_without_init_raises():
    set_client(None)
    with pytest.raises(SupabaseORMUsageError, match="not initialized"):
        get_client()


def test_set_and_get_roundtrip():
    sentinel = object()
    try:
        set_client(sentinel)  # type: ignore[arg-type]
        assert get_client() is sentinel
    finally:
        set_client(None)


def test_set_none_clears():
    set_client(object())  # type: ignore[arg-type]
    set_client(None)
    with pytest.raises(SupabaseORMUsageError):
        get_client()


# ─── use_client ──────────────────────────────────────────────────────────


async def test_use_client_scopes_to_block():
    outer = object()
    inner = object()
    set_client(outer)  # type: ignore[arg-type]
    try:
        assert get_client() is outer
        async with use_client(inner):  # type: ignore[arg-type]
            assert get_client() is inner
        assert get_client() is outer
    finally:
        set_client(None)


async def test_use_client_isolates_concurrent_tasks():
    """Each task gets its own ContextVar copy — JWTs cannot leak across
    concurrent requests."""
    set_client(object())  # type: ignore[arg-type]

    async def task(label: str) -> str:
        marker = f"client-{label}"
        async with use_client(marker):  # type: ignore[arg-type]
            # Yield control so the other task gets to run between set & read.
            await asyncio.sleep(0)
            return get_client()  # type: ignore[return-value]

    try:
        results = await asyncio.gather(task("a"), task("b"), task("c"))
        assert results == ["client-a", "client-b", "client-c"]
    finally:
        set_client(None)


async def test_use_client_restores_even_on_exception():
    outer = object()
    set_client(outer)  # type: ignore[arg-type]
    try:
        with pytest.raises(RuntimeError):
            async with use_client(object()):  # type: ignore[arg-type]
                raise RuntimeError("boom")
        assert get_client() is outer
    finally:
        set_client(None)


# ─── ContextVar semantics ────────────────────────────────────────────────


def test_client_is_a_contextvar():
    """Sanity check: the storage backend is a ContextVar (not a module
    global). Documents the design assumption that per-request isolation
    relies on."""
    from contextvars import ContextVar

    assert isinstance(_client, ContextVar)


# ─── QueryBuilder resolves client at terminal time, not chain start ──────


async def test_querybuilder_resolves_client_at_terminal_not_at_chain_start():
    """Build a chain under client A, swap to client B before calling the
    terminal — the request must hit B, not the captured A. Proves the
    per-request RLS / use_client() story works even when chains span
    context boundaries."""
    from supabase_orm import SupabaseModel
    from tests.conftest import FakeClient, FakeResponse

    class Pet(SupabaseModel, table="pets_ctx"):
        id: int
        name: str

    client_a = FakeClient()
    client_b = FakeClient()
    client_b.queue(FakeResponse(data=[{"id": 1, "name": "B-pet"}]))

    set_client(client_a)  # type: ignore[arg-type]
    try:
        # Build chain under client A.
        qb = Pet.query.eq("name", "x")
        # Swap client mid-flight (the FastAPI middleware pattern).
        async with use_client(client_b):  # type: ignore[arg-type]
            rows = await qb.all()
        # Request hit B (we queued B's response and got it back); A was
        # never touched.
        assert client_a.builders == []
        assert len(client_b.builders) == 1
        assert rows[0].name == "B-pet"
    finally:
        set_client(None)
