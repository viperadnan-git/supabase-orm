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

    from supabase import acreate_client
    from supabase_orm import use_client

    @app.middleware("http")
    async def per_request_client(request, call_next):
        if (auth := request.headers.get("authorization")):
            jwt = auth.removeprefix("Bearer ")
            client = await acreate_client(URL, ANON_KEY)
            client.postgrest.auth(jwt)
            async with use_client(client):
                return await call_next(request)
        return await call_next(request)

The per-request client is the only safe pattern for RLS under
concurrent load: mutating headers on the app-wide client (e.g. via
``client.postgrest.auth(jwt)`` outside a ``use_client`` block) leaks
across overlapping requests because the underlying postgrest sub-client
is shared. ``ContextVar`` isolates *references*, not the objects they
point at.

Tests / scripts::

    from supabase import acreate_client
    from supabase_orm import set_client

    set_client(await acreate_client(url, key))
    ...
    set_client(None)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

from supabase import AsyncClient, acreate_client

from ._exceptions import SupabaseORMUsageError

_log = logging.getLogger("supabase_orm")

_client: ContextVar[AsyncClient | None] = ContextVar(
    "supabase_orm_client", default=None
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


@asynccontextmanager
async def lifespan(url: str, key: str) -> AsyncIterator[AsyncClient]:
    """Async context manager that owns one AsyncClient for its lifetime.

    Yields the client so callers can stash it on app state if they want;
    most code should just import ``get_client`` from inside request handlers.
    """
    client = await acreate_client(url, key)
    token = _client.set(client)
    try:
        yield client
    finally:
        _client.reset(token)
        # Best-effort teardown of the underlying httpx pools. supabase-py's
        # AsyncClient doesn't expose a top-level close as of 2.x; we close
        # each subclient that does so connection pools drain cleanly on
        # graceful shutdown. Failures are logged but not raised — shutdown
        # paths shouldn't cascade.
        for sub in ("postgrest", "auth", "storage", "functions"):
            obj = getattr(client, sub, None)
            close = getattr(obj, "aclose", None)
            if close is None:
                continue
            try:
                await close()
            except Exception as exc:  # noqa: BLE001 — shutdown is best-effort
                _log.warning("supabase_orm: failed to close %s: %r", sub, exc)
