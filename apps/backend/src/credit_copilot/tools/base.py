"""Tool layer base: structured results + timeout + exponential-backoff retry.

This is where the "exception handling" design principle lands — every tool returns a
:class:`ToolResult` instead of raising, so the scenario layer can degrade per-section
(a single-point failure never breaks the whole report).

Exception taxonomy:
- :class:`TransientError`  transient (rate limit / 5xx / connection) -> bounded retry + backoff
- :class:`ToolTimeout`     timeout -> bounded retry then degrade
- :class:`FatalError`      fatal (bad argument / permission / missing data) -> no retry, fail fast
"""
from __future__ import annotations

import functools
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


class ToolError(Exception):
    """Base class for tool-call failures."""


class TransientError(ToolError):
    """Transient error: retryable."""


class ToolTimeout(ToolError):
    """Tool timeout: degrade after bounded retries."""


class FatalError(ToolError):
    """Fatal error: do not retry."""


@dataclass
class ToolResult:
    """Unified tool return structure.
    ``fallback_applied`` marks whether the degraded path was taken."""

    ok: bool
    data: Any = None
    error: str | None = None
    fallback_applied: bool = False

    @classmethod
    def success(cls, data: Any) -> ToolResult:
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error: str, *, fallback: bool = False) -> ToolResult:
        return cls(ok=False, error=error, fallback_applied=fallback)


def with_retry(
    fn: Callable[..., T], *, retries: int = 3, backoff: float = 0.5
) -> Callable[..., ToolResult]:
    """Wrap a function that raises :class:`ToolError` into a tool returning :class:`ToolResult`.

    - ``FatalError`` fails immediately (no retry);
    - ``TransientError`` / ``ToolTimeout`` retry with exponential backoff ``retries``
      times, then mark the degraded path.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
        last: ToolError | None = None
        for attempt in range(retries + 1):
            try:
                return ToolResult.success(fn(*args, **kwargs))
            except FatalError as e:
                return ToolResult.failure(str(e))
            except (TransientError, ToolTimeout) as e:
                last = e
                if attempt < retries:
                    time.sleep(backoff * (2**attempt))
        return ToolResult.failure(f"{type(last).__name__}: {last}", fallback=True)

    return wrapper
