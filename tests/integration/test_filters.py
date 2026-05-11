"""Round-trip every filter operator against a real PostgREST."""

from __future__ import annotations

from uuid import uuid4

import pytest

from .conftest import Owner, Pet


async def _seed_pets(n: int = 3) -> list[Pet]:
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    pets = []
    for i in range(n):
        pets.append(
            await Pet.create(
                owner_id=owner.id,
                name=f"pet-{i}",
                species="cat" if i % 2 == 0 else "dog",
                adopted=i == 0,
                tags=["a", "b"] if i == 0 else ["b"],
                amount=float(i),
            )
        )
    return pets


async def test_eq_and_neq(clean):
    pets = await _seed_pets()
    rows = await Pet.query.eq("species", "cat").all()
    assert {p.id for p in rows} == {p.id for p in pets if p.species == "cat"}

    rows = await Pet.query.neq("species", "cat").all()
    assert {p.id for p in rows} == {p.id for p in pets if p.species != "cat"}


async def test_gt_gte_lt_lte(clean):
    pets = await _seed_pets()
    expected = {p.id for p in pets if p.amount > 0}
    assert {p.id for p in await Pet.query.gt("amount", 0).all()} == expected
    assert {p.id for p in await Pet.query.gte("amount", 1).all()} == {
        p.id for p in pets if p.amount >= 1
    }
    assert {p.id for p in await Pet.query.lt("amount", 2).all()} == {
        p.id for p in pets if p.amount < 2
    }
    assert {p.id for p in await Pet.query.lte("amount", 1).all()} == {
        p.id for p in pets if p.amount <= 1
    }


async def test_like_and_ilike(clean):
    await _seed_pets()
    assert len(await Pet.query.like("name", "pet-%").all()) == 3
    assert len(await Pet.query.ilike("name", "PET-%").all()) == 3
    assert len(await Pet.query.ilike("name", "nope-%").all()) == 0


async def test_in_(clean):
    pets = await _seed_pets()
    ids = [pets[0].id, pets[2].id]
    rows = await Pet.query.in_("id", ids).all()
    assert {p.id for p in rows} == set(ids)


async def test_is_null_and_bool(clean):
    pets = await _seed_pets()
    # adopted has bool values; ``is_`` distinguishes ``true``/``false``/``null``.
    rows = await Pet.query.is_("adopted", True).all()
    assert {p.id for p in rows} == {p.id for p in pets if p.adopted}

    # Null check: clear owner_id on one pet to verify is_ null.
    target = pets[0]
    await target.update(owner_id=None)
    rows = await Pet.query.is_("owner_id", None).all()
    assert [p.id for p in rows] == [target.id]


async def test_contains_contained_by_overlaps(clean):
    pets = await _seed_pets()
    # pet[0] has ["a", "b"], others have ["b"].
    rows = await Pet.query.contains("tags", ["a"]).all()
    assert {p.id for p in rows} == {pets[0].id}

    rows = await Pet.query.contained_by("tags", ["a", "b", "c"]).all()
    assert {p.id for p in rows} == {p.id for p in pets}

    rows = await Pet.query.overlaps("tags", ["a"]).all()
    assert {p.id for p in rows} == {pets[0].id}


async def test_or_predicate(clean):
    pets = await _seed_pets()
    rows = await Pet.query.or_(
        lambda q: q.eq("name", pets[0].name),
        lambda q: q.eq("name", pets[2].name),
    ).all()
    assert {p.id for p in rows} == {pets[0].id, pets[2].id}


async def test_or_with_compound_branch_uses_and_wrap(clean):
    """The defensive ``and(...)`` wrap on multi-pred branches must parse."""
    pets = await _seed_pets()
    rows = await Pet.query.or_(
        lambda q: q.eq("species", "cat").gte("amount", 2),
        lambda q: q.eq("name", pets[1].name),
    ).all()
    expected = {p.id for p in pets if (p.species == "cat" and p.amount >= 2)}
    expected.add(pets[1].id)
    assert {p.id for p in rows} == expected


async def test_not_predicate(clean):
    pets = await _seed_pets()
    rows = await Pet.query.not_(lambda q: q.eq("species", "cat")).all()
    assert {p.id for p in rows} == {p.id for p in pets if p.species != "cat"}


@pytest.mark.parametrize("variant", ["fts", "plfts", "phfts", "wfts"])
async def test_text_search_variants(clean, variant):
    owner = await Owner.create(email=f"o-{uuid4()}@x.test")
    p = await Pet.create(
        owner_id=owner.id,
        name="fluffy whiskers",
        species="cat",
        adopted=False,
        tags=[],
        amount=0,
    )
    rows = await getattr(Pet.query, variant)("name", "fluffy").all()
    assert any(r.id == p.id for r in rows)
