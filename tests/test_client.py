"""Client lifecycle: ContextVar isolation, use_client, set_auth."""

from __future__ import annotations

import asyncio

import pytest

from supabase_orm import (
    SupabaseORMUsageError,
    get_client,
    set_auth,
    set_client,
    use_client,
)
from supabase_orm._client import _client, _default_key


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


# ─── set_auth ────────────────────────────────────────────────────────────


class _FakePostgrest:
    def __init__(self):
        self.token: str | None = None

    def auth(self, token: str) -> None:
        self.token = token


class _FakeAuthClient:
    def __init__(self):
        self.postgrest = _FakePostgrest()


def test_set_auth_applies_jwt_to_postgrest():
    c = _FakeAuthClient()
    set_client(c)  # type: ignore[arg-type]
    try:
        set_auth("user-jwt-abc")
        assert c.postgrest.token == "user-jwt-abc"
    finally:
        set_client(None)


def test_set_auth_none_restores_default_key():
    c = _FakeAuthClient()
    set_client(c)  # type: ignore[arg-type]
    key_token = _default_key.set("anon-key-xyz")
    try:
        set_auth("user-jwt")
        assert c.postgrest.token == "user-jwt"
        set_auth(None)
        assert c.postgrest.token == "anon-key-xyz"
    finally:
        _default_key.reset(key_token)
        set_client(None)


def test_set_auth_none_without_default_key_raises():
    c = _FakeAuthClient()
    # Run in a fresh context — the integration suite's session lifespan
    # may have set _default_key elsewhere; we want to assert behavior
    # when no key is recorded.
    from contextvars import copy_context

    def _body():
        _default_key.set(None)
        set_client(c)  # type: ignore[arg-type]
        with pytest.raises(SupabaseORMUsageError, match="default key"):
            set_auth(None)

    copy_context().run(_body)


async def test_set_auth_isolated_across_requests():
    """Two concurrent tasks each running their own use_client + set_auth
    must not see each other's JWT."""
    set_client(_FakeAuthClient())  # type: ignore[arg-type]

    async def request(jwt: str) -> str:
        async with use_client(_FakeAuthClient()):  # type: ignore[arg-type]
            set_auth(jwt)
            await asyncio.sleep(0)  # let the other task run between set & read
            return get_client().postgrest.token  # type: ignore[attr-defined]

    try:
        results = await asyncio.gather(
            request("jwt-alice"), request("jwt-bob"), request("jwt-carol")
        )
        assert results == ["jwt-alice", "jwt-bob", "jwt-carol"]
    finally:
        set_client(None)


# ─── ContextVar semantics ────────────────────────────────────────────────


def test_client_is_a_contextvar():
    """Sanity check: the storage backend is a ContextVar (not a module
    global). Documents the design assumption that per-request isolation
    relies on."""
    from contextvars import ContextVar

    assert isinstance(_client, ContextVar)
