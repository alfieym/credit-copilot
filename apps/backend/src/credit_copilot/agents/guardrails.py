"""OpenAI Agents SDK output guardrail（④结果校验的一环）。

校验成文 Agent 的「风险点与结论」输出：为空 / 过长视为 tripwire，
由 Runner 抛 OutputGuardrailTripwireTriggered，上层据此降级为规则摘要。
"""
from __future__ import annotations

from typing import Any

from agents import Agent, GuardrailFunctionOutput, RunContextWrapper
from agents.guardrail import output_guardrail

MAX_CONCLUSION_CHARS = 500


@output_guardrail
def conclusion_output_guardrail(
    context: RunContextWrapper[Any], agent: Agent[Any], output: Any
) -> GuardrailFunctionOutput:
    """结论段校验：非空且不过长。"""
    text = output if isinstance(output, str) else str(output)
    if not text.strip():
        return GuardrailFunctionOutput(
            output_info={"reason": "结论为空"}, tripwire_triggered=True
        )
    if len(text) > MAX_CONCLUSION_CHARS:
        return GuardrailFunctionOutput(
            output_info={"reason": f"结论过长 {len(text)} 字"}, tripwire_triggered=True
        )
    return GuardrailFunctionOutput(output_info={"length": len(text)}, tripwire_triggered=False)
