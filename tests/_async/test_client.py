"""Client lifecycle: ContextVar isolation, use_client."""

from __future__ import annotations

import pytest

from supabase_orm._async import (
    SupabaseORMUsageError,
    get_client,
    init,
    set_client,
    shutdown,
    use_client,
)
from supabase_orm._async._client import _client_override


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


# ─── init / shutdown ─────────────────────────────────────────────────────


class _FakeSubclient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeOwnedClient:
    """Minimal stand-in for ``AsyncClient`` exposing the subclients
    ``shutdown()`` walks: postgrest / auth / storage / functions."""

    def __init__(self) -> None:
        self.postgrest = _FakeSubclient()
        self.auth = _FakeSubclient()
        self.storage = _FakeSubclient()
        self.functions = _FakeSubclient()


async def test_init_binds_and_returns_client():
    client = _FakeOwnedClient()
    try:
        returned = init(client)  # type: ignore[arg-type]
        assert returned is client
        assert get_client() is client
    finally:
        await shutdown()


async def test_shutdown_closes_init_owned_client():
    client = _FakeOwnedClient()
    init(client)  # type: ignore[arg-type]
    await shutdown()
    for sub in (client.postgrest, client.auth, client.storage, client.functions):
        assert sub.closed is True
    with pytest.raises(SupabaseORMUsageError):
        get_client()


async def test_shutdown_does_not_close_set_client_owned():
    """set_client() doesn't transfer ownership — shutdown() unbinds but
    must NOT close the user's client."""
    client = _FakeOwnedClient()
    set_client(client)  # type: ignore[arg-type]
    try:
        await shutdown()
        for sub in (client.postgrest, client.auth, client.storage, client.functions):
            assert sub.closed is False
        with pytest.raises(SupabaseORMUsageError):
            get_client()
    finally:
        # Caller owns teardown; mirror what a real caller would do.
        pass


async def test_shutdown_idempotent_and_safe_with_no_client():
    await shutdown()  # no client ever bound — must not raise
    await shutdown()  # repeat — still no-op


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


def test_override_is_a_contextvar():
    """Sanity check: the per-request override backend is a ContextVar so
    use_client() doesn't leak across concurrent requests."""
    from contextvars import ContextVar

    assert isinstance(_client_override, ContextVar)


# ─── QueryBuilder resolves client at terminal time, not chain start ──────


async def test_querybuilder_resolves_client_at_terminal_not_at_chain_start():
    """Build a chain under client A, swap to client B before calling the
    terminal — the request must hit B, not the captured A. Proves the
    per-request RLS / use_client() story works even when chains span
    context boundaries."""
    from supabase_orm._async import SupabaseModel
    from tests._async.conftest import FakeClient, FakeResponse

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


# gen_sync: skip-block
# ─── Asyncio-specific concurrency regressions ────────────────────────────
#
# Sibling-task isolation under asyncio.gather / asyncio.create_task. No
# sync analog — sync use_client is thread-scoped, not task-scoped.
import asyncio


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


async def test_set_client_visible_across_independent_tasks():
    """Reproduces the bug a ContextVar-only design has under ASGI servers.

    Uvicorn runs ``lifespan`` in one task and each request handler in a
    separate, sibling task. ``ContextVar.set()`` only mutates the
    setter's own context; sibling tasks (request handlers) inherit
    uvicorn's root context, where the var is still its default.

    set_client() must therefore propagate to ALL tasks — not just
    descendants of the setter — by storing in a module global. This test
    spawns the setter as a finished sibling task, then a separate reader
    task; the reader must see what the setter wrote."""
    sentinel = object()

    async def setter() -> None:
        set_client(sentinel)  # type: ignore[arg-type]

    async def reader():
        return get_client()

    try:
        await asyncio.create_task(setter())  # completes before we read
        result = await asyncio.create_task(reader())
        assert result is sentinel
    finally:
        set_client(None)


async def test_use_client_override_still_isolated_per_task():
    """The default is a global, but per-request use_client() overrides
    must STILL be ContextVar-isolated — otherwise concurrent requests
    overwrite each other's RLS-scoped client."""
    default = object()
    set_client(default)  # type: ignore[arg-type]

    async def request(label: str) -> tuple[object, object]:
        per_request = f"client-{label}"
        async with use_client(per_request):  # type: ignore[arg-type]
            await asyncio.sleep(0)  # let other tasks run between set & read
            return get_client(), per_request  # type: ignore[return-value]

    try:
        results = await asyncio.gather(request("a"), request("b"), request("c"))
        # Each task saw its own override, not anyone else's.
        for got, expected in results:
            assert got == expected
        # After all overrides exit, default is back.
        assert get_client() is default
    finally:
        set_client(None)


# gen_sync: end-skip
