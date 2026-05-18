# DO NOT EDIT — generated from tests/_async/test_debug.py by scripts/gen_sync.py.
# Run `python scripts/gen_sync.py` (or rebuild the package) to regenerate.

"""Debug introspection: ``.explain()``, ``__repr__``, query logging."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import pytest
from postgrest import SyncPostgrestClient

from supabase_orm._sync import ExplainResult, SupabaseModel, set_client

from .conftest import FakeResponse

_LOGGER_NAME = "supabase_orm.query"


class Pet(SupabaseModel, table="pets_dbg"):
    id: UUID
    name: str
    species: str


class _ClientShim:
    def __init__(self, pg: SyncPostgrestClient) -> None:
        self._pg = pg

    def table(self, name: str):
        return self._pg.from_(name)


@pytest.fixture
def pg_client():
    pg = SyncPostgrestClient(
        "http://localhost:54321/rest/v1",
        headers={"apikey": "secret-key", "Authorization": "Bearer tok"},
    )
    set_client(_ClientShim(pg))  # type: ignore[arg-type]
    try:
        yield pg
    finally:
        set_client(None)


# ─── .explain() ──────────────────────────────────────────────────────────


def test_explain_method_path_params(pg_client):
    ex = Pet.query.eq("species", "cat").limit(10).order_by("name").explain()
    assert isinstance(ex, ExplainResult)
    assert ex.method == "GET"
    assert ex.path == "http://localhost:54321/rest/v1/pets_dbg"
    assert ex.params == {
        "select": "id,name,species",
        "species": "eq.cat",
        "limit": "10",
        "order": "name.asc",
    }
    assert ex.body is None


def test_explain_url_composes_query_string(pg_client):
    ex = Pet.query.eq("species", "cat").explain()
    assert "?" in ex.url
    assert "species=eq.cat" in ex.url
    assert "select=id%2Cname%2Cspecies" in ex.url


def test_explain_redact_default_hides_auth(pg_client):
    ex = Pet.query.explain()
    assert ex.headers["apikey"] == "***REDACTED***"
    assert ex.headers["authorization"] == "***REDACTED***"


def test_explain_redact_false_shows_raw(pg_client):
    ex = Pet.query.explain(redact=False)
    assert ex.headers["apikey"] == "secret-key"
    assert ex.headers["authorization"] == "Bearer tok"


def test_explain_str_format(pg_client):
    s = str(Pet.query.eq("species", "cat").limit(5).explain())
    assert s.startswith("GET http://localhost:54321/rest/v1/pets_dbg?")
    assert "species=eq.cat" in s
    assert "apikey: ***REDACTED***" in s


# ─── __repr__ ────────────────────────────────────────────────────────────


def test_repr_empty_chain():
    assert repr(Pet.query) == "<QueryBuilder[Pet] select='id,name,species'>"


def test_repr_includes_filter_op():
    r = repr(Pet.query.eq("species", "cat"))
    assert "ops=[eq('species', 'cat')]" in r
    assert "QueryBuilder[Pet]" in r


def test_repr_lists_multiple_ops_in_order():
    r = repr(Pet.query.eq("species", "cat").limit(10).offset(5))
    assert "ops=[eq('species', 'cat'), limit(10), offset(5)]" in r


def test_repr_includes_order_direction():
    assert "order(name.asc)" in repr(Pet.query.order_by("name"))
    assert "order(name.desc)" in repr(Pet.query.order_by("-name"))


def test_repr_does_not_need_client():
    str(Pet.query.eq("name", "x").limit(1))


def test_repr_works_inside_exception_message():
    try:
        raise RuntimeError(f"failing on {Pet.query.eq('species', 'cat')!r}")
    except RuntimeError as e:
        assert "QueryBuilder[Pet]" in str(e)
        assert "eq('species', 'cat')" in str(e)


# ─── Query logging ───────────────────────────────────────────────────────


def test_logger_disabled_by_default(fake_client, caplog):
    fake_client.queue(FakeResponse(data=[]))
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        Pet.query.eq("name", "x").all()
    assert [r for r in caplog.records if r.name == _LOGGER_NAME] == []


def test_logger_emits_method_path_and_ms_when_debug(pg_client, caplog):
    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        try:
            Pet.query.eq("name", "x").all()
        except Exception:
            pass  # localhost:54321 not running; we only verify the log record
    records = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert records
    msg = records[0].getMessage()
    assert msg.startswith("GET http://localhost:54321/rest/v1/pets_dbg")
    assert "name=eq.x" in msg
    assert "ms)" in msg


def test_log_path_swallows_introspection_failure(fake_client, caplog):
    # FakeBuilder has no .request attribute; log path must fall back gracefully.
    pid = uuid4()
    fake_client.queue(
        FakeResponse(data=[{"id": str(pid), "name": "x", "species": "cat"}])
    )
    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        rows = Pet.query.eq("name", "x").all()
    assert len(rows) == 1
    records = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert len(records) == 1
    assert "no introspection" in records[0].getMessage()
