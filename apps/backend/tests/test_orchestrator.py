"""编排冒烟测试：run_report 离线可产 memo；实体消歧空查询走拒答。"""
from __future__ import annotations

from credit_copilot.agents.models import EntityResolutionError
from credit_copilot.agents.orchestrator import run_report
from credit_copilot.agents.pipeline import resolve_entity


def test_resolve_entity_empty_hint_rejects():
    try:
        resolve_entity("")
    except EntityResolutionError as e:
        assert "无法从问题中识别主体" in e.message
    else:
        raise AssertionError("空查询应拒答")


def test_run_report_offline_returns_memo():
    memo = run_report("")
    assert memo.sections
    assert memo.sections[0].title == "生成失败"
