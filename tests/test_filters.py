"""Filter operator registry + predicate compilation."""

from __future__ import annotations

from uuid import UUID

import pytest

from supabase_orm import register_op
from supabase_orm._filters import (
    OPERATORS,
    PREDICATES,
    _pred_value,
    apply_op,
    compile_predicate,
)

# ─── _pred_value ──────────────────────────────────────────────────────────


def test_pred_value_scalars():
    assert _pred_value(None) == "null"
    assert _pred_value(True) == "true"
    assert _pred_value(False) == "false"
    assert _pred_value(1) == "1"
    assert _pred_value("ok") == "ok"


def test_pred_value_quotes_commas_and_parens():
    assert _pred_value("a,b") == '"a,b"'
    assert _pred_value("a(b)") == '"a(b)"'
    assert _pred_value("plain") == "plain"


def test_pred_value_collection_to_tuple():
    assert _pred_value([1, 2, 3]) == "(1,2,3)"
    assert _pred_value((1, 2)) == "(1,2)"


def test_pred_value_serializes_uuids():
    u = UUID(int=0)
    assert _pred_value(u) == str(u)


# ─── compile_predicate ────────────────────────────────────────────────────


def test_compile_predicate_eq():
    assert compile_predicate("eq", "name", "alice") == "name.eq.alice"


def test_compile_predicate_is():
    # ``is_`` is registered with wire="is"
    assert compile_predicate("is_", "deleted_at", None) == "deleted_at.is.null"


def test_compile_predicate_in_uses_custom_compiler():
    out = compile_predicate("in_", "id", [1, 2, 3])
    assert out == "id.in.(1,2,3)"


def test_compile_predicate_unknown_raises():
    with pytest.raises(KeyError):
        compile_predicate("nope", "c", 1)


# ─── apply_op ─────────────────────────────────────────────────────────────


class _Recorder:
    def __init__(self):
        self.calls = []

    def _make(self, name):
        def fn(*a, **kw):
            self.calls.append((name, a, kw))
            return self

        return fn

    def __getattr__(self, name):
        return self._make(name)


def test_apply_op_dispatches_to_builder_method():
    rec = _Recorder()
    apply_op(rec, "eq", "name", "x")
    assert rec.calls == [("eq", ("name", "x"), {})]


def test_apply_op_serializes_value():
    rec = _Recorder()
    u = UUID(int=1)
    apply_op(rec, "eq", "id", u)
    name, args, _ = rec.calls[0]
    assert name == "eq"
    assert args == ("id", str(u))


def test_apply_op_in_serializes_each_element():
    rec = _Recorder()
    apply_op(rec, "in_", "id", [UUID(int=0), UUID(int=1)])
    name, args, _ = rec.calls[0]
    assert name == "in_"
    assert args == ("id", [str(UUID(int=0)), str(UUID(int=1))])


def test_apply_op_unknown_raises():
    with pytest.raises(KeyError):
        apply_op(_Recorder(), "nope", "x", 1)


def test_text_search_variants_route_to_text_search():
    rec = _Recorder()
    apply_op(rec, "fts", "body", "cat")
    apply_op(rec, "plfts", "body", "cat")
    apply_op(rec, "phfts", "body", "cat")
    apply_op(rec, "wfts", "body", "cat")
    # All four should hit text_search with the right options.
    assert [c[0] for c in rec.calls] == ["text_search"] * 4
    assert rec.calls[0][2] == {}
    assert rec.calls[1][2] == {"options": {"type": "plain"}}
    assert rec.calls[2][2] == {"options": {"type": "phrase"}}
    assert rec.calls[3][2] == {"options": {"type": "websearch"}}


# ─── register_op ──────────────────────────────────────────────────────────


def test_register_op_adds_to_registry():
    def _foo(b, c, v):
        return b.eq(c, v)  # not exercised here

    register_op("foo_op", builder=_foo)
    assert "foo_op" in OPERATORS
    assert "foo_op" in PREDICATES
    assert compile_predicate("foo_op", "c", 1) == "c.foo_op.1"


def test_register_op_with_wire_override():
    def _b(b, c, v):
        return b

    register_op("bar_op", wire="bar", builder=_b)
    assert compile_predicate("bar_op", "c", 1) == "c.bar.1"


def test_register_op_decorator_form():
    @register_op("baz_op")
    def _baz(b, c, v):
        return b

    assert callable(_baz)
    assert "baz_op" in OPERATORS
