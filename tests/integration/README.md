# Integration tests

These hit a real Supabase project. They're skipped by default; CI runs them
explicitly. The mock suite in `tests/` is still the fast feedback loop.

## One-time setup

1. Create a Supabase project dedicated to tests (or pick one you don't mind
   wiping the `orm_test_*` tables in).
2. Apply `schema.sql` once via the SQL editor or `psql`.
3. Grab the project URL and the **service-role** key (RLS-bypassing). Anon
   keys also work if you enable the permissive policies at the bottom of
   `schema.sql`.

## Running locally

Either export the env vars directly, or copy `.env.example` → `.env` at the
repo root — the integration conftest auto-loads it via `python-dotenv`
(existing env vars take precedence, so CI secrets are never overridden):

```bash
cp .env.example .env       # then fill in SUPABASE_TEST_URL / SUPABASE_TEST_KEY

uv run pytest tests/integration -v          # run just the integration suite
uv run pytest -m integration -v             # same, via marker
uv run pytest                               # default: integration is skipped
```

## CI (GitHub Actions)

Store the URL + key as repository secrets, then:

```yaml
- name: Run integration tests
  env:
    SUPABASE_TEST_URL: ${{ secrets.SUPABASE_TEST_URL }}
    SUPABASE_TEST_KEY: ${{ secrets.SUPABASE_TEST_KEY }}
  run: uv run pytest tests/integration -v
```

## What they cover (vs. the mock suite)

The mock suite proves we *call* postgrest correctly. These tests prove
postgrest *interprets* those calls as we expect:

- Every filter operator (`eq`/`neq`/`gt`/`gte`/`lt`/`lte`/`like`/`ilike`/
  `in_`/`is_`/`contains`/`contained_by`/`overlaps`/`fts`) round-trips a real
  row.
- `or_` and `not_` predicate strings actually parse server-side, including
  the `and(...)`-wrap branch.
- Resource embedding (`owner:orm_test_owners(...)`) resolves with both
  `left` and `inner` joins.
- `count="exact"` + `head=True`, `range()`, `order_by` (asc + desc).
- Write round-trips: `create` / `bulk_create` / `save` / `instance.update` /
  `query.update` / `delete` / `query.delete`.
- Pydantic validates real PostgREST row shapes (timestamptz, numeric,
  text[]).
- RPC: `setof` and scalar.

Each test starts from empty tables (function-scoped truncate fixture).
