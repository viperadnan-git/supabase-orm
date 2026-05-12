"""Filter operator registry.

Each operator is a name → (postgrest builder method, predicate-string compiler)
pair. Top-level chained calls use the builder method. Inside ``or_()`` /
``not_()`` we compile to PostgREST's ``col.op.value`` predicate string instead.

Adding a new operator:

    @register_op("fts")
    def _fts(builder, col, val): return builder.fts(col, val)

The op is then available as ``Model.query.fts(col, val)`` everywhere — but
typed access requires adding the method to the ``_Filterable`` mixin too.
Most users won't need ``register_op`` directly; it's mainly an internal hook.
"""

from __future__ import annotations

from typing import Any, Callable

from ._serializers import serialize

BuilderCall = Callable[[Any, str, Any], Any]
"""(postgrest_builder, column, value) → builder."""

ValueFormatter = Callable[[Any], str]
"""value → wire-formatted value string. Op-specific quoting / shape."""

OPERATORS: dict[str, BuilderCall] = {}
WIRE_NAMES: dict[str, str] = {}
VALUE_FORMATTERS: dict[str, ValueFormatter] = {}

# Back-compat alias — older external code may import ``PREDICATES``.
PREDICATES = VALUE_FORMATTERS


def register_op(
    name: str,
    *,
    wire: str | None = None,
    builder: BuilderCall | None = None,
    predicate: ValueFormatter | None = None,
) -> Callable[[BuilderCall], BuilderCall] | BuilderCall:
    """Register an operator.

    ``name`` is the Python method name (used as ``Model.<name>(col, val)``).
    ``wire`` is the PostgREST operator string used in ``or=(col.OP.val)``
    predicate groups. Defaults to ``name``. Override when ``name`` collides
    with a Python keyword — e.g. ``register_op("in_", wire="in")``.

    ``predicate`` is a value-only formatter ``(val) -> str``. Defaults to
    :func:`_pred_value` (handles scalars, sequences, comma-quoting). Override
    for ops that need a different value shape — e.g. arrays use ``{a,b,c}``.
    """
    wire_name = wire or name

    def _do(fn: BuilderCall) -> BuilderCall:
        OPERATORS[name] = fn
        WIRE_NAMES[name] = wire_name
        VALUE_FORMATTERS[name] = predicate or _pred_value
        return fn

    if builder is not None:
        _do(builder)
        return builder
    return _do


def _pred_value(val: Any) -> str:
    """Format a single value for a predicate string."""
    val = serialize(val)
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (list, tuple, set)):
        inner = ",".join(_pred_value(v) for v in val)
        return f"({inner})"
    s = str(val)
    # PostgREST predicates use commas as separators; quote if value contains one.
    if "," in s or "(" in s or ")" in s:
        return f'"{s}"'
    return s


def apply_op(builder: Any, op: str, col: str, val: Any) -> Any:
    fn = OPERATORS.get(op)
    if fn is None:
        raise KeyError(f"Unknown operator: {op!r}. Registered: {sorted(OPERATORS)}")
    return fn(builder, col, val)


def compile_value(op: str, val: Any) -> str:
    """Wire-format the value side of a predicate (no column, no operator)."""
    fmt = VALUE_FORMATTERS.get(op)
    if fmt is None:
        raise KeyError(f"Unknown operator: {op!r}")
    return fmt(val)


def compile_predicate(op: str, col: str, val: Any) -> str:
    """Build a full ``col.op.value`` predicate string."""
    wire = WIRE_NAMES.get(op)
    if wire is None:
        raise KeyError(f"Unknown operator: {op!r}")
    return f"{col}.{wire}.{VALUE_FORMATTERS[op](val)}"


# ─── Builtin operators ─────────────────────────────────────────────────────


@register_op("eq")
def _eq(b, c, v):
    return b.eq(c, serialize(v))


@register_op("neq")
def _neq(b, c, v):
    return b.neq(c, serialize(v))


@register_op("gt")
def _gt(b, c, v):
    return b.gt(c, serialize(v))


@register_op("gte")
def _gte(b, c, v):
    return b.gte(c, serialize(v))


@register_op("lt")
def _lt(b, c, v):
    return b.lt(c, serialize(v))


@register_op("lte")
def _lte(b, c, v):
    return b.lte(c, serialize(v))


@register_op("like")
def _like(b, c, v):
    return b.like(c, v)


@register_op("ilike")
def _ilike(b, c, v):
    return b.ilike(c, v)


def _in_value(v: Any) -> str:
    return "(" + ",".join(_pred_value(x).strip("()") for x in v) + ")"


@register_op("in_", wire="in", predicate=_in_value)
def _in(b, c, v):
    return b.in_(c, [serialize(x) for x in v])


@register_op("is_", wire="is")
def _is(b, c, v):
    return b.is_(c, v)


# Array/range ops use Postgres ``{a,b}`` braces (``in`` uses ``(a,b)`` parens).
# Wire names are short (``cs`` / ``cd`` / ``ov``); the long Python names map
# to supabase-py builder methods only.
def _array_value(val: Any) -> str:
    val = serialize(val)
    if isinstance(val, (list, tuple, set)):
        return "{" + ",".join(_pred_value(v).strip('"') for v in val) + "}"
    return _pred_value(val)


@register_op("contains", wire="cs", predicate=_array_value)
def _contains(b, c, v):
    return b.contains(c, serialize(v))


@register_op("contained_by", wire="cd", predicate=_array_value)
def _contained_by(b, c, v):
    return b.contained_by(c, serialize(v))


@register_op("overlaps", wire="ov", predicate=_array_value)
def _overlaps(b, c, v):
    return b.overlaps(c, serialize(v))


@register_op("fts")
def _fts(b, c, v):
    return b.text_search(c, v)


@register_op("plfts")
def _plfts(b, c, v):
    return b.text_search(c, v, options={"type": "plain"})


@register_op("phfts")
def _phfts(b, c, v):
    return b.text_search(c, v, options={"type": "phrase"})


@register_op("wfts")
def _wfts(b, c, v):
    return b.text_search(c, v, options={"type": "websearch"})
