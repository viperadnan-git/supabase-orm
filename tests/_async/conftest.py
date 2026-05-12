"""Test fixtures + a fake postgrest-py-shaped async client.

The ORM only ever touches the client through:
    client.table(name).select(...).<filter>.<order>...execute()
    client.table(name).insert(payload).execute()
    client.table(name).update(payload).<filter>.execute()
    client.table(name).delete().<filter>.execute()
    client.rpc(name, params).execute()

We don't need a real Supabase — a recorder that returns self on every chain
call and pops a queued response on ``.execute()`` is enough to exercise every
code path in the orm.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import pytest

from supabase_orm._async._client import set_client


class FakeResponse:
    def __init__(self, data: Any = None, count: int | None = None) -> None:
        self.data = data
        self.count = count


class FakeBuilder:
    """Chainable recorder. Every method returns self and logs the call."""

    # Methods we deliberately model — anything else is auto-recorded too.
    _CHAIN_METHODS = (
        "select",
        "insert",
        "update",
        "delete",
        "eq",
        "neq",
        "gt",
        "gte",
        "lt",
        "lte",
        "like",
        "ilike",
        "in_",
        "is_",
        "contains",
        "contained_by",
        "overlaps",
        "match",
        "text_search",
        "or_",
        "filter",
        "order",
        "limit",
        "offset",
        "range",
    )

    def __init__(self, client: "FakeClient", table: str) -> None:
        self._client = client
        self.table = table
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str, *a, **kw) -> "FakeBuilder":
        self.calls.append((name, a, kw))
        return self

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def _stub(*a, **kw):
            return self._record(name, *a, **kw)

        return _stub

    async def execute(self) -> FakeResponse:
        return self._client._pop_response()


class FakeRPC:
    def __init__(self, client: "FakeClient", name: str, params: dict) -> None:
        self._client = client
        self.name = name
        self.params = params

    async def execute(self) -> FakeResponse:
        return self._client._pop_response()


class FakeClient:
    """Records every .table() / .rpc() and returns queued responses."""

    def __init__(self) -> None:
        self.builders: list[FakeBuilder] = []
        self.rpc_calls: list[FakeRPC] = []
        self._responses: deque[FakeResponse] = deque()

    def queue(self, *responses: FakeResponse) -> None:
        self._responses.extend(responses)

    def _pop_response(self) -> FakeResponse:
        if not self._responses:
            return FakeResponse(data=[])
        return self._responses.popleft()

    def table(self, name: str) -> FakeBuilder:
        b = FakeBuilder(self, name)
        self.builders.append(b)
        return b

    def rpc(self, name: str, params: dict) -> FakeRPC:
        call = FakeRPC(self, name, params)
        self.rpc_calls.append(call)
        return call


@pytest.fixture
def fake_client() -> FakeClient:
    c = FakeClient()
    set_client(c)  # type: ignore[arg-type]
    try:
        yield c
    finally:
        set_client(None)
