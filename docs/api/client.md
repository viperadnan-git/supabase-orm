---
search:
  boost: 2
---

# Client lifecycle

Pick the entry point that matches your runtime. All four manage the same `ContextVar` — the difference is who owns the client and when it's closed.

=== "async / FastAPI"

    ```python
    from supabase_orm import lifespan

    async with lifespan(SUPABASE_URL, SUPABASE_KEY):
        # the orm sees the client for the duration of this block
        rows = await Pet.query.all()
    ```

=== "async / manual"

    ```python
    from supabase import acreate_client
    from supabase_orm import init, shutdown

    init(await acreate_client(SUPABASE_URL, SUPABASE_KEY))
    try:
        rows = await Pet.query.all()
    finally:
        await shutdown()
    ```

=== "sync (scripts, Celery, cron)"

    ```python
    from supabase import create_client
    from supabase_orm.sync import init, shutdown

    init(create_client(SUPABASE_URL, SUPABASE_KEY))
    try:
        rows = Pet.query.all()
    finally:
        shutdown()
    ```

---

::: supabase_orm.lifespan

::: supabase_orm.init

::: supabase_orm.shutdown

::: supabase_orm.set_client

::: supabase_orm.get_client

::: supabase_orm.use_client
