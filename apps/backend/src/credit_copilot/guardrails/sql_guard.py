"""SQL Guardrail：只读白名单 + 单语句 + 危险关键字 + 行数上限。

这是「结果校验」的第一道关卡（执行前校验），防御性编程：
即使 SQL 由 Agent/LLM 生成，也只允许命中白名单表的只读查询。
注：表名校验为启发式（正则提取 FROM/JOIN 后的表名），非完整 SQL 解析器。
"""
from __future__ import annotations

import re

from credit_copilot.tools.base import FatalError

# 只读白名单：本域 8 张表
ALLOWED_TABLES = frozenset(
    {
        "dim_borrowing_group",
        "dim_borrower",
        "dim_main_facility",
        "dim_sub_facility",
        "fact_rating",
        "dim_involved_party",
        "map_carm_wren",
        "fact_utilization",
    }
)

# 写入 / DDL / DCL 关键字（词边界匹配，大小写不敏感）
FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "merge", "replace", "copy", "call", "execute",
    "attach", "detach", "vacuum", "reindex", "into",
)

MAX_ROWS = 1000

_FROM_RE = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_.]*)", re.IGNORECASE)


class SQLGuardError(FatalError):
    """SQL 未通过只读白名单校验。"""


def validate_sql(sql: str) -> None:
    """校验只读 SQL，不满足抛 :class:`SQLGuardError`。"""
    s = sql.strip()
    if not s:
        raise SQLGuardError("空 SQL")

    # 单语句：去掉末尾分号后不允许再出现分号
    body = s[:-1].rstrip() if s.endswith(";") else s
    if ";" in body:
        raise SQLGuardError("禁止多语句")

    # 只读：首关键字必须是 SELECT 或 WITH
    first = re.match(r"\s*([A-Za-z]+)", body)
    if not first or first.group(1).upper() not in ("SELECT", "WITH"):
        raise SQLGuardError("仅允许 SELECT / WITH 查询")

    for kw in FORBIDDEN:
        if re.search(rf"\b{re.escape(kw)}\b", body, re.IGNORECASE):
            raise SQLGuardError(f"禁止关键字: {kw}")

    # 表白名单
    for m in _FROM_RE.finditer(body):
        table = m.group(1).split(".")[-1].strip('"')
        if table not in ALLOWED_TABLES:
            raise SQLGuardError(f"表不在白名单: {table}")


def cap_rows(rows: list) -> list:
    """行数上限：超限抛 :class:`SQLGuardError`，避免把整库拉回。"""
    if len(rows) > MAX_ROWS:
        raise SQLGuardError(f"返回行数 {len(rows)} 超上限 {MAX_ROWS}")
    return rows
