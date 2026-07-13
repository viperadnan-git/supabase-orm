# DO NOT EDIT — generated from tests/_async/test_query.py by scripts/gen_sync.py.
# Run `python scripts/gen_sync.py` (or rebuild the package) to regenerate.

"""QueryBuilder — filters, ordering, terminals, write ops, as_, values."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

import pytest

from supabase_orm._sync import (
    Relation,
    SupabaseModel,
    SupabaseORMDoesNotExist,
    SupabaseORMMultipleObjectsReturned,
    SupabaseORMUsageError,
)

from .conftest import FakeResponse


class User(SupabaseModel, table="users_q"):
    id: UUID
    email: str
    is_active: bool = True


class UserMini(SupabaseModel, table="users_q"):
    id: UUID
    email: str


class OtherTable(SupabaseModel, table="other_q"):
    id: UUID


class Post(SupabaseModel, table="posts_q"):
    id: UUID
    views: int
    author: Annotated[User, Relation(filter={"is_active": True})]


# ─── Filter operators record onto raw builder ─────────────────────────────


def test_eq_records_op_and_filter(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    User.query.eq("email", "a@b.c").all()
    calls = fake_client.builders[0].calls
    assert ("select", ("id,email,is_active",), {}) in calls
    assert ("eq", ("email", "a@b.c"), {}) in calls


def test_unknown_column_raises_before_request(fake_client):
    with pytest.raises(AttributeError):
        User.query.eq("nope", 1)


def test_dotted_relation_column_filter_reaches_wire(fake_client):
    """``eq("relation.col", v)`` validates and reaches postgrest as-is."""
    Post._validate_column("author.is_active")
    fake_client.queue(FakeResponse(data=[]))
    Post.query.eq("views", 10).eq("author.is_active", False).all()
    calls = fake_client.builders[0].calls
    assert ("eq", ("views", 10), {}) in calls
    assert ("eq", ("author.is_active", False), {}) in calls


def test_dotted_relation_column_typo_in_head_still_raises(fake_client):
    with pytest.raises(AttributeError):
        Post.query.eq("authr.is_active", False)


def test_in_serializes_each_element(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    a, b = uuid4(), uuid4()
    User.query.in_("id", [a, b]).all()
    in_call = next(c for c in fake_client.builders[0].calls if c[0] == "in_")
    assert in_call[1] == ("id", [str(a), str(b)])


# ─── or_ / not_ ───────────────────────────────────────────────────────────


def test_or_with_two_simple_branches(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    User.query.or_(
        lambda q: q.eq("email", "a@b.c"),
        lambda q: q.eq("email", "x@y.z"),
    ).all()
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    # The orm strips the outer "or(...)" before calling postgrest's or_().
    inner = or_call[1][0]
    assert inner == "email.eq.a@b.c,email.eq.x@y.z"


def test_or_branch_with_multiple_preds_wraps_in_and(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    User.query.or_(
        lambda q: q.eq("email", "a@b.c").eq("is_active", True),
        lambda q: q.eq("email", "x@y.z"),
    ).all()
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    inner = or_call[1][0]
    assert inner == "and(email.eq.a@b.c,is_active.eq.true),email.eq.x@y.z"


def test_not_compiles_to_not_and_group(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    User.query.not_(lambda q: q.eq("email", "a@b.c")).all()
    or_call = next(c for c in fake_client.builders[0].calls if c[0] == "or_")
    assert or_call[1][0] == "not.and(email.eq.a@b.c)"


# ─── order / limit / offset / range ──────────────────────────────────────


def test_order_by_handles_desc_prefix(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    User.query.order_by("-email", "id").all()
    orders = [c for c in fake_client.builders[0].calls if c[0] == "order"]
    assert orders[0] == ("order", ("email",), {"desc": True})
    assert orders[1] == ("order", ("id",), {"desc": False})


def test_order_by_relation_column_uses_embed_syntax(fake_client):
    """rel.col → rel(col); capability (to-many, nesting) is PostgREST's call."""
    fake_client.queue(FakeResponse(data=[]))
    Post.query.order_by("-author.email").all()
    order = next(c for c in fake_client.builders[0].calls if c[0] == "order")
    assert order == ("order", ("author(email)",), {"desc": True})


def test_limit_offset_range(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    User.query.limit(10).offset(5).range(0, 9).all()
    calls = fake_client.builders[0].calls
    assert ("limit", (10,), {}) in calls
    assert ("offset", (5,), {}) in calls
    assert ("range", (0, 9), {}) in calls


# ─── Read terminals ──────────────────────────────────────────────────────


def test_all_validates_rows(fake_client):
    uid = uuid4()
    fake_client.queue(
        FakeResponse(data=[{"id": str(uid), "email": "a@b.c", "is_active": True}])
    )
    rows = User.query.eq("is_active", True).all()
    assert len(rows) == 1 and rows[0].id == uid


def test_first_returns_first_or_none(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    assert User.query.eq("is_active", True).first() is None

    uid = uuid4()
    fake_client.queue(
        FakeResponse(data=[{"id": str(uid), "email": "a@b.c", "is_active": True}])
    )
    out = User.query.eq("is_active", True).first()
    assert out is not None and out.id == uid


def test_one_raises_when_empty(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    with pytest.raises(SupabaseORMDoesNotExist):
        User.query.eq("is_active", True).one()


def test_one_raises_when_multiple(fake_client):
    fake_client.queue(
        FakeResponse(
            data=[
                {"id": str(uuid4()), "email": "a@b.c", "is_active": True},
                {"id": str(uuid4()), "email": "x@y.z", "is_active": True},
            ]
        )
    )
    with pytest.raises(SupabaseORMMultipleObjectsReturned):
        User.query.eq("is_active", True).one()


def test_one_returns_single(fake_client):
    uid = uuid4()
    fake_client.queue(
        FakeResponse(data=[{"id": str(uid), "email": "a@b.c", "is_active": True}])
    )
    out = User.query.eq("is_active", True).one()
    assert out.id == uid


def test_maybe_one_returns_none_or_one(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    assert User.query.eq("is_active", True).maybe_one() is None

    uid = uuid4()
    fake_client.queue(
        FakeResponse(data=[{"id": str(uid), "email": "a@b.c", "is_active": True}])
    )
    out = User.query.eq("is_active", True).maybe_one()
    assert out is not None and out.id == uid


def test_maybe_one_raises_when_multiple(fake_client):
    fake_client.queue(
        FakeResponse(
            data=[
                {"id": str(uuid4()), "email": "a@b.c", "is_active": True},
                {"id": str(uuid4()), "email": "x@y.z", "is_active": True},
            ]
        )
    )
    with pytest.raises(SupabaseORMMultipleObjectsReturned):
        User.query.eq("is_active", True).maybe_one()


def test_count_uses_head_select_and_replays_ops(fake_client):
    fake_client.queue(FakeResponse(data=None, count=42))
    n = User.query.eq("is_active", True).count()
    assert n == 42
    # count() builds a fresh request. Look for the builder whose select was
    # called with head=True.
    count_builder = next(
        b
        for b in fake_client.builders
        if any(c[0] == "select" and c[2].get("head") for c in b.calls)
    )
    select_call = next(c for c in count_builder.calls if c[0] == "select")
    # Embed-aware select so embedded-column filters keep their !inner join.
    assert select_call[1] == (User.__select__,)
    assert select_call[2] == {"count": "exact", "head": True}
    assert ("eq", ("is_active", True), {}) in count_builder.calls


def test_count_none_returns_zero(fake_client):
    fake_client.queue(FakeResponse(data=None, count=None))
    assert User.query.eq("is_active", True).count() == 0


def test_exists_true_when_row_returned(fake_client):
    fake_client.queue(FakeResponse(data=[{"id": str(uuid4())}]))
    assert User.query.eq("is_active", True).exists() is True
    b = fake_client.builders[-1]
    select_call = next(c for c in b.calls if c[0] == "select")
    # Embed-aware select, limit 1 — no count, no head.
    assert select_call[1] == (User.__select__,)
    assert "count" not in select_call[2] and "head" not in select_call[2]
    assert ("limit", (1,), {}) in b.calls
    assert ("eq", ("is_active", True), {}) in b.calls


def test_exists_false_on_empty(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    assert User.query.eq("is_active", True).exists() is False


def test_exists_false_on_none(fake_client):
    fake_client.queue(FakeResponse(data=None))
    assert User.query.exists() is False


def test_all_with_count_returns_pair(fake_client):
    uid = uuid4()
    fake_client.queue(
        FakeResponse(
            data=[{"id": str(uid), "email": "a@b.c", "is_active": True}],
            count=99,
        )
    )
    rows, total = User.query.eq("is_active", True).all_with_count()
    assert total == 99 and len(rows) == 1


# ─── Write terminals ─────────────────────────────────────────────────────


def test_delete_requires_filter(fake_client):
    with pytest.raises(SupabaseORMUsageError, match="Refusing unfiltered"):
        User.query.delete()


def test_delete_with_filter_runs(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    out = User.query.eq("is_active", False).delete()
    assert out == []
    # delete() builds a fresh request and replays the op log onto it.
    del_builder = next(
        b for b in fake_client.builders if any(c[0] == "delete" for c in b.calls)
    )
    assert ("delete", (), {"returning": "representation"}) in del_builder.calls
    assert ("eq", ("is_active", False), {}) in del_builder.calls


def test_delete_allow_unfiltered(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    User.query.delete(allow_unfiltered=True)
    del_builder = next(
        b for b in fake_client.builders if any(c[0] == "delete" for c in b.calls)
    )
    assert ("delete", (), {"returning": "representation"}) in del_builder.calls


def test_update_requires_filter(fake_client):
    with pytest.raises(SupabaseORMUsageError, match="Refusing unfiltered"):
        User.query.update(is_active=True)


def test_update_requires_values(fake_client):
    with pytest.raises(SupabaseORMUsageError, match="at least one"):
        User.query.eq("is_active", False).update()


def test_update_runs_with_filter(fake_client):
    uid = uuid4()
    fake_client.queue(
        FakeResponse(data=[{"id": str(uid), "email": "a@b.c", "is_active": True}])
    )
    rows = User.query.eq("is_active", False).update(is_active=True)
    assert len(rows) == 1
    upd_builder = next(
        b for b in fake_client.builders if any(c[0] == "update" for c in b.calls)
    )
    update_call = next(c for c in upd_builder.calls if c[0] == "update")
    assert update_call[1][0] == {"is_active": True}


# ─── as_ projection ──────────────────────────────────────────────────────


def test_as_rebinds_to_same_table_model(fake_client):
    uid = uuid4()
    fake_client.queue(FakeResponse(data=[{"id": str(uid), "email": "a@b.c"}]))
    rows = User.query.eq("is_active", True).as_(UserMini).all()
    assert isinstance(rows[0], UserMini)
    assert rows[0].id == uid

    # The builder should have been rebuilt with UserMini's select string.
    # Two builders are created (initial + the as_ rebuild).
    select_calls = [
        c for b in fake_client.builders for c in b.calls if c[0] == "select"
    ]
    # Last select call should be UserMini.__select__ = "id,email"
    assert select_calls[-1][1] == ("id,email",)


def test_as_different_table_raises(fake_client):
    with pytest.raises(SupabaseORMUsageError, match="different table"):
        User.query.as_(OtherTable)  # type: ignore[type-var]


# ─── as_(plain BaseModel) — validation-only rebinding ────────────────────


def test_as_plain_basemodel_validation_only(fake_client):
    """Plain BaseModel target: wire ``select`` stays the source's, but
    rows come back as the BaseModel instances."""
    from pydantic import BaseModel

    class UserCard(BaseModel):
        id: UUID
        email: str

    uid = uuid4()
    fake_client.queue(
        FakeResponse(data=[{"id": str(uid), "email": "a@b.c", "is_active": True}])
    )
    rows = User.query.eq("is_active", True).as_(UserCard).all()

    # Validated as the plain BaseModel — not the source User.
    assert isinstance(rows[0], UserCard)
    assert not isinstance(rows[0], User)
    assert rows[0].id == uid

    # Wire select stayed the source's full string (no narrowing).
    sel = next(c for c in fake_client.builders[0].calls if c[0] == "select")
    assert sel[1] == ("id,email,is_active",)


def test_as_plain_basemodel_keeps_source_predicate_validation(fake_client):
    """After as_(plain BaseModel), the source still owns predicate column
    validation — you can filter on source columns the target doesn't have."""
    from pydantic import BaseModel

    class UserCard(BaseModel):
        id: UUID  # only one field — no email, no is_active

    fake_client.queue(FakeResponse(data=[]))
    # Filter on `is_active` — exists on User (source), not on UserCard.
    # Should not raise, because predicates validate against source.
    User.query.eq("is_active", True).as_(UserCard).all()
    calls = fake_client.builders[0].calls
    assert ("eq", ("is_active", True), {}) in calls


def test_as_supabase_model_same_table_still_narrows_wire(fake_client):
    """Sanity: SupabaseModel same-table target keeps the existing narrow-
    wire behavior (full rebind, not validation-only)."""
    uid = uuid4()
    fake_client.queue(FakeResponse(data=[{"id": str(uid), "email": "a@b.c"}]))
    rows = User.query.eq("is_active", True).as_(UserMini).all()
    assert isinstance(rows[0], UserMini)
    sel = next(c for c in fake_client.builders[-1].calls if c[0] == "select")
    assert sel[1] == ("id,email",)  # UserMini's narrower select


def test_as_rejects_non_basemodel():
    """Non-BaseModel targets fail loudly at call time."""
    with pytest.raises(SupabaseORMUsageError, match="Pydantic BaseModel"):
        User.query.as_(dict)  # type: ignore[type-var]


def test_as_plain_basemodel_iter_works(fake_client):
    """iter() must keep working after as_(plain BaseModel) — keyset uses
    the source's PK from the raw dict (the source's __select__ always
    includes the PK column)."""
    from pydantic import BaseModel

    class UserCard(BaseModel):
        id: UUID
        email: str

    a, b = uuid4(), uuid4()
    fake_client.queue(
        FakeResponse(
            data=[
                {"id": str(a), "email": "A", "is_active": True},
                {"id": str(b), "email": "B", "is_active": True},
            ]
        ),
        FakeResponse(data=[]),
    )
    out = [u for u in User.query.as_(UserCard).iter(batch_size=2)]
    assert len(out) == 2
    assert all(isinstance(u, UserCard) for u in out)

    # Cursor in the second batch must be the last seen PK — read from the
    # dict, not the validated UserCard object.
    second_batch_calls = fake_client.builders[1].calls
    gt_calls = [c for c in second_batch_calls if c[0] == "gt"]
    assert gt_calls and gt_calls[0][1] == ("id", str(b))


# ─── values ──────────────────────────────────────────────────────────────


def test_values_returns_raw_dicts(fake_client):
    fake_client.queue(FakeResponse(data=[{"id": "x", "email": "a@b.c"}]))
    rows = User.query.eq("is_active", True).values("id", "email")
    assert rows == [{"id": "x", "email": "a@b.c"}]


def test_values_requires_columns(fake_client):
    with pytest.raises(SupabaseORMUsageError, match="at least one column"):
        User.query.values()


# ─── relation filters auto-applied ───────────────────────────────────────


def test_relation_filter_emitted_on_terminal(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    Post.query.eq("id", uuid4()).all()
    # Should have a filter() call applying the relation filter
    # 'author.is_active' op='eq' value='true'.
    filters = [c for c in fake_client.builders[0].calls if c[0] == "filter"]
    assert any(f[1] == ("author.is_active", "eq", "true") for f in filters), filters


# ─── raw escape hatch ────────────────────────────────────────────────────


def test_raw_returns_builder_with_relation_filters_applied(fake_client):
    qb = Post.query.eq("id", uuid4())
    b = qb.raw()
    # raw() applies relation filters but does not call execute.
    filters = [c for c in b.calls if c[0] == "filter"]
    assert any(f[1][0] == "author.is_active" for f in filters)


# ─── QueryBuilder.update/delete returning= mode ─────────────────────────


def test_query_update_minimal_returns_none(fake_client):
    fake_client.queue(FakeResponse(data=None))
    result = User.query.eq("is_active", True).update(
        email="y@x.test", returning="minimal"
    )
    assert result is None
    up = next(c for c in fake_client.builders[-1].calls if c[0] == "update")
    assert up[2]["returning"] == "minimal"


def test_query_delete_minimal_returns_none(fake_client):
    fake_client.queue(FakeResponse(data=None))
    result = User.query.eq("is_active", True).delete(returning="minimal")
    assert result is None
    d = next(c for c in fake_client.builders[-1].calls if c[0] == "delete")
    assert d[2]["returning"] == "minimal"


def test_query_delete_default_passes_representation(fake_client):
    uid = uuid4()
    fake_client.queue(
        FakeResponse(data=[{"id": str(uid), "email": "a@b.c", "is_active": True}])
    )
    rows = User.query.eq("is_active", True).delete()
    assert len(rows) == 1
    d = next(c for c in fake_client.builders[-1].calls if c[0] == "delete")
    assert d[2]["returning"] == "representation"
