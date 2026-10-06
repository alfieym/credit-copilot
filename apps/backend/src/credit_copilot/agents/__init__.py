"""Credit-memo generation — OpenAI Agents SDK orchestration layer.

The four principles in practice:
- Task decomposition: a deterministic pipeline (explicit steps in ``orchestrator.run_report``)
  + an Agent that only handles LLM drafting.
- Tool calling: facts via DB (canned SQL), policy via RAG (policy_search);
  ``memo_agent.MEMO_TOOLS`` wraps these framework-agnostic tools with ``@function_tool``.
- Exception handling: tools return :class:`ToolResult` (with_retry in tools/base.py),
  and the scenario layer degrades per-section; LLM drafting failure degrades to a rule summary.
- Result validation: entity resolution (resolve_entity raises EntityResolutionError,
  equivalent to an input guardrail) + deterministic compliance rules + numeric/completeness/
  citation-coverage validation (validate_report) + an output guardrail on the conclusion
  (guardrails.conclusion_output_guardrail).
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
