"""Predicate API round-trips against real PostgREST.

The mock suite proves we emit the right predicate strings. These tests
prove PostgREST parses and applies them correctly — including the
``not.or(...)``, nested ``and(or(...))``, and atom-form negation cases
that string-concatenation makes easy to get subtly wrong.
"""

from __future__ import annotations

from uuid import uuid4

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


# ─── Atomic predicates ────────────────────────────────────────────────────


async def test_eq_predicate_via_or_single_branch(clean):
    pets = await _seed_pets()
    rows = await Pet.query.or_(Pet.f.species == "cat").all()
    assert {p.id for p in rows} == {p.id for p in pets if p.species == "cat"}


async def test_comparison_operators_round_trip(clean):
    pets = await _seed_pets()
    rows = await Pet.query.or_(Pet.f.amount >= 1).all()
    assert {p.id for p in rows} == {p.id for p in pets if p.amount >= 1}

    rows = await Pet.query.or_(Pet.f.amount < 2).all()
    assert {p.id for p in rows} == {p.id for p in pets if p.amount < 2}


async def test_in_predicate(clean):
    pets = await _seed_pets()
    ids = [pets[0].id, pets[2].id]
    rows = await Pet.query.or_(Pet.f.id.in_(ids)).all()
    assert {p.id for p in rows} == set(ids)


async def test_like_predicate(clean):
    await _seed_pets()
    rows = await Pet.query.or_(Pet.f.name.like("pet-%")).all()
    assert len(rows) == 3


async def test_is_null_predicate(clean):
    pets = await _seed_pets()
    await pets[0].update(owner_id=None)
    rows = await Pet.query.or_(Pet.f.owner_id.is_null()).all()
    assert [p.id for p in rows] == [pets[0].id]


async def test_contains_predicate(clean):
    pets = await _seed_pets()
    # Only pets[0] has tag "a".
    rows = await Pet.query.or_(Pet.f.tags.contains(["a"])).all()
    assert {p.id for p in rows} == {pets[0].id}


# ─── Composition: |, &, ~ ────────────────────────────────────────────────


async def test_or_composition_two_branches(clean):
    pets = await _seed_pets()
    rows = await Pet.query.or_(
        Pet.f.name == pets[0].name,
        Pet.f.name == pets[2].name,
    ).all()
    assert {p.id for p in rows} == {pets[0].id, pets[2].id}


async def test_and_inside_or_branch(clean):
    pets = await _seed_pets()
    rows = await Pet.query.or_(
        Pet.f.name == pets[1].name,
        (Pet.f.species == "cat") & (Pet.f.amount >= 2),
    ).all()
    expected = {pets[1].id} | {
        p.id for p in pets if p.species == "cat" and p.amount >= 2
    }
    assert {p.id for p in rows} == expected


async def test_pipe_composition_flattens(clean):
    """``a | b | c`` should match rows matching any of the three."""
    pets = await _seed_pets()
    p = (
        (Pet.f.name == pets[0].name)
        | (Pet.f.name == pets[1].name)
        | (Pet.f.name == pets[2].name)
    )
    rows = await Pet.query.or_(p).all()
    assert {p.id for p in rows} == {p.id for p in pets}


async def test_not_of_atom(clean):
    pets = await _seed_pets()
    rows = await Pet.query.not_(Pet.f.species == "cat").all()
    assert {p.id for p in rows} == {p.id for p in pets if p.species != "cat"}


async def test_not_of_or_group(clean):
    """``not.or(name=X, name=Y)`` must parse as "neither X nor Y"."""
    pets = await _seed_pets()
    rows = await Pet.query.not_(
        (Pet.f.name == pets[0].name) | (Pet.f.name == pets[1].name)
    ).all()
    assert {p.id for p in rows} == {pets[2].id}


async def test_not_of_and_group(clean):
    pets = await _seed_pets()
    rows = await Pet.query.not_((Pet.f.species == "cat") & (Pet.f.amount == 0)).all()
    # Exclude pets[0] (cat, amount=0) only; pets[2] is cat amount=2,
    # pets[1] is dog amount=1 → both retained.
    assert {p.id for p in rows} == {pets[1].id, pets[2].id}


# ─── Chain integration ───────────────────────────────────────────────────


async def test_chain_eq_plus_predicate_or(clean):
    """Chain handles AND; predicate args handle OR. They mix freely."""
    pets = await _seed_pets()
    rows = await (
        Pet.query.eq("adopted", False)
        .or_(Pet.f.name == pets[1].name, Pet.f.name == pets[2].name)
        .all()
    )
    # pets[1] and pets[2] are both adopted=False (only pets[0] is adopted).
    assert {p.id for p in rows} == {pets[1].id, pets[2].id}


# ─── Backward compat — lambda form still works against the server ────────


async def test_legacy_lambda_or_still_works(clean):
    """The old ``or_(lambda q: q.eq(...))`` form must keep working
    end-to-end so 0.1.x callers aren't broken by 0.2.0."""
    pets = await _seed_pets()
    rows = await Pet.query.or_(
        lambda q: q.eq("name", pets[0].name),
        lambda q: q.eq("name", pets[2].name),
    ).all()
    assert {p.id for p in rows} == {pets[0].id, pets[2].id}


# ─── Order / .asc() / .desc() ────────────────────────────────────────────


async def test_typed_order_desc_real_round_trip(clean):
    pets = await _seed_pets()
    rows = await Pet.query.order_by(Pet.f.amount.desc()).all()
    assert [r.amount for r in rows] == sorted([p.amount for p in pets], reverse=True)


async def test_typed_order_asc_default(clean):
    pets = await _seed_pets()
    rows = await Pet.query.order_by(Pet.f.amount).all()
    assert [r.amount for r in rows] == sorted(p.amount for p in pets)


async def test_order_by_with_nulls_last(clean):
    """``nulls="last"`` puts NULLs after the values regardless of ASC/DESC."""
    pets = await _seed_pets()
    # Null out one pet's owner_id; sort by owner_id with nulls last.
    await pets[0].update(owner_id=None)
    rows = await Pet.query.order_by(Pet.f.owner_id.asc(nulls="last")).all()
    # The orphaned pet must appear at the end.
    assert rows[-1].id == pets[0].id


async def test_order_by_string_and_typed_compose(clean):
    """Strings and Order objects mix freely in one call."""
    await _seed_pets()
    rows = await Pet.query.order_by("species", Pet.f.amount.desc()).all()
    # First sort key: species asc; ties broken by amount desc.
    species_groups: list[list[float]] = []
    last_species = None
    for r in rows:
        if r.species != last_species:
            species_groups.append([])
            last_species = r.species
        species_groups[-1].append(r.amount)
    # Each species group must be amount-descending internally.
    for group in species_groups:
        assert group == sorted(group, reverse=True)


# ─── as_(plain BaseModel) — validation-only ──────────────────────────────


async def test_as_plain_basemodel_round_trip(clean):
    """Real PostgREST: as_(plain BaseModel) returns the BaseModel instances,
    while filters continue using source columns."""
    from pydantic import BaseModel

    class PetCard(BaseModel):
        id: str  # plain str ok — pydantic coerces uuid string
        name: str

    pets = await _seed_pets()
    cards = await Pet.query.in_("id", [p.id for p in pets]).as_(PetCard).all()
    assert len(cards) == len(pets)
    assert all(isinstance(c, PetCard) for c in cards)
    # Names round-trip correctly even though PetCard doesn't declare
    # species/adopted/tags etc.
    assert {c.name for c in cards} == {p.name for p in pets}
