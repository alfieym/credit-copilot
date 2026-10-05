"""授信尽调报告生成（Credit Memo）—— OpenAI Agents SDK 编排层。

四原则落地：
- 任务拆解：确定性管线（``orchestrator.run_report`` 显式步骤）+ Agent 仅负责 LLM 成文。
- 工具调用：事实走 DB（canned SQL）、政策走 RAG（policy_search），
  ``memo_agent.MEMO_TOOLS`` 用 ``@function_tool`` 薄封装这些框架无关工具。
- 异常处理：工具层返回 :class:`ToolResult`（tools/base.py 的 with_retry），
  场景层按章节降级；LLM 成文失败降级为规则摘要。
- 结果校验：实体消歧（resolve_entity 抛 EntityResolutionError，等价 input guardrail）
  + 确定性合规规则 + 数值/完整性/引用覆盖率校验（validate_report）
  + 成文结论的 output guardrail（guardrails.conclusion_output_guardrail）。
"""
from __future__ import annotations

from credit_copilot.agents.models import (
    SECTION_TITLES,
    CreditMemo,
    Entity,
    EntityResolutionError,
    Flag,
    Section,
    extract_entity_hint,
)
from credit_copilot.agents.orchestrator import run_report, run_report_stream

__all__ = [
    "SECTION_TITLES",
    "CreditMemo",
    "Entity",
    "EntityResolutionError",
    "Flag",
    "Section",
    "extract_entity_hint",
    "run_report",
    "run_report_stream",
]
