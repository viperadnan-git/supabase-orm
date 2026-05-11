"""SupabaseModel behavior — subclass setup, get/find/create/save/update/delete."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

import pytest

from supabase_orm import (
    Relation,
    SupabaseModel,
    SupabaseORMDoesNotExist,
    SupabaseORMUsageError,
)

from .conftest import FakeResponse

# ─── Models used across tests ────────────────────────────────────────────


class User(SupabaseModel, table="users_base"):
    id: UUID
    email: str


class Pet(SupabaseModel, table="pets_base"):
    id: UUID
    name: str
    species: str
    adopted: bool


class PetWithOwner(SupabaseModel, table="pets_owner_base"):
    id: UUID
    name: str
    owner: Annotated[User, Relation(join="inner")]


# ─── Subclass setup ──────────────────────────────────────────────────────


def test_table_metadata_populated():
    assert Pet.__table__ == "pets_base"
    assert Pet.__pk__ == "id"
    assert Pet.__select__ == "id,name,species,adopted"
    assert Pet.__list_adapter__ is not None


def test_custom_pk():
    class Thing(SupabaseModel, table="things", pk="slug"):
        slug: str
        name: str

    assert Thing.__pk__ == "slug"


def test_query_without_table_raises():
    class Abstract(SupabaseModel):
        x: int = 0

    with pytest.raises(SupabaseORMUsageError, match="no __table__"):
        Abstract.query  # noqa: B018  (descriptor call)


def test_validate_column_known():
    Pet._validate_column("name")
    Pet._validate_column("species.id")  # relation.column form is allowed


def test_validate_column_unknown():
    with pytest.raises(AttributeError, match="no column"):
        Pet._validate_column("nope")


# ─── get / find ──────────────────────────────────────────────────────────


async def test_get_returns_validated_row(fake_client):
    pid = uuid4()
    fake_client.queue(
        FakeResponse(
            data=[
                {
                    "id": str(pid),
                    "name": "Whiskers",
                    "species": "cat",
                    "adopted": False,
                }
            ]
        )
    )
    p = await Pet.get(pid)
    assert isinstance(p, Pet)
    assert p.id == pid
    assert p.name == "Whiskers"


async def test_get_missing_raises(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    with pytest.raises(SupabaseORMDoesNotExist):
        await Pet.get(uuid4())


async def test_find_returns_none_on_miss(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    assert await Pet.find(uuid4()) is None


async def test_find_returns_row_on_hit(fake_client):
    pid = uuid4()
    fake_client.queue(
        FakeResponse(
            data=[
                {
                    "id": str(pid),
                    "name": "x",
                    "species": "cat",
                    "adopted": True,
                }
            ]
        )
    )
    p = await Pet.find(pid)
    assert p is not None and p.id == pid


# ─── create / bulk_create ────────────────────────────────────────────────


async def test_create_flat_uses_insert_response_directly(fake_client):
    pid = uuid4()
    fake_client.queue(
        FakeResponse(
            data=[
                {
                    "id": str(pid),
                    "name": "Whiskers",
                    "species": "cat",
                    "adopted": False,
                }
            ]
        )
    )
    p = await Pet.create(id=pid, name="Whiskers", species="cat", adopted=False)
    assert isinstance(p, Pet) and p.id == pid

    # Insert payload should have UUID stringified.
    builder = fake_client.builders[0]
    insert_call = next(c for c in builder.calls if c[0] == "insert")
    payload = insert_call[1][0]
    assert payload["id"] == str(pid)
    assert payload["name"] == "Whiskers"


async def test_create_returns_no_rows_raises(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    with pytest.raises(ValueError, match="returned no rows"):
        await Pet.create(id=uuid4(), name="x", species="cat", adopted=False)


async def test_create_with_relations_does_followup_get(fake_client):
    pid = uuid4()
    uid = uuid4()
    # 1st response: insert returns the row (no embeds).
    # 2nd response: follow-up GET with embed.
    fake_client.queue(
        FakeResponse(data=[{"id": str(pid), "name": "P", "owner_id": str(uid)}]),
        FakeResponse(
            data=[
                {
                    "id": str(pid),
                    "name": "P",
                    "owner": {"id": str(uid), "email": "a@b.c"},
                }
            ]
        ),
    )
    p = await PetWithOwner.create(id=pid, name="P", owner_id=uid)
    assert p.owner.email == "a@b.c"
    # Two round-trips for relation models.
    assert len(fake_client.builders) == 2


async def test_bulk_create_empty_list_is_noop(fake_client):
    out = await Pet.bulk_create([])
    assert out == []
    assert fake_client.builders == []


async def test_bulk_create_flat_returns_validated_list(fake_client):
    a, b = uuid4(), uuid4()
    fake_client.queue(
        FakeResponse(
            data=[
                {"id": str(a), "name": "A", "species": "cat", "adopted": False},
                {"id": str(b), "name": "B", "species": "dog", "adopted": True},
            ]
        )
    )
    rows = await Pet.bulk_create(
        [
            {"id": a, "name": "A", "species": "cat", "adopted": False},
            {"id": b, "name": "B", "species": "dog", "adopted": True},
        ]
    )
    assert [r.name for r in rows] == ["A", "B"]
    # Payload list should be wire-serialized.
    insert_call = next(c for c in fake_client.builders[0].calls if c[0] == "insert")
    assert insert_call[1][0][0]["id"] == str(a)


async def test_bulk_create_empty_response(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    out = await Pet.bulk_create(
        [{"id": uuid4(), "name": "n", "species": "c", "adopted": True}]
    )
    assert out == []


# ─── save / update / delete / refresh ───────────────────────────────────


async def test_save_persists_dirty_fields_only(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    # Field-set is cleared after construction once we touch one attribute.
    object.__setattr__(p, "__pydantic_fields_set__", set())
    p.name = "B"

    fake_client.queue(
        FakeResponse(
            data=[{"id": str(pid), "name": "B", "species": "cat", "adopted": False}]
        )
    )
    await p.save()
    # The update payload should ONLY contain ``name``.
    update_call = next(c for c in fake_client.builders[0].calls if c[0] == "update")
    payload = update_call[1][0]
    assert payload == {"name": "B"}


async def test_save_with_no_dirty_returns_self_without_request(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    object.__setattr__(p, "__pydantic_fields_set__", set())
    out = await p.save()
    assert out is p
    assert fake_client.builders == []


async def test_save_missing_row_raises(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    p.name = "B"
    fake_client.queue(FakeResponse(data=[]))
    with pytest.raises(SupabaseORMDoesNotExist):
        await p.save()


async def test_instance_update_assigns_and_saves(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    fake_client.queue(
        FakeResponse(
            data=[{"id": str(pid), "name": "Z", "species": "cat", "adopted": True}]
        )
    )
    await p.update(name="Z", adopted=True)
    assert p.name == "Z"
    assert p.adopted is True


async def test_instance_update_rejects_no_kwargs(fake_client):
    p = Pet(id=uuid4(), name="A", species="cat", adopted=False)
    with pytest.raises(SupabaseORMUsageError, match="at least one"):
        await p.update()


async def test_instance_update_rejects_pk_change(fake_client):
    p = Pet(id=uuid4(), name="A", species="cat", adopted=False)
    with pytest.raises(SupabaseORMUsageError, match="primary key"):
        await p.update(id=uuid4())


async def test_instance_update_rejects_relation_field(fake_client):
    p = PetWithOwner(
        id=uuid4(),
        name="x",
        owner=User(id=uuid4(), email="a@b.c"),
    )
    with pytest.raises(SupabaseORMUsageError, match="relation"):
        await p.update(owner=User(id=uuid4(), email="z@b.c"))


async def test_delete_runs_eq_pk(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    fake_client.queue(FakeResponse(data=[]))
    await p.delete()
    calls = fake_client.builders[0].calls
    assert ("delete", (), {}) in calls
    eq_call = next(c for c in calls if c[0] == "eq")
    assert eq_call[1] == ("id", str(pid))


async def test_refresh_replaces_state(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    fake_client.queue(
        FakeResponse(
            data=[{"id": str(pid), "name": "Z", "species": "dog", "adopted": True}]
        )
    )
    await p.refresh()
    assert p.name == "Z"
    assert p.species == "dog"
    assert p.adopted is True
