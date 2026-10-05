"""数仓工具：确定性 canned SQL + 实体解析 + 只读 guardrail。

「工具调用」设计原则：报告主数据走 DB（参数化 SQL），不让 LLM 自由写 SQL。
自由 Text-to-SQL 留给 T1 问答场景（阶段2）。这里每个工具都经 ``with_retry``
包装，返回 :class:`ToolResult`，并带 ``connect_timeout`` / ``statement_timeout``。
"""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from credit_copilot.config import get_settings
from credit_copilot.guardrails.sql_guard import MAX_ROWS, validate_sql
from credit_copilot.tools.base import (
    FatalError,
    ToolTimeout,
    TransientError,
    with_retry,
)


def _connect() -> psycopg.Connection:
    """建立连接：连接超时 5s。连接失败视为瞬态错误（可重试）。"""
    cfg = get_settings()
    try:
        return psycopg.connect(
            cfg.postgres_dsn,
            connect_timeout=5,
            options="-c statement_timeout=10000",  # 单条 SQL 10s 超时
        )
    except psycopg.OperationalError as e:
        raise TransientError(f"DB 连接失败: {e}") from e


def _run_readonly(sql: str, params: tuple = ()) -> list[dict]:
    """执行只读 SQL：先过 guardrail，再执行，行数超限抛 FatalError。"""
    validate_sql(sql)
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
        except psycopg.Error as e:
            # statement_timeout 触发 → SQLSTATE 57014 query_canceled
            if getattr(e, "sqlstate", None) == "57014":
                raise ToolTimeout(f"SQL 超时: {e}") from e
            raise FatalError(f"SQL 执行失败: {e}") from e
    if len(rows) > MAX_ROWS:
        raise FatalError(f"返回 {len(rows)} 行超上限 {MAX_ROWS}")
    return rows


# --------------------------------------------------------------------------- #
# 实体解析
# --------------------------------------------------------------------------- #
@with_retry
def search_borrowers(name: str) -> list[dict]:
    """按名称模糊匹配借款人。"""
    return _run_readonly(
        "SELECT borrower_id, group_id, borrower_name, country, industry, "
        "legal_type, internal_rating, status "
        "FROM dim_borrower WHERE borrower_name ILIKE %s ORDER BY borrower_id",
        (f"%{name}%",),
    )


@with_retry
def search_groups(name: str) -> list[dict]:
    """按名称模糊匹配借款集团。"""
    return _run_readonly(
        "SELECT group_id, group_name, country, industry, consolidated_exposure_limit, "
        "risk_consolidation, status "
        "FROM dim_borrowing_group WHERE group_name ILIKE %s ORDER BY group_id",
        (f"%{name}%",),
    )


# --------------------------------------------------------------------------- #
# 报告各章节事实
# --------------------------------------------------------------------------- #
@with_retry
def get_borrower_overview(borrower_id: int) -> list[dict]:
    """借款人 + 所属集团概况。"""
    return _run_readonly(
        "SELECT b.borrower_id, b.borrower_name, b.country, b.industry, b.legal_type, "
        "b.internal_rating, g.group_id, g.group_name, g.industry AS group_industry, "
        "g.risk_consolidation, g.status "
        "FROM dim_borrower b LEFT JOIN dim_borrowing_group g ON b.group_id = g.group_id "
        "WHERE b.borrower_id = %s",
        (borrower_id,),
    )


@with_retry
def get_group_overview(group_id: int) -> list[dict]:
    """集团概况。"""
    return _run_readonly(
        "SELECT group_id, group_name, country, industry, consolidated_exposure_limit, "
        "risk_consolidation, status FROM dim_borrowing_group WHERE group_id = %s",
        (group_id,),
    )


@with_retry
def get_ratings(entity_type: str, entity_id: int) -> list[dict]:
    """评级（含历史，时间维降序：当前有效在前）。"""
    return _run_readonly(
        "SELECT rating_id, entity_type, entity_id, agency, grade, outlook, methodology, "
        "valid_from, valid_to, rating_date "
        "FROM fact_rating WHERE entity_type = %s AND entity_id = %s ORDER BY valid_from DESC",
        (entity_type, entity_id),
    )


@with_retry
def get_facilities(borrower_id: int) -> list[dict]:
    """主额度 + 子额度。"""
    return _run_readonly(
        "SELECT m.main_facility_id, m.facility_name, m.facility_type, m.currency, "
        "m.committed_amount, m.maturity_date, m.purpose, m.status, "
        "s.sub_facility_id, s.sub_type, s.limit_amount, s.utilization_amount "
        "FROM dim_main_facility m LEFT JOIN dim_sub_facility s "
        "ON m.main_facility_id = s.main_facility_id "
        "WHERE m.borrower_id = %s ORDER BY m.main_facility_id, s.sub_facility_id",
        (borrower_id,),
    )


@with_retry
def get_exposure(group_id: int) -> list[dict]:
    """集团合并敞口 vs 限额（最新时点）。"""
    return _run_readonly(
        "SELECT g.group_id, g.group_name, g.consolidated_exposure_limit, "
        "COALESCE(SUM(u.utilized_amount), 0) AS total_utilized "
        "FROM dim_borrowing_group g "
        "JOIN dim_borrower b ON b.group_id = g.group_id "
        "JOIN dim_main_facility m ON m.borrower_id = b.borrower_id "
        "JOIN fact_utilization u ON u.main_facility_id = m.main_facility_id "
        "WHERE g.group_id = %s "
        "AND u.as_of_date = (SELECT MAX(as_of_date) FROM fact_utilization) "
        "GROUP BY g.group_id",
        (group_id,),
    )


@with_retry
def get_involved_parties(borrower_id: int) -> list[dict]:
    """相关方与担保结构。"""
    return _run_readonly(
        "SELECT p.involved_party_id, p.main_facility_id, p.party_name, p.role, "
        "p.ownership_pct, p.country, p.is_internal "
        "FROM dim_involved_party p JOIN dim_main_facility m "
        "ON p.main_facility_id = m.main_facility_id "
        "WHERE m.borrower_id = %s ORDER BY p.role, p.party_name",
        (borrower_id,),
    )
