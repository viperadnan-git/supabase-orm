"""QueryBuilder.iter() — keyset pagination over the PK."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from supabase_orm._async import SupabaseModel, SupabaseORMUsageError

from .conftest import FakeResponse


class Pet(SupabaseModel, table="pets_iter"):
    id: UUID
    name: str


def _row(pid: UUID, name: str = "x") -> dict:
    return {"id": str(pid), "name": name}


# ─── Termination ─────────────────────────────────────────────────────────


async def test_iter_yields_nothing_for_empty_result(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    out = [p async for p in Pet.query.iter(batch_size=5)]
    assert out == []


async def test_iter_stops_when_batch_smaller_than_batch_size(fake_client):
    """One partial batch ⇒ no follow-up request."""
    a, b = uuid4(), uuid4()
    fake_client.queue(FakeResponse(data=[_row(a, "A"), _row(b, "B")]))
    out = [p async for p in Pet.query.iter(batch_size=10)]
    assert [p.name for p in out] == ["A", "B"]
    # Only one terminal request was made.
    assert len(fake_client.builders) == 1


async def test_iter_paginates_through_full_then_partial_batch(fake_client):
    """Full batch ⇒ keep going. Partial batch ⇒ stop."""
    ids = [uuid4() for _ in range(7)]
    fake_client.queue(
        FakeResponse(data=[_row(i, f"R{n}") for n, i in enumerate(ids[:3])]),
        FakeResponse(data=[_row(i, f"R{n}") for n, i in enumerate(ids[3:6], start=3)]),
        FakeResponse(data=[_row(ids[6], "R6")]),  # partial batch ⇒ done
    )
    out = [p async for p in Pet.query.iter(batch_size=3)]
    assert [p.name for p in out] == [f"R{n}" for n in range(7)]
    assert len(fake_client.builders) == 3


async def test_iter_stops_when_batch_returns_empty_at_boundary(fake_client):
    """Batch of exactly batch_size ⇒ next batch is empty ⇒ stop."""
    ids = [uuid4() for _ in range(2)]
    fake_client.queue(
        FakeResponse(data=[_row(i, f"R{n}") for n, i in enumerate(ids)]),
        FakeResponse(data=[]),  # exact-multiple boundary
    )
    out = [p async for p in Pet.query.iter(batch_size=2)]
    assert len(out) == 2
    assert len(fake_client.builders) == 2


# ─── Per-batch wire shape ────────────────────────────────────────────────


async def test_iter_first_batch_has_no_cursor_predicate(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    _ = [p async for p in Pet.query.iter(batch_size=5)]
    calls = fake_client.builders[0].calls
    # First batch: select, order(id asc), limit(5). No gt() yet.
    assert ("order", ("id",), {"desc": False}) in calls
    assert ("limit", (5,), {}) in calls
    assert not any(c[0] == "gt" for c in calls)


async def test_iter_subsequent_batches_advance_cursor_to_last_pk(fake_client):
    """Each follow-up batch carries ``gt(pk, last_seen_pk)``."""
    a, b = uuid4(), uuid4()
    fake_client.queue(
        FakeResponse(data=[_row(a, "A"), _row(b, "B")]),  # full batch
        FakeResponse(data=[]),  # done
    )
    _ = [p async for p in Pet.query.iter(batch_size=2)]

    # Batch 2 must have gt("id", str(b)) — the last pk from batch 1.
    second = fake_client.builders[1].calls
    gt_calls = [c for c in second if c[0] == "gt"]
    assert len(gt_calls) == 1
    assert gt_calls[0][1] == ("id", str(b))


async def test_iter_layers_user_filters_on_every_batch(fake_client):
    """The user's chained filters get replayed onto each batch."""
    a = uuid4()
    fake_client.queue(
        FakeResponse(data=[_row(a, "A")]),
    )
    _ = [p async for p in Pet.query.eq("name", "cat").iter(batch_size=10)]
    calls = fake_client.builders[0].calls
    assert ("eq", ("name", "cat"), {}) in calls


# ─── Early cancellation ─────────────────────────────────────────────────


async def test_iter_break_mid_batch_does_not_fetch_next(fake_client):
    ids = [uuid4() for _ in range(3)]
    fake_client.queue(
        FakeResponse(data=[_row(i, f"R{n}") for n, i in enumerate(ids)]),
        FakeResponse(data=[]),
    )
    seen = []
    async for p in Pet.query.iter(batch_size=3):
        seen.append(p)
        break
    assert len(seen) == 1
    assert len(fake_client.builders) == 1


async def test_iter_break_at_batch_boundary_does_not_overfetch(fake_client):
    ids = [uuid4() for _ in range(4)]
    fake_client.queue(
        FakeResponse(data=[_row(i, f"R{n}") for n, i in enumerate(ids[:2])]),
        FakeResponse(data=[_row(i, f"R{n}") for n, i in enumerate(ids[2:], start=2)]),
    )
    seen = []
    async for p in Pet.query.iter(batch_size=2):
        seen.append(p)
        if len(seen) == 2:
            break
    assert len(seen) == 2
    assert len(fake_client.builders) == 1


async def test_iter_explicit_aclose_is_clean(fake_client):
    fake_client.queue(FakeResponse(data=[_row(uuid4(), "A")]))
    gen = Pet.query.iter(batch_size=10)
    first = await anext(gen)
    assert first.name == "A"
    await gen.aclose()
    # Second aclose() must be a no-op.
    await gen.aclose()


async def test_iter_can_restart_after_break(fake_client):
    a, b = uuid4(), uuid4()
    fake_client.queue(
        FakeResponse(data=[_row(a, "A")]),
        FakeResponse(data=[_row(b, "B")]),
    )
    first_pass = []
    async for p in Pet.query.iter(batch_size=10):
        first_pass.append(p)
        break

    second_pass = [p async for p in Pet.query.iter(batch_size=10)]
    assert [p.name for p in first_pass] == ["A"]
    assert [p.name for p in second_pass] == ["B"]


# ─── Conflict detection ─────────────────────────────────────────────────


async def test_iter_rejects_chained_order_by():
    with pytest.raises(SupabaseORMUsageError, match="iter\\(\\) owns ordering"):
        Pet.query.order_by("name").iter()


async def test_iter_rejects_chained_limit():
    with pytest.raises(SupabaseORMUsageError, match="iter\\(\\) owns ordering"):
        Pet.query.limit(10).iter()


async def test_iter_rejects_chained_offset():
    with pytest.raises(SupabaseORMUsageError, match="iter\\(\\) owns ordering"):
        Pet.query.offset(5).iter()


async def test_iter_rejects_chained_range():
    with pytest.raises(SupabaseORMUsageError, match="iter\\(\\) owns ordering"):
        Pet.query.range(0, 9).iter()


async def test_iter_validates_pk_is_a_model_field():
    """If the model declares a __pk__ that isn't a real field, fail fast."""

    class Bad(SupabaseModel, table="bad_pk_iter", pk="nope"):
        id: UUID

    with pytest.raises(SupabaseORMUsageError, match="needs __pk__ 'nope'"):
        Bad.query.iter()


# ─── Pre-flight runs at call time, not at first __anext__ ──────────────


async def test_iter_conflict_raised_before_iteration_starts():
    """Pre-flight checks must fire on .iter() call, not on the first
    ``async for`` step — so debugging stack traces point at the right line."""
    with pytest.raises(SupabaseORMUsageError):
        Pet.query.limit(1).iter()  # no `async for` — error fires at call


# ─── Composes with other terminals on the same chain ─────────────────────


async def test_chain_with_filters_and_predicates_iters_correctly(fake_client):
    """Sanity: realistic compound query iterates as expected."""
    a = uuid4()
    fake_client.queue(FakeResponse(data=[_row(a, "A")]))
    out = [
        p
        async for p in Pet.query.eq("name", "cat")
        .or_(Pet.f.name == "cat", Pet.f.name == "dog")
        .iter(batch_size=10)
    ]
    assert len(out) == 1
    calls = fake_client.builders[0].calls
    assert any(c[0] == "or_" for c in calls)
    assert any(c[0] == "eq" for c in calls)


# ─── Projection: as_(Mini) narrows the per-batch select ──────────────────


class PetWide(SupabaseModel, table="pets_iter_wide"):
    id: UUID
    name: str
    species: str
    adopted: bool
    tags: list[str] = []


class PetMini(SupabaseModel, table="pets_iter_wide"):
    id: UUID
    name: str


def test_wide_and_mini_have_independent_select_strings():
    """Two models on the same table compute their own __select__ from
    their own field declarations — no leakage."""
    assert PetWide.__select__ == "id,name,species,adopted,tags"
    assert PetMini.__select__ == "id,name"


async def test_iter_uses_mini_select_string_on_every_batch(fake_client):
    """as_(PetMini).iter() must send PetMini's narrow select on every
    paginated request — not PetWide's full one."""
    a, b, c = uuid4(), uuid4(), uuid4()
    fake_client.queue(
        FakeResponse(data=[_row(a, "A"), _row(b, "B")]),
        FakeResponse(data=[_row(c, "C")]),  # partial batch ⇒ done
    )
    out = [m async for m in PetWide.query.as_(PetMini).iter(batch_size=2)]
    assert len(out) == 3
    assert all(isinstance(m, PetMini) for m in out)

    # Every batch's select call must use PetMini's narrow string,
    # not PetWide's wide one.
    for builder in fake_client.builders:
        sel = next(c for c in builder.calls if c[0] == "select")
        assert sel[1] == ("id,name",), (
            f"expected PetMini's select on every batch, got {sel[1]}"
        )


async def test_iter_without_as_uses_full_model_select(fake_client):
    """Sanity: without as_(), the full model's select drives every batch."""
    a = uuid4()
    fake_client.queue(
        FakeResponse(
            data=[
                {
                    "id": str(a),
                    "name": "A",
                    "species": "cat",
                    "adopted": False,
                    "tags": [],
                }
            ]
        )
    )
    _ = [p async for p in PetWide.query.iter(batch_size=10)]
    sel = next(c for c in fake_client.builders[0].calls if c[0] == "select")
    assert sel[1] == ("id,name,species,adopted,tags",)
