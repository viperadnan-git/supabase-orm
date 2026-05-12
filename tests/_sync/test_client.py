# DO NOT EDIT — generated from tests/_async/test_client.py by scripts/gen_sync.py.
# Run `python scripts/gen_sync.py` (or rebuild the package) to regenerate.

"""Client lifecycle: ContextVar isolation, use_client."""

from __future__ import annotations

import pytest

from supabase_orm._sync import (
    SupabaseORMUsageError,
    get_client,
    init,
    set_client,
    shutdown,
    use_client,
)
from supabase_orm._sync._client import _client_override


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

    def close(self) -> None:
        self.closed = True


class _FakeOwnedClient:
    """Minimal stand-in for ``Client`` exposing the subclients
    ``shutdown()`` walks: postgrest / auth / storage / functions."""

    def __init__(self) -> None:
        self.postgrest = _FakeSubclient()
        self.auth = _FakeSubclient()
        self.storage = _FakeSubclient()
        self.functions = _FakeSubclient()


def test_init_binds_and_returns_client():
    client = _FakeOwnedClient()
    try:
        returned = init(client)  # type: ignore[arg-type]
        assert returned is client
        assert get_client() is client
    finally:
        shutdown()


def test_shutdown_closes_init_owned_client():
    client = _FakeOwnedClient()
    init(client)  # type: ignore[arg-type]
    shutdown()
    for sub in (client.postgrest, client.auth, client.storage, client.functions):
        assert sub.closed is True
    with pytest.raises(SupabaseORMUsageError):
        get_client()


def test_shutdown_does_not_close_set_client_owned():
    """set_client() doesn't transfer ownership — shutdown() unbinds but
    must NOT close the user's client."""
    client = _FakeOwnedClient()
    set_client(client)  # type: ignore[arg-type]
    try:
        shutdown()
        for sub in (client.postgrest, client.auth, client.storage, client.functions):
            assert sub.closed is False
        with pytest.raises(SupabaseORMUsageError):
            get_client()
    finally:
        # Caller owns teardown; mirror what a real caller would do.
        pass


def test_shutdown_idempotent_and_safe_with_no_client():
    shutdown()  # no client ever bound — must not raise
    shutdown()  # repeat — still no-op


# ─── use_client ──────────────────────────────────────────────────────────


def test_use_client_scopes_to_block():
    outer = object()
    inner = object()
    set_client(outer)  # type: ignore[arg-type]
    try:
        assert get_client() is outer
        with use_client(inner):  # type: ignore[arg-type]
            assert get_client() is inner
        assert get_client() is outer
    finally:
        set_client(None)


def test_use_client_restores_even_on_exception():
    outer = object()
    set_client(outer)  # type: ignore[arg-type]
    try:
        with pytest.raises(RuntimeError):
            with use_client(object()):  # type: ignore[arg-type]
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


def test_querybuilder_resolves_client_at_terminal_not_at_chain_start():
    """Build a chain under client A, swap to client B before calling the
    terminal — the request must hit B, not the captured A. Proves the
    per-request RLS / use_client() story works even when chains span
    context boundaries."""
    from supabase_orm._sync import SupabaseModel
    from tests._sync.conftest import FakeClient, FakeResponse

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
        with use_client(client_b):  # type: ignore[arg-type]
            rows = qb.all()
        # Request hit B (we queued B's response and got it back); A was
        # never touched.
        assert client_a.builders == []
        assert len(client_b.builders) == 1
        assert rows[0].name == "B-pet"
    finally:
        set_client(None)
