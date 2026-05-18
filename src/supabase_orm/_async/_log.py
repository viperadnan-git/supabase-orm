"""Per-query logging at ``logging.getLogger("supabase_orm.query")``.

Disabled by default — attach a handler / set level=DEBUG to opt in.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .._explain import from_builder

_LOG = logging.getLogger("supabase_orm.query")


async def execute_logged(builder: Any) -> Any:
    """``await builder.execute()`` with a DEBUG log of method + URL + ms.

    Cheap when disabled (single ``isEnabledFor`` check, no timing).
    Log path swallows introspection errors to never break the query.
    """
    if not _LOG.isEnabledFor(logging.DEBUG):
        return await builder.execute()
    t0 = time.perf_counter()
    try:
        return await builder.execute()
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        try:
            ex = from_builder(builder)
            _LOG.debug("%s %s (%.1fms)", ex.method, ex.url, elapsed_ms)
        except Exception:
            _LOG.debug("query (%.1fms) [no introspection]", elapsed_ms)
