"""AsyncClient lifecycle.

This module is framework-agnostic. The orm reads its client from a
``ContextVar`` so that:

  * ``lifespan()`` sets the app-wide default at startup,
  * a request middleware can override it for a single request without
    leaking into others (each FastAPI request runs in its own copied
    context),
  * tests can scope their fake client to one test without races.

Typical FastAPI use::

    from contextlib import asynccontextmanager
    from supabase_orm import lifespan as orm_lifespan

    @asynccontextmanager
    async def lifespan(app):
        async with orm_lifespan(SUPABASE_URL, SUPABASE_KEY):
            yield

    app = FastAPI(lifespan=lifespan)

Per-request RLS via JWT (FastAPI middleware)::

    from supabase_orm import set_auth

    @app.middleware("http")
    async def attach_jwt(request, call_next):
        # ContextVar copy-on-task-creation makes this set local to the
        # request's context — no other request sees this JWT.
        if (auth := request.headers.get("authorization")):
            set_auth(auth.removeprefix("Bearer "))
        try:
            return await call_next(request)
        finally:
            set_auth(None)  # reset to the anon/service-role default

Tests / scripts::

    from supabase import acreate_client
    from supabase_orm import set_client

    set_client(await acreate_client(url, key))
    ...
    set_client(None)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

from supabase import AsyncClient, acreate_client

from ._exceptions import SupabaseORMUsageError

_client: ContextVar[AsyncClient | None] = ContextVar(
    "supabase_orm_client", default=None
)
# Stash the anon/service-role key the lifespan was opened with, so
# ``set_auth(None)`` can restore the default Authorization header without
# the caller having to remember it.
_default_key: ContextVar[str | None] = ContextVar(
    "supabase_orm_default_key", default=None
)


def get_client() -> AsyncClient:
    c = _client.get()
    if c is None:
        raise SupabaseORMUsageError(
            "Supabase AsyncClient not initialized. "
            "Wrap your app startup in `async with lifespan(url, key):` "
            "or call `set_client(client)` directly."
        )
    return c


def set_client(client: AsyncClient | None) -> None:
    """Bind ``client`` in the current async context.

    Call from app startup (or use :func:`lifespan`) to set the
    app-wide default; per-request overrides should prefer
    :func:`use_client` so the previous binding is restored on exit.
    """
    _client.set(client)


@asynccontextmanager
async def use_client(client: AsyncClient) -> AsyncIterator[AsyncClient]:
    """Bind ``client`` for the duration of the ``async with`` block only.

    Restores the previous binding on exit. Safe under concurrent FastAPI
    requests: each request runs in its own copied context, so the
    override never leaks across requests::

        async with use_client(per_request_client):
            row = await Pet.get(some_id)
    """
    token = _client.set(client)
    try:
        yield client
    finally:
        _client.reset(token)


def set_auth(jwt: str | None) -> None:
    """Apply a JWT (or revert to the default key) on the current client.

    Mutates the active client's postgrest sub-client so subsequent ORM
    calls send ``Authorization: Bearer <jwt>``. Postgres RLS then sees
    the user identity encoded in the token.

    Pass ``None`` to revert to the anon / service-role key the
    :func:`lifespan` was opened with.

    Safe to call from FastAPI middleware: ContextVar isolation per
    request means each request's JWT never leaks into another. Outside
    a request scope (background tasks, scripts), prefer wrapping in
    :func:`use_client` with a dedicated client.
    """
    client = get_client()
    target = jwt if jwt is not None else _default_key.get()
    if target is None:
        raise SupabaseORMUsageError(
            "set_auth(None) requires the client to have been opened via "
            "`lifespan(url, key)` so the default key is recorded. "
            "Otherwise pass an explicit JWT."
        )
    client.postgrest.auth(target)


@asynccontextmanager
async def lifespan(url: str, key: str) -> AsyncIterator[AsyncClient]:
    """Async context manager that owns one AsyncClient for its lifetime.

    Yields the client so callers can stash it on app state if they want;
    most code should just import ``get_client`` from inside request handlers.
    """
    client = await acreate_client(url, key)
    key_token = _default_key.set(key)
    client_token = _client.set(client)
    try:
        yield client
    finally:
        _client.reset(client_token)
        _default_key.reset(key_token)
        # Best-effort teardown of the underlying httpx pools. supabase-py's
        # AsyncClient doesn't expose a top-level close as of 2.x; we close
        # each subclient that does so connection pools drain cleanly on
        # graceful shutdown.
        for sub in ("postgrest", "auth", "storage", "functions"):
            obj = getattr(client, sub, None)
            close = getattr(obj, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 — shutdown is best-effort
                    pass
