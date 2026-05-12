# DO NOT EDIT — generated from tests/_async/test_base.py by scripts/gen_sync.py.
# Run `python scripts/gen_sync.py` (or rebuild the package) to regenerate.

"""SupabaseModel behavior — subclass setup, get/find/create/save/update/delete."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

import pytest

from supabase_orm._sync import (
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


def test_get_returns_validated_row(fake_client):
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
    p = Pet.get(pid)
    assert isinstance(p, Pet)
    assert p.id == pid
    assert p.name == "Whiskers"


def test_get_missing_raises(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    with pytest.raises(SupabaseORMDoesNotExist):
        Pet.get(uuid4())


def test_find_returns_none_on_miss(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    assert Pet.find(uuid4()) is None


def test_find_returns_row_on_hit(fake_client):
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
    p = Pet.find(pid)
    assert p is not None and p.id == pid


# ─── create / bulk_create ────────────────────────────────────────────────


def test_create_flat_uses_insert_response_directly(fake_client):
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
    p = Pet.create(id=pid, name="Whiskers", species="cat", adopted=False)
    assert isinstance(p, Pet) and p.id == pid

    # Insert payload should have UUID stringified.
    builder = fake_client.builders[0]
    insert_call = next(c for c in builder.calls if c[0] == "insert")
    payload = insert_call[1][0]
    assert payload["id"] == str(pid)
    assert payload["name"] == "Whiskers"


def test_create_returns_no_rows_raises(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    with pytest.raises(ValueError, match="returned no rows"):
        Pet.create(id=uuid4(), name="x", species="cat", adopted=False)


def test_create_with_relations_does_followup_get(fake_client):
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
    p = PetWithOwner.create(id=pid, name="P", owner_id=uid)
    assert p.owner.email == "a@b.c"
    # Two round-trips for relation models.
    assert len(fake_client.builders) == 2


def test_bulk_create_empty_list_is_noop(fake_client):
    out = Pet.bulk_create([])
    assert out == []
    assert fake_client.builders == []


def test_bulk_create_flat_returns_validated_list(fake_client):
    a, b = uuid4(), uuid4()
    fake_client.queue(
        FakeResponse(
            data=[
                {"id": str(a), "name": "A", "species": "cat", "adopted": False},
                {"id": str(b), "name": "B", "species": "dog", "adopted": True},
            ]
        )
    )
    rows = Pet.bulk_create(
        [
            {"id": a, "name": "A", "species": "cat", "adopted": False},
            {"id": b, "name": "B", "species": "dog", "adopted": True},
        ]
    )
    assert [r.name for r in rows] == ["A", "B"]
    # Payload list should be wire-serialized.
    insert_call = next(c for c in fake_client.builders[0].calls if c[0] == "insert")
    assert insert_call[1][0][0]["id"] == str(a)


def test_bulk_create_empty_response(fake_client):
    fake_client.queue(FakeResponse(data=[]))
    out = Pet.bulk_create(
        [{"id": uuid4(), "name": "n", "species": "c", "adopted": True}]
    )
    assert out == []


# ─── save / update / delete / refresh ───────────────────────────────────


def test_save_persists_dirty_fields_only(fake_client):
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
    p.save()
    # The update payload should ONLY contain ``name``.
    update_call = next(c for c in fake_client.builders[0].calls if c[0] == "update")
    payload = update_call[1][0]
    assert payload == {"name": "B"}


def test_save_with_no_dirty_returns_self_without_request(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    object.__setattr__(p, "__pydantic_fields_set__", set())
    out = p.save()
    assert out is p
    assert fake_client.builders == []


def test_save_missing_row_raises(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    p.name = "B"
    fake_client.queue(FakeResponse(data=[]))
    with pytest.raises(SupabaseORMDoesNotExist):
        p.save()


def test_instance_update_assigns_and_saves(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    fake_client.queue(
        FakeResponse(
            data=[{"id": str(pid), "name": "Z", "species": "cat", "adopted": True}]
        )
    )
    p.update(name="Z", adopted=True)
    assert p.name == "Z"
    assert p.adopted is True


def test_instance_update_rejects_no_kwargs(fake_client):
    p = Pet(id=uuid4(), name="A", species="cat", adopted=False)
    with pytest.raises(SupabaseORMUsageError, match="at least one"):
        p.update()


def test_instance_update_rejects_pk_change(fake_client):
    p = Pet(id=uuid4(), name="A", species="cat", adopted=False)
    with pytest.raises(SupabaseORMUsageError, match="primary key"):
        p.update(id=uuid4())


def test_instance_update_rejects_relation_field(fake_client):
    p = PetWithOwner(
        id=uuid4(),
        name="x",
        owner=User(id=uuid4(), email="a@b.c"),
    )
    with pytest.raises(SupabaseORMUsageError, match="relation"):
        p.update(owner=User(id=uuid4(), email="z@b.c"))


def test_delete_runs_eq_pk(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    fake_client.queue(FakeResponse(data=[]))
    p.delete()
    calls = fake_client.builders[0].calls
    assert ("delete", (), {}) in calls
    eq_call = next(c for c in calls if c[0] == "eq")
    assert eq_call[1] == ("id", str(pid))


def test_refresh_replaces_state(fake_client):
    pid = uuid4()
    p = Pet(id=pid, name="A", species="cat", adopted=False)
    fake_client.queue(
        FakeResponse(
            data=[{"id": str(pid), "name": "Z", "species": "dog", "adopted": True}]
        )
    )
    p.refresh()
    assert p.name == "Z"
    assert p.species == "dog"
    assert p.adopted is True


# ─── Custom query_class hook ─────────────────────────────────────────────


def test_default_query_class_is_querybuilder():
    from supabase_orm._sync import QueryBuilder

    class M(SupabaseModel, table="qc_default"):
        id: int

    assert M.__query_class__ is QueryBuilder


def test_per_model_query_class_kwarg(fake_client):
    from supabase_orm._sync import QueryBuilder

    from .conftest import FakeResponse

    class PaginatedQB(QueryBuilder):
        def paginate(self, *, page: int, per_page: int):
            return self.range(page * per_page, (page + 1) * per_page - 1).all()

    class M(SupabaseModel, table="qc_inline", query_class=PaginatedQB):
        id: int

    assert M.__query_class__ is PaginatedQB
    assert isinstance(M.query, PaginatedQB)

    fake_client.queue(FakeResponse(data=[{"id": 1}]))
    rows = M.query.eq("id", 1).paginate(page=0, per_page=10)
    assert rows[0].id == 1


def test_query_class_inherited_via_base_class():
    """The MRO-inheritance pattern: define a base model with __query_class__
    set, every subclass picks it up without specifying ``query_class=``."""
    from supabase_orm._sync import QueryBuilder

    class _AppQB(QueryBuilder):
        marker = "app-qb"

    class _AppModel(SupabaseModel):
        __query_class__ = _AppQB

    class A(_AppModel, table="qc_inh_a"):
        id: int

    class B(_AppModel, table="qc_inh_b"):
        id: int

    assert A.__query_class__ is _AppQB
    assert B.__query_class__ is _AppQB
    assert isinstance(A.query, _AppQB)
    assert A.query.marker == "app-qb"


def test_per_model_kwarg_overrides_inherited():
    """An inline ``query_class=`` on a child overrides the base's choice."""
    from supabase_orm._sync import QueryBuilder

    class BaseQB(QueryBuilder):
        marker = "base"

    class OverrideQB(QueryBuilder):
        marker = "override"

    class _Base(SupabaseModel):
        __query_class__ = BaseQB

    class A(_Base, table="qc_ovr_a"):
        id: int

    class B(_Base, table="qc_ovr_b", query_class=OverrideQB):
        id: int

    assert A.__query_class__ is BaseQB
    assert B.__query_class__ is OverrideQB
