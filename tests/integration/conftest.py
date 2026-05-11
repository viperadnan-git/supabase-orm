"""Integration fixtures.

The whole package is skipped at collection time when the env vars aren't
set, so importing supabase or attempting a connection never happens on a
default `pytest` run.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, AsyncIterator
from uuid import UUID

import pytest
from dotenv import load_dotenv

from supabase_orm import Relation, SupabaseModel, lifespan

# Load .env from the repo root if present. Existing env vars win — CI
# secrets are not overridden by a local .env file.
_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _DOTENV_PATH.exists():
    load_dotenv(_DOTENV_PATH, override=False)

URL = os.environ.get("SUPABASE_TEST_URL")
KEY = os.environ.get("SUPABASE_TEST_KEY")


def pytest_collection_modifyitems(config, items):
    """Tag every test in this directory with @integration, and skip the
    whole suite when creds are missing.

    Tagging in a hook (rather than per-file ``pytestmark``) keeps the test
    files free of boilerplate. Skipping (vs. erroring) means a developer
    running plain ``pytest`` without the env vars gets a clean skip.
    """
    integration = pytest.mark.integration
    skip = pytest.mark.skip(reason="SUPABASE_TEST_URL / SUPABASE_TEST_KEY not set")
    here = str(config.rootpath / "tests" / "integration")
    for item in items:
        if str(item.path).startswith(here):
            item.add_marker(integration)
            if not (URL and KEY):
                item.add_marker(skip)


# ─── Models pointing at the integration schema ───────────────────────────


class Owner(SupabaseModel, table="orm_test_owners"):
    id: UUID
    email: str
    is_active: bool


class Pet(SupabaseModel, table="orm_test_pets"):
    id: UUID
    owner_id: UUID | None
    name: str
    species: str
    adopted: bool
    tags: list[str]
    amount: float
    due: str | None  # keep as str — PostgREST returns ISO date


class PetWithOwnerLeft(SupabaseModel, table="orm_test_pets"):
    id: UUID
    name: str
    species: str
    owner: Annotated[Owner | None, Relation()] = None


class PetWithOwnerInner(SupabaseModel, table="orm_test_pets"):
    id: UUID
    name: str
    species: str
    owner: Annotated[Owner, Relation(join="inner")]


# ─── Client + cleanup ────────────────────────────────────────────────────


@pytest.fixture(scope="session")
async def _live_client() -> AsyncIterator[None]:
    """Open one AsyncClient for the whole test session."""
    assert URL and KEY  # guarded by pytest_collection_modifyitems
    async with lifespan(URL, KEY):
        yield


_IMPOSSIBLE_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
async def clean(_live_client) -> AsyncIterator[None]:
    """Truncate the test tables before each test.

    Pets are deleted first (FK → owners). Supabase/PostgREST rejects bare
    DELETE server-side ("DELETE requires a WHERE clause"), so we attach a
    tautological ``neq(id, <impossible-uuid>)`` filter — matches every row
    without tripping that guard.
    """
    await Pet.query.neq("id", _IMPOSSIBLE_UUID).delete()
    await Owner.query.neq("id", _IMPOSSIBLE_UUID).delete()
    yield
