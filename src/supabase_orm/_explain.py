"""Resolved-request introspection — see ``QueryBuilder.explain``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

# Case-insensitive match against lowercased keys.
_SENSITIVE: frozenset[str] = frozenset(
    {"apikey", "authorization", "cookie", "x-api-key"}
)

_REDACTED = "***REDACTED***"


@dataclass(frozen=True)
class ExplainResult:
    method: str
    path: str
    params: dict[str, str]
    headers: dict[str, str]
    body: Any

    @property
    def url(self) -> str:
        if not self.params:
            return self.path
        return f"{self.path}?{urlencode(self.params)}"

    def __str__(self) -> str:
        lines = [f"{self.method} {self.url}"]
        for k, v in self.headers.items():
            lines.append(f"  {k}: {v}")
        if self.body is not None:
            lines.append(f"  body: {self.body!r}")
        return "\n".join(lines)


def from_builder(builder: Any, *, redact: bool = True) -> ExplainResult:
    """Read ``builder.request`` (postgrest ``RequestConfig``); no network."""
    r = builder.request
    raw = dict(r.headers)
    headers = (
        {k: (_REDACTED if k.lower() in _SENSITIVE else v) for k, v in raw.items()}
        if redact
        else raw
    )
    return ExplainResult(
        method=str(getattr(r.http_method, "value", r.http_method)),
        path=str(r.path),
        params=dict(r.params),
        headers=headers,
        body=r.json,
    )
