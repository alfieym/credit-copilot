"""结果校验（第 1 关）：SQL 只读白名单。"""
from __future__ import annotations

import pytest

from credit_copilot.guardrails.sql_guard import SQLGuardError, cap_rows, validate_sql


def test_allows_select():
    validate_sql("SELECT * FROM dim_borrower WHERE borrower_id = %s")


def test_allows_join():
    validate_sql(
        "SELECT b.borrower_id, g.group_name FROM dim_borrower b "
        "JOIN dim_borrowing_group g ON b.group_id = g.group_id WHERE b.borrower_id = %s"
    )


def test_rejects_empty():
    with pytest.raises(SQLGuardError):
        validate_sql("")


def test_rejects_insert():
    with pytest.raises(SQLGuardError):
        validate_sql("INSERT INTO dim_borrower VALUES (1)")


def test_rejects_update():
    with pytest.raises(SQLGuardError):
        validate_sql("UPDATE dim_borrower SET status = 'x'")


def test_rejects_multi_statement():
    with pytest.raises(SQLGuardError):
        validate_sql("SELECT 1; DROP TABLE dim_borrower")


def test_rejects_non_whitelisted_table():
    with pytest.raises(SQLGuardError):
        validate_sql("SELECT * FROM secret_table")


def test_rejects_forbidden_keyword():
    with pytest.raises(SQLGuardError):
        validate_sql("SELECT * FROM dim_borrower INTO temp_table")


def test_cap_rows():
    assert len(cap_rows([1] * 100)) == 100
    with pytest.raises(SQLGuardError):
        cap_rows([1] * 1001)
