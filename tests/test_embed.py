"""build_select / collect_relations / Relation metadata."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import pytest

from supabase_orm import Relation, SupabaseModel
from supabase_orm._embed import build_select, collect_relations


def test_flat_model_select_is_csv_of_fields():
    class Pet(SupabaseModel, table="pets_flat"):
        id: UUID
        name: str
        species: str

    assert Pet.__select__ == "id,name,species"
    assert Pet.__relations__ == {}


def test_simple_relation_is_embedded():
    class Owner(SupabaseModel, table="owners_a"):
        id: UUID
        email: str

    class Pet(SupabaseModel, table="pets_a"):
        id: UUID
        owner: Owner

    # field name differs from table → prefix with ``owner:``
    assert Pet.__select__ == "id,owner:owners_a(id,email)"
    assert "owner" in Pet.__relations__
    cls, is_list, rel = Pet.__relations__["owner"]
    assert cls is Owner
    assert is_list is False
    assert rel.join == "left"


def test_relation_field_name_matches_table_no_prefix():
    class Owners_b(SupabaseModel, table="owners_b"):
        id: UUID

    class Pet(SupabaseModel, table="pets_b"):
        id: UUID
        owners_b: Owners_b

    assert "owners_b(id)" in Pet.__select__
    assert "owners_b:owners_b" not in Pet.__select__


def test_inner_join_appends_bang_inner():
    class Owner(SupabaseModel, table="owners_c"):
        id: UUID

    class Pet(SupabaseModel, table="pets_c"):
        id: UUID
        owner: Annotated[Owner, Relation(join="inner")]

    assert "owners_c!inner(id)" in Pet.__select__


def test_fk_hint_inserts_bang_fk():
    class Owner(SupabaseModel, table="owners_d"):
        id: UUID

    class Pet(SupabaseModel, table="pets_d"):
        id: UUID
        owner: Annotated[Owner, Relation(fk="pets_owner_fk")]

    assert "owners_d!pets_owner_fk(id)" in Pet.__select__


def test_list_relation_recognized():
    class Tag(SupabaseModel, table="tags_a"):
        id: UUID
        name: str

    class Post(SupabaseModel, table="posts_a"):
        id: UUID
        tags: list[Tag]

    _, is_list, _ = Post.__relations__["tags"]
    assert is_list is True
    assert "tags:tags_a(id,name)" in Post.__select__


def test_optional_relation_unwrapped():
    class Owner(SupabaseModel, table="owners_e"):
        id: UUID

    class Pet(SupabaseModel, table="pets_e"):
        id: UUID
        owner: Owner | None = None

    assert "owner" in Pet.__relations__


def test_select_override_takes_precedence():
    class Pet(SupabaseModel, table="pets_f", select="id,name"):
        id: UUID
        name: str
        species: str

    assert Pet.__select__ == "id,name"


def test_relation_cycle_detected():
    # Use plain Pydantic models that point at SupabaseModel subclasses but
    # form a cycle, then call build_select directly to trigger detection.
    class A(SupabaseModel, table="cycle_a_x"):
        id: UUID

    # Manually inject a self-reference into A's relations metadata to force
    # build_select to recurse into itself.
    A.__pydantic_fields__ = A.__pydantic_fields__  # noqa: keep refs alive
    with pytest.raises(ValueError, match="cycle"):
        build_select(A, _seen=frozenset({A}))


def test_collect_relations_skips_scalars():
    class Owner(SupabaseModel, table="owners_g"):
        id: UUID

    class Pet(SupabaseModel, table="pets_g"):
        id: UUID
        name: str
        owner: Owner

    rels = collect_relations(Pet)
    assert set(rels.keys()) == {"owner"}


def test_relation_dataclass_defaults():
    r = Relation()
    assert r.join == "left"
    assert r.fk is None
    assert r.through is None
    assert r.filter is None
