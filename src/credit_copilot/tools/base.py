"""工具层基础：结构化结果 + 超时 + 指数退避重试。

这是「异常处理」设计原则的落点——所有工具都返回 :class:`ToolResult` 而非直接抛异常，
让场景层能按章节降级（单点失败不击穿整份报告）。

异常分类：
- :class:`TransientError`  瞬态错误（限流 / 5xx / 连接失败）→ 有限重试 + 指数退避
- :class:`ToolTimeout`     超时 → 有限重试后降级
- :class:`FatalError`      致命错误（参数错 / 权限拒 / 数据缺失）→ 不重试，立即失败
"""
from __future__ import annotations

import functools
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


class ToolError(Exception):
    """工具调用失败的基类。"""


class TransientError(ToolError):
    """瞬态错误：可重试。"""


class ToolTimeout(ToolError):
    """工具超时：有限重试后可降级。"""


class FatalError(ToolError):
    """致命错误：不重试。"""


@dataclass
class ToolResult:
    """工具统一返回结构。``fallback_applied`` 标记是否走了降级路径。"""

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
    """把会抛 :class:`ToolError` 的函数包装成返回 :class:`ToolResult` 的工具。

    - ``FatalError`` 直接失败，不重试；
    - ``TransientError`` / ``ToolTimeout`` 指数退避重试 ``retries`` 次，仍失败则标记降级。
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
