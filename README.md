<div align="center">

# supabase-orm

### A lightweight, Pydantic-native ORM on top of `supabase-py` — async-first, sync mirror generated.

[Features](#features) · [Install](#install) · [Quick start](#quick-start) · [Models](#defining-models) · [Querying](#querying) · [Writes](#writes) · [RPC](#rpc) · [Lifecycle](#client-lifecycle) · [Extending](#extending)

</div>

---

## Features

- **Type-safe query builder.** Every operator on `Model.query` is a real method with a real signature — autocomplete works, typos surface as `AttributeError` at call time, not as silent server-side errors.

- **Typed predicate expressions.** `Pet.f.age >= 5` builds a composable `Predicate`. Combine with `|` / `&` / `~` and pass to `.or_()` / `.not_()`. Reads as boolean logic, type-checks as expressions.

- **Keyset iteration that scales.** `async for pet in Pet.query.eq(...).iter():` paginates by PK with constant-time-per-batch and no offset cliff. Works on tables of any size; race-safe under concurrent inserts and deletes.

- **Pydantic v2 throughout.** Your model *is* the row schema, the response schema, and the request body schema. No DTO layer.

- **Async-first, sync mirror included.** Built for `asyncio` and FastAPI. A byte-for-byte sync API lives at `supabase_orm.sync`, generated from the same source via `unasync` — identical surface for cron jobs, Celery workers, and scripts where running an event loop is overkill.

- **PostgREST embeds, declared at the type level.** Mark a field as `Annotated[Owner, Relation(...)]` and the ORM builds the right `select=` string for you, including `!inner` / FK hints / per-relation filters.

- **Per-request RLS via `ContextVar`.** Pair `use_client()` with a JWT-authenticated client in a FastAPI middleware — Postgres row-level security sees the user, with zero leakage between concurrent requests.

- **Typed RPC helpers.** Call `setof` functions with row validation, get a single row, or coerce a scalar — all with one line.

- **Opt-in foot-gun guards.** Unfiltered bulk `delete()` / `update()` raise unless you pass `allow_unfiltered=True`.

- **Tested both ways.** 440+ mock tests (async + sync trees) cover the wire contract — every operator, every serializer, every shorthand, predicate composition, keyset iteration. 60+ integration tests run against a real Supabase project to confirm PostgREST actually interprets those calls the way we expect.

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
    # Read — chain style for sequential AND
    cats = await Pet.query.eq("species", "cat").order_by("-created_at").limit(10).all()
    one = await PetWithOwner.get(some_id)

    # Read — typed predicates for OR / NOT / nested boolean logic
    rescues = await Pet.query.or_(
        Pet.f.species == "cat",
        (Pet.f.species == "dog") & (Pet.f.adopted == False),
    ).all()

    # Write
    p = await Pet.create(name="Whiskers", species="cat", adopted=False)
    p.name = "Mr. Whiskers"
    await p.save()

    # Bulk
    await Pet.query.eq("adopted", False).update(adopted=True)
    await Pet.query.eq("species", "fish").lt("created_at", cutoff).delete()
```

### Sync mode

Same model classes, same chain syntax, same predicates. Switch the import and drop `await` / `async`:

```python
from supabase_orm.sync import SupabaseModel, init, shutdown

class Pet(SupabaseModel, table="pets"):
    id: UUID
    name: str
    species: str

from supabase import create_client
init(create_client(SUPABASE_URL, SUPABASE_KEY))

cats = Pet.query.eq("species", "cat").limit(10).all()
for p in Pet.query.eq("species", "cat").iter():
    process(p)

shutdown()                                          # optional — process exit drains pools anyway
```

The sync tree is generated from the async source — no second implementation to keep in sync. See [Client lifecycle](#client-lifecycle) for the four entry points (`lifespan`, `init`, `set_client`, `use_client`) and when each fits.

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

| Kwarg         | Default          | What it does                                                                |
|---------------|------------------|-----------------------------------------------------------------------------|
| `table`       | —                | PostgREST table or view name. **Required.**                                 |
| `pk`          | `"id"`           | Primary-key field name. Used by `get()`, `save()`, `delete()`, `iter()`.    |
| `select`      | auto             | Override the auto-derived `select=` string. Escape hatch only.              |
| `query_class` | `QueryBuilder`   | Custom `QueryBuilder` subclass for `.query`. MRO-inherited via base models. |

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

Two models on the same table — full-detail vs. trimmed view. Just query the lean one directly when its fields are enough:

```python
class Pet(SupabaseModel, table="pets"):
    id: UUID
    name: str
    species: str
    bio: str           # heavy column you don't always need
    created_at: datetime

class PetMini(SupabaseModel, table="pets"):
    id: UUID
    name: str

# Half the wire bytes, fewer Pydantic fields to validate:
await PetMini.query.eq("species", "cat").all()
```

For huge result sets, pair with `.iter()` so the lean projection runs per batch:

```python
async for mini in PetMini.query.iter(batch_size=5000):
    process(mini)
```

### `.as_(target)` — rebind the response shape

Use `.as_()` when you need to **filter on source columns the lean model doesn't expose**, or to switch the response shape conditionally without rebuilding the chain. Two modes:

**Same-table SupabaseModel** — narrows the wire `select` AND validates against the target:

```python
# Wire: ?select=id,name  →  list[PetMini]
await Pet.query.eq("adopted", False).as_(PetMini).all()
```

**Plain Pydantic BaseModel** — validation only, wire `select` unchanged. The chain keeps using the source model's columns and predicates:

```python
from pydantic import BaseModel

class PetCard(BaseModel):
    id: UUID
    name: str

# Filter on `bio` (only on Pet) but validate as PetCard:
await Pet.query.fts("bio", "fluffy").as_(PetCard).all()
# → list[PetCard], wire still selects all of Pet's columns
```

If a same-table SupabaseModel target works, prefer it — you get the wire-narrowing optimization. Reach for the plain BaseModel form only when the lean schema doesn't have all the columns you need to filter on.

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
| `.iter(batch_size=)`  | `AsyncIterator[T]`     | Stream every matching row via PK keyset pagination. Scales to any size. |
| `.values(*cols)`      | `list[dict]`           | Ad-hoc projection, raw dicts, no Pydantic validation.                   |
| `.raw()`              | postgrest builder      | Escape hatch.                                                           |

### Filter operators

Every operator below works as a method on `Model.query` (chain style) and as a method/operator on `Model.f.<column>` (predicate style):

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

### Typed predicates (`Pet.f`)

For OR / NOT / nested boolean logic, use the `Model.f` namespace. Every column is a typed `Column[T]` with operator overloads — `==`, `!=`, `<`, `<=`, `>`, `>=` build atomic predicates, and `|` / `&` / `~` compose them.

```python
from supabase_orm import SupabaseModel

class Pet(SupabaseModel, table="pets"):
    id: UUID
    name: str
    species: str
    age: int
    adopted: bool
    tags: list[str]

# Atomic predicates — what `==`, `>=` etc. return:
Pet.f.species == "cat"            # column.eq.value
Pet.f.age >= 5
Pet.f.name.like("Mr%")
Pet.f.tags.contains(["indoor"])
Pet.f.owner_id.is_null()
```

Compose with boolean operators:

```python
# OR
await Pet.query.or_(
    Pet.f.species == "cat",
    Pet.f.species == "dog",
).all()

# OR with AND inside a branch
await Pet.query.or_(
    Pet.f.species == "cat",
    (Pet.f.species == "dog") & (Pet.f.age >= 5),
).all()

# NOT — negates any predicate, atomic or compound
await Pet.query.not_(Pet.f.adopted == True).all()
await Pet.query.not_((Pet.f.species == "cat") | (Pet.f.species == "dog")).all()
```

The chain and predicates compose freely — chain handles sequential AND, predicates handle boolean logic:

```python
await (
    Pet.query.eq("owner_id", uid)                       # chain: AND
    .or_(Pet.f.species == "cat", Pet.f.species == "dog") # predicate: OR
    .order_by("-created_at")
    .limit(20)
    .all()
)
```

#### Foot-gun guards

```python
if Pet.f.age >= 5:           # TypeError: Predicate is not a bool
    ...
```

A predicate is an expression that builds a query — it has no truth value at the call site. The runtime rejects `bool(predicate)` loudly so `if Pet.f.adopted == True:` mistakes fail at the first hit instead of always being truthy.

#### Lambda form

```python
await Pet.query.or_(
    lambda q: q.eq("species", "cat"),
    lambda q: q.eq("species", "dog").gte("age", 5),
).all()
```

Prefer the `Pet.f` form — it composes, reads as boolean logic, and gives operator-level type safety.

### `match()` — multi-column equality

```python
await Pet.query.match({"species": "cat", "adopted": False}).all()
```

`match` is a `postgrest-py` convenience — it just expands to multiple `eq` filters on the wire, equivalent to chaining `.eq()` per pair or composing `(Pet.f.a == 1) & (Pet.f.b == 2)`. Use whichever reads best.

### Ordering & pagination

`order_by()` accepts strings (`"-col"` for descending) or typed `Pet.f.<col>.asc()` / `.desc()`. The typed form unlocks `nulls="first"` / `"last"` and gets autocomplete + column-existence checks.

```python
# String shorthand
await Pet.query.order_by("-created_at", "name").limit(20).offset(40).all()
await Pet.query.range(0, 9).all()                           # inclusive range

# Typed form — autocomplete on Pet.f, nulls position support
await Pet.query.order_by(Pet.f.created_at.desc()).all()
await Pet.query.order_by(Pet.f.last_login.desc(nulls="last")).all()

# Mix freely
await Pet.query.order_by("species", Pet.f.amount.desc()).all()
```

Typos in either form raise `AttributeError` at call time — never silent server errors.

### Iteration over large result sets

`.iter()` streams every matching row using **PK keyset pagination** — `WHERE pk > :cursor ORDER BY pk LIMIT :batch_size` per batch. Constant time per batch regardless of position; scales to billions of rows.

```python
async for pet in Pet.query.eq("species", "cat").iter():
    process(pet)

# Tune batch size for the memory / round-trip tradeoff:
async for row in BigTable.query.iter(batch_size=5000):
    ...

# Compose with projections to narrow wire bytes per batch:
async for mini in Pet.query.eq("species", "cat").as_(PetMini).iter():
    ...
```

`.iter()` owns ordering and pagination — chaining `.order_by()` / `.limit()` / `.offset()` / `.range()` before it raises `SupabaseORMUsageError`. Race-safe under concurrent inserts (new rows with `pk > cursor` get picked up) and deletes (deleted rows simply don't appear).

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

## Client lifecycle

Four entry points cover the standard deployment shapes. Pick by *who owns the client* and *whether you need a context-manager boundary*:

| Entry point         | Owns the client | Shape                                        | Use for                                          |
|---------------------|-----------------|----------------------------------------------|--------------------------------------------------|
| `lifespan(url, key)`| orm             | `async with` / `with` block                  | FastAPI / ASGI apps, anywhere with a startup hook |
| `init(client)`      | orm             | one-liner, no `with`                         | scripts, cron, Celery workers                    |
| `set_client(client)`| caller          | one-liner, no `with`                         | tests handing in fakes, advanced setups          |
| `use_client(client)`| caller          | per-block `async with` / `with`              | per-request RLS overrides under concurrent load  |

`init()` and `lifespan()` register ownership: `shutdown()` (called explicitly or by `lifespan`'s `__aexit__`) will drain the client's httpx pools. `set_client()` only binds — caller stays responsible for teardown.

### FastAPI / ASGI

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

Inside a handler, just call the ORM as usual:

```python
@app.get("/pets", response_model=list[Pet])
async def list_pets():
    return await Pet.query.order_by("-created_at").all()
```

### Scripts, cron, Celery workers

When there's no `with`-block-shaped startup hook, use `init` / `shutdown` directly:

```python
from supabase import acreate_client
from supabase_orm import init, shutdown

async def main():
    init(await acreate_client(SUPABASE_URL, SUPABASE_KEY))
    try:
        async for pet in Pet.query.eq("species", "cat").iter():
            process(pet)
    finally:
        await shutdown()                            # optional — drains httpx pools
```

Sync flavour:

```python
from supabase import create_client
from supabase_orm.sync import init, shutdown

init(create_client(SUPABASE_URL, SUPABASE_KEY))
for pet in Pet.query.eq("species", "cat").iter():
    process(pet)
shutdown()                                          # optional
```

For short-lived processes, you can skip `shutdown()` entirely — process death drains the pools.

### Per-request RLS via JWT

`lifespan()` sets a module-wide default visible to every task (ASGI request handlers are *siblings* of the lifespan task, not children, so `ContextVar` inheritance wouldn't reach them). Per-request overrides go through `use_client()`, which uses a `ContextVar` and is safe under concurrent load — each request runs in its own task with its own snapshot.

```python
from supabase import acreate_client
from supabase_orm import use_client

@app.middleware("http")
async def per_request_client(request, call_next):
    auth = request.headers.get("authorization")
    if not auth:
        return await call_next(request)

    jwt = auth.removeprefix("Bearer ")
    client = await acreate_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.postgrest.auth(jwt)

    async with use_client(client):
        return await call_next(request)
```

> [!IMPORTANT]
> Don't mutate the app-wide client's auth headers across requests (e.g. `get_client().postgrest.auth(jwt)` directly). The underlying postgrest sub-client is shared, so the mutation leaks across overlapping requests. `ContextVar` isolates *references*, not the objects they point at — `use_client()` with a per-request client is the only safe pattern.

### Custom client (tests, advanced)

Bind a client without transferring ownership — useful for handing in a fake under test, or when calling code already wraps the client in its own context manager:

```python
from supabase_orm import set_client

set_client(my_fake_client)
try:
    rows = await Pet.query.eq("species", "cat").all()
finally:
    set_client(None)            # shutdown() would also unbind, but won't close my_fake_client
```

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

### Custom `QueryBuilder` methods

Subclass `QueryBuilder` to add your own chainable methods, then opt in either per-model or project-wide.

```python
from supabase_orm import QueryBuilder, SupabaseModel

class PaginatedQB(QueryBuilder):
    async def paginate(self, *, page: int, per_page: int):
        return await self.range(
            page * per_page, (page + 1) * per_page - 1
        ).all_with_count()
```

**Project-wide** — define a base model once, every subclass inherits via MRO:

```python
class _AppModel(SupabaseModel):
    __query_class__ = PaginatedQB

class User(_AppModel, table="users"):  # gets PaginatedQB automatically
    id: UUID
    email: str

rows, total = await User.query.eq("is_active", True).paginate(page=0, per_page=20)
```

**Per-model** — opt in inline, no base class needed:

```python
class Audit(SupabaseModel, table="audit_log", query_class=PaginatedQB):
    ...
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

The mock suite runs against both the async and sync trees in one invocation (440+ tests total). Integration runs only against the async tree — see [Lifecycle](#client-lifecycle) and the architecture rationale; sync mock coverage proves the wire path independently.

The integration suite needs a Supabase project with the test schema applied. See [`tests/integration/README.md`](tests/integration/README.md).

---

## Contributing

Issues and PRs welcome at [github.com/viperadnan-git/supabase-orm](https://github.com/viperadnan-git/supabase-orm).

### Architecture

Async is the canonical source. The sync API at `supabase_orm.sync` is generated from `src/supabase_orm/_async/` into `src/supabase_orm/_sync/` via `unasync`, with a project-specific rule that also rewrites prose in docstrings/comments. Test trees follow the same pattern (`tests/_async/` → `tests/_sync/`).

Edit only the async tree, then regenerate:

```bash
uv run python scripts/gen_sync.py                 # regenerate _sync/
uv run python scripts/gen_sync.py --check         # CI drift check (exit 1 on diff)
```

The hatch build hook (`scripts/hatch_build.py`) regenerates `_sync/` on every wheel/sdist build, so release artifacts always ship a fresh mirror.

#### `# gen_sync: skip-block` directive

For async-only code (e.g. `asyncio.gather` regressions, ASGI-specific lifespan tests) that has no meaningful sync counterpart, wrap it so the codegen drops it from the sync mirror:

```python
# gen_sync: skip-block
import asyncio

async def test_concurrent_tasks():
    results = await asyncio.gather(...)
# gen_sync: end-skip
```

### Running tests

```bash
uv run pytest                       # mock suite (fast, no network) — async + sync
uv run pytest -m integration        # integration (needs .env)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
