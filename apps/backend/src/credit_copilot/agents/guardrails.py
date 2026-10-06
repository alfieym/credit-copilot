"""OpenAI Agents SDK output guardrail (part of result validation ④).

Validates the drafting agent's "Risk Points & Conclusion" output: empty or overlong
counts as a tripwire, raising OutputGuardrailTripwireTriggered via the Runner, which
the upper layer degrades to a rule summary.
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
    """Output guardrail for the drafting agent's conclusion.

    Args:
        context: SDK run context.
        agent: The drafting agent.
        output: The LLM output to validate.

    Returns:
        A ``GuardrailFunctionOutput`` — trips when the conclusion is empty or longer
        than ``MAX_CONCLUSION_CHARS`` (500), otherwise reports its length.

    Implementation: casts output to text, then trips the guardrail (via ``Runner``) if
    it is empty or longer than ``MAX_CONCLUSION_CHARS`` (500); otherwise returns the
    length without tripping.
    """
    text = output if isinstance(output, str) else str(output)
    if not text.strip():
        return GuardrailFunctionOutput(
            output_info={"reason": "conclusion is empty"}, tripwire_triggered=True
        )
    if len(text) > MAX_CONCLUSION_CHARS:
        return GuardrailFunctionOutput(
            output_info={"reason": f"conclusion too long ({len(text)} chars)"},
            tripwire_triggered=True,
        )
    return GuardrailFunctionOutput(output_info={"length": len(text)}, tripwire_triggered=False)
