-- Schema for supabase-orm integration tests.
-- Apply once to your test Supabase project (Dashboard → SQL editor, or
-- `supabase db push` if you mirror this into a migration).
--
-- IMPORTANT: This drops/recreates the tables. Only run against a project
-- you've designated for tests.

drop table if exists orm_test_pets cascade;
drop table if exists orm_test_owners cascade;

create table orm_test_owners (
    id          uuid primary key default gen_random_uuid(),
    email       text not null unique,
    is_active   bool not null default true,
    created_at  timestamptz not null default now()
);

create table orm_test_pets (
    id          uuid primary key default gen_random_uuid(),
    owner_id    uuid references orm_test_owners(id) on delete cascade,
    name        text not null,
    species     text not null,
    adopted     bool not null default false,
    tags        text[] not null default '{}',
    amount      numeric(12,2) not null default 0,
    due         date,
    created_at  timestamptz not null default now()
);

create index on orm_test_pets (owner_id);
create index on orm_test_pets (species);

-- RPC used by the rpc integration test.
drop function if exists orm_test_count_active_owners();
create function orm_test_count_active_owners()
returns integer
language sql
as $$
    select count(*)::int from orm_test_owners where is_active = true;
$$;

drop function if exists orm_test_owner_pet_count(p_owner uuid);
create function orm_test_owner_pet_count(p_owner uuid)
returns table(owner_id uuid, n integer)
language sql
as $$
    select owner_id, count(*)::int as n
    from orm_test_pets
    where owner_id = p_owner
    group by owner_id;
$$;

-- The service-role key bypasses RLS; if you only have an anon key, enable
-- permissive policies for the test tables below.
-- alter table orm_test_owners enable row level security;
-- alter table orm_test_pets   enable row level security;
-- create policy "anon all" on orm_test_owners for all using (true) with check (true);
-- create policy "anon all" on orm_test_pets   for all using (true) with check (true);
