<div align="center">

# supabase-orm

### A lightweight, Pydantic-native ORM on top of `supabase-py` — async-first, sync mirror generated.

**[Documentation](https://viperadnan-git.github.io/supabase-orm/)** · [Install](#install) · [Quick start](#quick-start) · [Sync mode](#sync-mode) · [Contributing](#contributing)

</div>

---

## Features

- **Type-safe query builder.** Every operator on `Model.query` is a real method with a real signature — autocomplete works, typos surface as `AttributeError` at call time, not as silent server-side errors.
- **Typed predicate expressions.** `Pet.f.age >= 5` builds a composable `Predicate`. Combine with `|` / `&` / `~` and pass to `.or_()` / `.not_()`.
- **Keyset iteration that scales.** `async for pet in Pet.query.eq(...).iter():` paginates by PK with constant-time-per-batch, race-safe under concurrent inserts/deletes.
- **Pydantic v2 throughout.** Your model *is* the row schema, the response schema, and the request body schema. No DTO layer.
- **Async-first, sync mirror included.** Built for `asyncio` and FastAPI; a byte-for-byte sync API lives at `supabase_orm.sync`, generated via `unasync`.
- **PostgREST embeds, declared at the type level.** Annotate a field as `Annotated[Owner, Relation(...)]` — the ORM builds the right `select=` string for you, including `!inner` / FK hints / per-relation filters.
- **Per-request RLS via `ContextVar`.** Pair `use_client()` with a JWT-authenticated client in a FastAPI middleware — zero leakage between concurrent requests.
- **Typed RPC helpers.** Call `setof` functions with row validation, get a single row, or coerce a scalar — one line each.
- **Foot-gun guards.** Unfiltered bulk `delete()` / `update()` raise unless you pass `allow_unfiltered=True`.
- **Tested both ways.** 500+ mock tests cover the wire contract; 80+ integration tests run against real Supabase.

---

## Install

```bash
uv add supabase-orm
# or
pip install supabase-orm
```

Requires Python 3.11+, `supabase-py 2.30+`, `pydantic 2.13+`.

---

## Quick start

```python
from uuid import UUID
from typing import Annotated
from supabase_orm import SupabaseModel, Relation, lifespan


class Owner(SupabaseModel, table="owners"):
    id: UUID
    email: str
    is_active: bool


class Pet(SupabaseModel, table="pets"):
    id: UUID
    name: str
    species: str
    adopted: bool
    owner: Annotated[Owner, Relation(join="inner")]


async with lifespan(SUPABASE_URL, SUPABASE_KEY):
    # Chain-style query (sequential AND)
    cats = await Pet.query.eq("species", "cat").order_by("-created_at").limit(10).all()

    # Typed predicates (OR / NOT / boolean composition)
    rescues = await Pet.query.or_(
        Pet.f.species == "cat",
        (Pet.f.species == "dog") & (Pet.f.adopted == False),
    ).all()

    # Writes
    p = await Pet.create(name="Whiskers", species="cat", adopted=False)
    p.name = "Mr. Whiskers"
    await p.save()

    # Stream every matching row, any table size
    async for pet in Pet.query.eq("adopted", False).iter():
        await process(pet)

    # Bulk update / delete (guards block unfiltered ops)
    await Pet.query.eq("adopted", False).update(adopted=True)
```

Full guide: **[viperadnan-git.github.io/supabase-orm](https://viperadnan-git.github.io/supabase-orm/)** — models, predicates, embeds, lifecycle, RPC, extending.

---

## Sync mode

Same model classes, same chain syntax, same predicates. Switch the import and drop `await` / `async`:

```python
from supabase import create_client
from supabase_orm.sync import SupabaseModel, init, shutdown

class Pet(SupabaseModel, table="pets"):
    id: UUID
    name: str
    species: str

init(create_client(SUPABASE_URL, SUPABASE_KEY))

cats = Pet.query.eq("species", "cat").limit(10).all()
for p in Pet.query.eq("species", "cat").iter():
    process(p)

shutdown()  # optional — process exit drains pools anyway
```

The sync tree is generated from the async source — no second implementation to keep in sync.

---

## Contributing

```bash
git clone https://github.com/viperadnan-git/supabase-orm
cd supabase-orm
uv sync --all-groups
uv run pytest                # mock suite (always runs)
```

### Architecture

- `src/supabase_orm/_async/` is the canonical implementation.
- `src/supabase_orm/_sync/` is **generated** by `scripts/gen_sync.py` (`unasync`-based token rewrite + prose regex + skip-block directive).
- Tests mirror the same layout: `tests/_async/` is the source, `tests/_sync/` is generated.
- A pre-commit hook (`nizm`) auto-regenerates and stages the sync mirror whenever `_async/**/*.py` changes. CI also runs `python scripts/gen_sync.py --check` to fail on drift.

#### Skip-block directive

Wrap async-only test code (e.g. concurrency tests using `asyncio.gather`) so the sync mirror omits it:

```python
# gen_sync: skip-block
async def test_async_only():
    ...
# gen_sync: end-skip
```

### Running tests

```bash
uv run pytest                      # mock only (default)
uv run pytest -m integration       # live Supabase
```

Integration tests need a Supabase project with the test schema. See [`tests/integration/README.md`](https://github.com/viperadnan-git/supabase-orm/blob/main/tests/integration/README.md).

### Building docs locally

```bash
uv sync --group docs
uv run mkdocs serve   # http://localhost:8000
```

---

## License

Apache License 2.0 — see [LICENSE](https://github.com/viperadnan-git/supabase-orm/blob/main/LICENSE).
