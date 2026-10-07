"""Data-warehouse tools: deterministic canned SQL + entity resolution + read-only guardrail.

Tool-calling design principle: report data comes from the DB via parameterized SQL;
the LLM never writes free-form SQL. Free text-to-SQL is reserved for the T1 Q&A
scenario (phase 2). Every tool here is wrapped by ``with_retry``, returns a
:class:`ToolResult`, and carries ``connect_timeout`` / ``statement_timeout``.
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
    """Open a psycopg connection to the configured Postgres.

    Returns:
        A configured ``psycopg.Connection``.

    Raises:
        TransientError: on ``psycopg.OperationalError`` (so ``with_retry`` retries it).

    Implementation: ``psycopg.connect`` with ``connect_timeout=5`` and a per-statement
    ``statement_timeout=10000`` (10s).
    """
    cfg = get_settings()
    try:
        return psycopg.connect(
            cfg.postgres_dsn,
            connect_timeout=5,
            options="-c statement_timeout=10000",  # 10s per-statement timeout
        )
    except psycopg.OperationalError as e:
        raise TransientError(f"DB connection failed: {e}") from e


def _run_readonly(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a canned read-only SQL statement safely and return rows as dicts.

    Args:
        sql: The parameterized read-only SQL statement.
        params: Bound parameter values for the statement.

    Returns:
        ``list[dict]`` of result rows (one dict per row, keys = column names).

    Raises:
        ToolTimeout: on ``sqlstate=57014`` (statement timeout).
        FatalError: on invalid SQL, other DB errors, or results over ``MAX_ROWS``.
        TransientError: on connection failure (propagated from ``_connect``).

    Implementation: ``validate_sql`` guardrail, then execute with bound parameters via
    ``dict_row``.
    """
    validate_sql(sql)
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
        except psycopg.Error as e:
            # statement_timeout fires as SQLSTATE 57014 query_canceled
            if getattr(e, "sqlstate", None) == "57014":
                raise ToolTimeout(f"SQL timeout: {e}") from e
            raise FatalError(f"SQL execution failed: {e}") from e
    if len(rows) > MAX_ROWS:
        raise FatalError(f"Returned {len(rows)} rows, over the limit of {MAX_ROWS}")
    return rows


# --------------------------------------------------------------------------- #
# Entity resolution
# --------------------------------------------------------------------------- #
@with_retry
def search_borrowers(name: str) -> list[dict]:
    """Fuzzy-match borrowers by name (matches either the Chinese or English name).

    Args:
        name: Borrower-name fragment to fuzzy-match.

    Returns:
        ``list[dict]`` of borrower rows (borrower_id, group_id, borrower_name_cn/en,
        country, industry, legal_type, internal_rating, status).

    Implementation: ``ILIKE '%name%'`` on both ``borrower_name_cn`` and
    ``borrower_name_en``, ordered by ``borrower_id``.
    """
    return _run_readonly(
        "SELECT borrower_id, group_id, borrower_name_cn, borrower_name_en, country, "
        "industry, legal_type, internal_rating, status "
        "FROM dim_borrower WHERE borrower_name_cn ILIKE %s OR borrower_name_en ILIKE %s "
        "ORDER BY borrower_id",
        (f"%{name}%", f"%{name}%"),
    )


@with_retry
def search_groups(name: str) -> list[dict]:
    """Fuzzy-match borrowing groups by name (matches either the Chinese or English name).

    Args:
        name: Group-name fragment to fuzzy-match.

    Returns:
        ``list[dict]`` of group rows (group_id, group_name_cn/en, country, industry,
        consolidated_exposure_limit, risk_consolidation, status).

    Implementation: ``ILIKE '%name%'`` on both ``group_name_cn`` and ``group_name_en``,
    ordered by ``group_id``.
    """
    return _run_readonly(
        "SELECT group_id, group_name_cn, group_name_en, country, industry, "
        "consolidated_exposure_limit, risk_consolidation, status "
        "FROM dim_borrowing_group WHERE group_name_cn ILIKE %s OR group_name_en ILIKE %s "
        "ORDER BY group_id",
        (f"%{name}%", f"%{name}%"),
    )


# --------------------------------------------------------------------------- #
# Per-section report facts
# --------------------------------------------------------------------------- #
@with_retry
def get_borrower_overview(borrower_id: int) -> list[dict]:
    """Borrower plus its borrowing group (chapter 1 fact).

    Args:
        borrower_id: The borrower's primary key.

    Returns:
        ``list[dict]`` with the borrower's identity fields joined with its group's names /
        industry / status.

    Implementation: ``dim_borrower LEFT JOIN dim_borrowing_group`` on ``group_id``.
    """
    return _run_readonly(
        "SELECT b.borrower_id, b.borrower_name_cn, b.borrower_name_en, b.country, "
        "b.industry, b.legal_type, b.internal_rating, g.group_id, g.group_name_cn, "
        "g.group_name_en, g.industry AS group_industry, g.risk_consolidation, g.status "
        "FROM dim_borrower b LEFT JOIN dim_borrowing_group g ON b.group_id = g.group_id "
        "WHERE b.borrower_id = %s",
        (borrower_id,),
    )


@with_retry
def get_group_overview(group_id: int) -> list[dict]:
    """Borrowing-group overview (chapter 1 fact for group queries).

    Args:
        group_id: The group's primary key.

    Returns:
        ``list[dict]`` with one group row (identity, industry, consolidated exposure
        limit, risk-consolidation, status).

    Implementation: a single-row ``SELECT`` on ``dim_borrowing_group``.
    """
    return _run_readonly(
        "SELECT group_id, group_name_cn, group_name_en, country, industry, "
        "consolidated_exposure_limit, risk_consolidation, status "
        "FROM dim_borrowing_group WHERE group_id = %s",
        (group_id,),
    )


@with_retry
def get_ratings(entity_type: str, entity_id: int) -> list[dict]:
    """Ratings for an entity (chapter 2 fact), newest first.

    Args:
        entity_type: ``"borrower"`` or ``"group"``.
        entity_id: The entity's primary key.

    Returns:
        ``list[dict]`` of rating rows, newest first.

    Implementation: ``SELECT ... FROM fact_rating WHERE entity_type = %s AND
    entity_id = %s ORDER BY valid_from DESC`` — current ratings (``valid_to`` NULL)
    surface before historical ones.
    """
    return _run_readonly(
        "SELECT rating_id, entity_type, entity_id, agency, grade, outlook, methodology, "
        "valid_from, valid_to, rating_date "
        "FROM fact_rating WHERE entity_type = %s AND entity_id = %s ORDER BY valid_from DESC",
        (entity_type, entity_id),
    )


@with_retry
def get_facilities(borrower_id: int) -> list[dict]:
    """Main facilities with their sub-facilities (chapter 3 fact).

    Args:
        borrower_id: The borrower's primary key.

    Returns:
        ``list[dict]`` of facility rows — one per sub-facility (main facilities without
        subs keep NULL sub columns).

    Implementation: ``dim_main_facility LEFT JOIN dim_sub_facility`` on
    ``main_facility_id``, ordered by main then sub id.
    """
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
    """Group consolidated exposure vs. limit at the latest as-of date (chapter 4 fact).

    Args:
        group_id: The group's primary key.

    Returns:
        ``list[dict]`` with one row carrying ``consolidated_exposure_limit`` and
        ``total_utilized``.

    Implementation: joins group → borrowers → main facilities → ``fact_utilization``,
    filters ``fact_utilization`` to the max ``as_of_date``, and sums ``utilized_amount``
    per group to compare against ``consolidated_exposure_limit``.
    """
    return _run_readonly(
        "SELECT g.group_id, g.group_name_cn, g.group_name_en, g.consolidated_exposure_limit, "
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
    """Related parties and guarantee structure (chapter 5 fact).

    Args:
        borrower_id: The borrower's primary key.

    Returns:
        ``list[dict]`` of party rows (role, ownership percentage, country, internal
        flag), ordered by role then name.

    Implementation: ``dim_involved_party JOIN dim_main_facility`` on
    ``main_facility_id`` for one borrower.
    """
    return _run_readonly(
        "SELECT p.involved_party_id, p.main_facility_id, p.party_name, p.role, "
        "p.ownership_pct, p.country, p.is_internal "
        "FROM dim_involved_party p JOIN dim_main_facility m "
        "ON p.main_facility_id = m.main_facility_id "
        "WHERE m.borrower_id = %s ORDER BY p.role, p.party_name",
        (borrower_id,),
    )
