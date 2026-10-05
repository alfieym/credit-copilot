"""OpenAI Agents SDK：function_tool 注册 + 成文 Agent 构建 + 离线降级。"""
from __future__ import annotations

from credit_copilot.agents.memo_agent import MEMO_TOOLS, build_composer_agent, synthesize_conclusion
from credit_copilot.agents.models import Entity


def test_function_tools_registered():
    names = {t.name for t in MEMO_TOOLS}
    assert "search_borrowers_tool" in names
    assert "get_ratings_tool" in names
    assert "search_policy_docs_tool" in names


def test_composer_agent_builds_offline():
    agent = build_composer_agent()
    assert agent.name == "credit_memo_conclusion"
    assert len(agent.output_guardrails) == 1


def test_synthesize_conclusion_offline_fallback():
    ent = Entity(kind="borrower", id=1, name="X")
    text, cites, _ = synthesize_conclusion(ent, [])
    assert "LLM 合成不可用" in text  # 无 key → 降级为规则摘要
    assert cites == []
