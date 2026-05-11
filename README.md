<div align="center">

# supabase-orm

### A lightweight, async, Pydantic-native ORM on top of `supabase-py`.

[Features](#features) · [Install](#install) · [Quick start](#quick-start) · [Models](#defining-models) · [Querying](#querying) · [Writes](#writes) · [RPC](#rpc) · [FastAPI](#fastapi-integration) · [Extending](#extending)

</div>

---

## Features

- **Type-safe query builder.** Every operator on `Model.query` is a real method with a real signature — autocomplete works, typos surface as `AttributeError` at call time, not as silent server-side errors.

- **Pydantic v2 throughout.** Your model *is* the row schema, the response schema, and the request body schema. No DTO layer.

- **Async-first.** Built for `asyncio` and FastAPI — every terminal call is `await`-able, every chain is a fresh builder.

- **PostgREST embeds, declared at the type level.** Mark a field as `Annotated[Owner, Relation(...)]` and the ORM builds the right `select=` string for you, including `!inner` / FK hints / per-relation filters.

- **Per-request RLS via `ContextVar`.** Attach a JWT in a FastAPI middleware and Postgres row-level security sees the user. No client-per-request overhead, no leakage between concurrent requests.

- **Typed RPC helpers.** Call `setof` functions with row validation, get a single row, or coerce a scalar — all with one line.

- **Opt-in foot-gun guards.** Unfiltered bulk `delete()` / `update()` raise unless you pass `allow_unfiltered=True`.

- **Tested both ways.** 166 mock tests cover the wire contract (every operator, every serializer, every shorthand). 34 integration tests run against a real Supabase project to confirm PostgREST actually interprets those calls the way we expect.

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


class PetWithOwner(SupabaseModel, table="pets"):
    id: UUID
    name: str
    species: str
    owner: Annotated[Owner, Relation(join="inner")]


async with lifespan(SUPABASE_URL, SUPABASE_KEY):
    # Read
    cats = await Pet.query.eq("species", "cat").order_by("-created_at").limit(10).all()
    one = await PetWithOwner.get(some_id)

    # Write
    p = await Pet.create(name="Whiskers", species="cat", adopted=False)
    p.name = "Mr. Whiskers"
    await p.save()

    # Bulk
    await Pet.query.eq("adopted", False).update(adopted=True)
    await Pet.query.eq("species", "fish").lt("created_at", cutoff).delete()
```

---

## Defining models

A model is a Pydantic `BaseModel` subclass plus one class kwarg:

```python
class Pet(SupabaseModel, table="pets"):
    id: UUID
    name: str
    species: str
    adopted: bool
```

### Class kwargs

| Kwarg    | Default | What it does                                                    |
|----------|---------|-----------------------------------------------------------------|
| `table`  | —       | PostgREST table or view name. **Required.**                     |
| `pk`     | `"id"`  | Primary-key field name. Used by `get()`, `save()`, `delete()`.  |
| `select` | auto    | Override the auto-derived `select=` string. Escape hatch only.  |

### Relations

A field annotated with another `SupabaseModel` becomes a PostgREST embed:

```python
class PetWithOwner(SupabaseModel, table="pets"):
    id: UUID
    name: str
    owner: Annotated[Owner, Relation(join="inner")]   # → owners!inner(id,email)
    tags:  list[Tag]                                  # → tags(id,name)  (left join, list)
```

`Relation(...)` is optional metadata:

| Field     | Purpose                                                         |
|-----------|-----------------------------------------------------------------|
| `join`    | `"left"` (default) or `"inner"` — appended as `!inner`.         |
| `fk`      | Foreign-key constraint name for disambiguation.                 |
| `through` | Junction-table hint when PostgREST can't auto-resolve.          |
| `filter`  | Per-relation filter dict, e.g. `{"is_deleted": False}`. Supports operator suffixes: `{"views__gte": 100}`. |

### Lean projections

Two models can point at the same table for full-detail vs. trimmed views:

```python
class Pet(SupabaseModel, table="pets"):
    id: UUID
    name: str
    species: str
    created_at: datetime

class PetMini(SupabaseModel, table="pets"):
    id: UUID
    name: str

# Build the full query, then rebind:
mini_rows = await Pet.query.eq("adopted", False).as_(PetMini).all()
# → list[PetMini]
```

---

## Querying

### Terminals

| Method                | Returns                | Behavior                                                                |
|-----------------------|------------------------|-------------------------------------------------------------------------|
| `.all()`              | `list[T]`              | Every matching row.                                                     |
| `.first()`            | `T \| None`            | The first row or `None`. Adds `limit(1)`.                               |
| `.one()`              | `T`                    | Exactly one row. Raises if 0 or >1.                                     |
| `.maybe_one()`        | `T \| None`            | At most one row. Raises if >1.                                          |
| `.count()`            | `int`                  | Head-only request with `count="exact"`.                                 |
| `.all_with_count()`   | `tuple[list[T], int]`  | Rows + filtered total in one round-trip (for paginated endpoints).      |
| `.values(*cols)`      | `list[dict]`           | Ad-hoc projection, raw dicts, no Pydantic validation.                   |
| `.raw()`              | postgrest builder      | Escape hatch.                                                           |

### Filter operators

Every operator below works as a method on `Model.query` **and** inside `or_()` / `not_()` predicate lambdas:

```python
Pet.query.eq("species", "cat")
Pet.query.neq("species", "dog")
Pet.query.gt("age", 3).lte("age", 10)
Pet.query.like("name", "Mr%").ilike("name", "mr%")
Pet.query.in_("species", ["cat", "dog"])
Pet.query.is_("adopted", None)                  # IS NULL / IS TRUE / IS FALSE
Pet.query.contains("tags", ["indoor"])
Pet.query.contained_by("tags", ["indoor", "outdoor"])
Pet.query.overlaps("tags", ["indoor"])
Pet.query.fts("description", "fluffy")          # plus plfts / phfts / wfts
```

### Compound predicates

```python
# OR across branches:
await Pet.query.or_(
    lambda q: q.eq("species", "cat"),
    lambda q: q.eq("species", "dog").gte("age", 5),
).all()

# NOT:
await Pet.query.not_(lambda q: q.eq("adopted", True)).all()
```

### `match()` — multi-column equality

```python
await Pet.query.match({"species": "cat", "adopted": False}).all()
```

PostgREST's `match` is multi-column by design and has no predicate-string form, so it isn't usable inside `or_()` / `not_()`.

### Ordering & pagination

```python
await Pet.query.order_by("-created_at", "name").limit(20).offset(40).all()
await Pet.query.range(0, 9).all()       # PostgREST-style inclusive range
```

### Pagination with total

```python
rows, total = await Pet.query.eq("species", "cat").limit(20).all_with_count()
```

One round-trip. The count is computed on the filtered set before `limit`/`offset` is applied.

### Type-checked column names

Typos surface immediately:

```python
Pet.query.eq("speceis", "cat")
# AttributeError: Pet has no column 'speceis'. Known: ['adopted', 'id', 'name', 'species']
```

---

## Writes

### Insert

```python
p = await Pet.create(name="Whiskers", species="cat", adopted=False)
many = await Pet.bulk_create([
    {"name": "A", "species": "cat", "adopted": False},
    {"name": "B", "species": "dog", "adopted": True},
])
```

### Update

Three forms — pick the one that reads best at the call site:

```python
# 1. Mutate then save (Pydantic validates each assignment):
p.name = "Mr. Whiskers"
await p.save()

# 2. One-liner with multiple fields:
await p.update(name="Mr. Whiskers", adopted=True)

# 3. Bulk update:
await Pet.query.eq("adopted", False).update(adopted=True)
```

### Delete

```python
await p.delete()                                        # single row
await Pet.query.lt("created_at", cutoff).delete()       # bulk, filtered
await Pet.query.delete(allow_unfiltered=True)           # wipe table (explicit)
```

Unfiltered bulk `delete()` / `update()` raise `SupabaseORMUsageError` unless you opt in — PostgREST also rejects unfiltered DELETE server-side.

### Serialization

Every write path serializes non-JSON-native values automatically. Built-in coercion:

| Type        | Wire form         |
|-------------|-------------------|
| `UUID`      | `str(u)`          |
| `datetime`  | `.isoformat()`    |
| `date`      | `.isoformat()`    |
| `Decimal`   | `str(d)`          |
| `Enum`      | `.value`          |
| `BaseModel` | `.model_dump(mode="json")` |

Register your own:

```python
from supabase_orm import register_serializer

register_serializer(Money, lambda v: v.cents)
```

---

## RPC

```python
from supabase_orm import rpc, rpc_one, rpc_maybe_one, rpc_scalar

# setof:
stats = await rpc("get_pet_stats", PetStats, p_owner_id=owner_id)

# Single row variants:
summary  = await rpc_one("get_owner_summary", OwnerSummary, p_owner_id=owner_id)
maybe    = await rpc_maybe_one("find_active_owner", Owner, p_email=email)

# Scalar:
n = await rpc_scalar("count_adopted_pets", int)
```

Keyword arguments map directly to the SQL function's parameter names — PostgREST passes them through verbatim, so the names must match the function signature.

---

## FastAPI integration

### Lifespan

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from supabase_orm import lifespan as orm_lifespan

@asynccontextmanager
async def lifespan(app):
    async with orm_lifespan(SUPABASE_URL, SUPABASE_KEY):
        yield

app = FastAPI(lifespan=lifespan)
```

### Per-request RLS via JWT

The client is stored in a `ContextVar`, so each FastAPI request runs in its own copied context — `set_auth()` mutations are isolated to that request, even under concurrent load.

```python
from supabase_orm import set_auth

@app.middleware("http")
async def attach_jwt(request, call_next):
    if (auth := request.headers.get("authorization")):
        set_auth(auth.removeprefix("Bearer "))
    try:
        return await call_next(request)
    finally:
        set_auth(None)   # back to the anon/service-role key from lifespan
```

Inside a handler, just call the ORM as usual — Postgres RLS sees the user:

```python
@app.get("/me/pets", response_model=list[Pet])
async def my_pets():
    return await Pet.query.order_by("-created_at").all()
```

### Per-request override with a dedicated client

For background tasks, scripts, or any place outside the request lifecycle:

```python
from supabase_orm import use_client

async with use_client(some_other_client):
    rows = await Pet.query.eq("species", "cat").all()
```

`use_client()` restores the previous binding on exit, including on exceptions.

---

## Extending

### Custom filter operators

```python
from supabase_orm import register_op

@register_op("starts_with")
def _starts_with(builder, col, val):
    return builder.like(col, f"{val}%")

# Now usable everywhere — but for typed access, add the method to
# QueryBuilder yourself (the registry handles the wire side).
await Pet.query._apply_op("starts_with", "name", "Mr")
```

### Custom serializers

```python
from supabase_orm import register_serializer

class Money:
    def __init__(self, cents: int): self.cents = cents

register_serializer(Money, lambda v: v.cents)
```

---

## Error handling

All exceptions inherit from `SupabaseORMError`:

```python
from supabase_orm import (
    SupabaseORMError,
    SupabaseORMDoesNotExist,
    SupabaseORMMultipleObjectsReturned,
    SupabaseORMUsageError,
)
```

| Exception                            | Raised when                                                          |
|--------------------------------------|----------------------------------------------------------------------|
| `SupabaseORMDoesNotExist`            | `.get()` / `.one()` matched zero rows; `save()` row vanished.        |
| `SupabaseORMMultipleObjectsReturned` | `.one()` / `.maybe_one()` matched more than one row.                 |
| `SupabaseORMUsageError`              | Setup or runtime misuse — see below.                                 |

`SupabaseORMUsageError` covers:

- Client not initialized when an ORM call is made.
- Model declared without `table=`.
- Unfiltered bulk `delete()` / `update()` without `allow_unfiltered=True`.
- `as_()` to a model on a different table.
- `instance.update()` trying to change the primary key or a relation field.
- `set_auth(None)` with no recorded default key.

Map them to HTTP responses in one place:

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(SupabaseORMDoesNotExist)
async def not_found(request: Request, exc: SupabaseORMDoesNotExist):
    return JSONResponse({"detail": str(exc)}, status_code=404)
```

---

## Testing

```bash
uv run pytest                       # mock + integration (if .env is set)
uv run pytest -m "not integration"  # mock only — fast, no network
uv run pytest -m integration        # integration only
```

The integration suite needs a Supabase project with the test schema applied. See [`tests/integration/README.md`](tests/integration/README.md).

---

## Contributing

Issues and PRs welcome at [github.com/viperadnan/supabase-orm](https://github.com/viperadnan/supabase-orm). Run the test suite before sending a PR:

```bash
uv run pytest                       # mock suite (fast, no network)
uv run pytest -m integration        # integration (needs .env)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
