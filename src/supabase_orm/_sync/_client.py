# DO NOT EDIT — generated from src/supabase_orm/_async/_client.py by scripts/gen_sync.py.
# Run `python scripts/gen_sync.py` (or rebuild the package) to regenerate.

"""Client lifecycle.

Bind a client once at startup, optionally override per-request::

    # FastAPI / ASGI
    with lifespan(URL, KEY):
        ...

    # scripts, cron, Celery
    init(create_client(URL, KEY))
    ...
    shutdown()

    # per-request RLS (FastAPI middleware)
    @app.middleware("http")
    def per_request_client(request, call_next):
        if (auth := request.headers.get("authorization")):
            jwt = auth.removeprefix("Bearer ")
            client = create_client(URL, ANON_KEY)
            client.postgrest.auth(jwt)
            with use_client(client):
                return call_next(request)
        return call_next(request)

Per-request ``use_client()`` is the only safe pattern for RLS under
concurrent load: mutating headers on the app-wide client leaks across
overlapping requests because the postgrest sub-client is shared.
``ContextVar`` isolates references, not the objects they point at.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from supabase import Client, create_client

from .._exceptions import SupabaseORMUsageError

_log = logging.getLogger("supabase_orm")

# Two-level lookup: a module global for the app-wide default (visible to
# every task — ASGI request handlers are siblings of the lifespan task,
# not children, so ContextVar inheritance wouldn't reach them), plus a
# ContextVar override for per-request scoping via use_client().
_default_client: Client | None = None
_client_override: ContextVar[Client | None] = ContextVar(
    "supabase_orm_client_override", default=None
)
# Non-None iff init()/lifespan() registered ownership; shutdown() closes.
_owned_client: Client | None = None


def get_client() -> Client:
    c = _client_override.get() or _default_client
    if c is None:
        raise SupabaseORMUsageError(
            "Supabase Client not initialized. "
            "Wrap your app startup in `with lifespan(url, key):` "
            "or call `set_client(client)` directly."
        )
    return c


def set_client(client: Client | None) -> None:
    """Bind ``client`` as the app-wide default; caller keeps ownership.

    ``shutdown()`` unbinds but does not close. For ownership transfer use
    :func:`init`.
    """
    global _default_client
    _default_client = client


def init(client: Client) -> Client:
    """Bind ``client`` and transfer ownership: ``shutdown()`` will close it.

    Returns ``client`` for inline composition::

        init(create_client(URL, KEY))
    """
    global _owned_client
    _owned_client = client
    set_client(client)
    return client


def shutdown() -> None:
    """Unbind the app-wide client. Closes it if :func:`init` registered ownership.

    Idempotent; no-op when nothing was bound. Subclient close failures
    are logged, not raised.
    """
    global _owned_client
    set_client(None)
    if _owned_client is None:
        return
    client, _owned_client = _owned_client, None
    # supabase-py's Client has no top-level close as of 2.x — drain
    # each subclient's httpx pool individually.
    for sub in ("postgrest", "auth", "storage", "functions"):
        obj = getattr(client, sub, None)
        close = getattr(obj, "close", None)
        if close is None:
            continue
        try:
            close()
        except Exception as exc:  # noqa: BLE001
            _log.warning("supabase_orm: failed to close %s: %r", sub, exc)


@contextmanager
def use_client(client: Client) -> Iterator[Client]:
    """Bind ``client`` for the duration of the ``with`` block only.

    Per-task isolated — concurrent requests don't see each other's
    overrides.
    """
    token = _client_override.set(client)
    try:
        yield client
    finally:
        _client_override.reset(token)


@contextmanager
def lifespan(url: str, key: str) -> Iterator[Client]:
    """Context manager that owns one ``Client`` for its lifetime.

    Builds the client, hands ownership to the orm via :func:`init`,
    drains pools on exit via :func:`shutdown`.
    """
    client = init(create_client(url, key))
    try:
        yield client
    finally:
        shutdown()
