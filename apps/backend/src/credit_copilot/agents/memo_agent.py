"""OpenAI Agents SDK: drafting agent + @function_tool registration + model selection.

② Tool calling: ``MEMO_TOOLS`` wraps the framework-agnostic tools (tools/) in thin
``@function_tool`` decorators returning JSON-friendly structures; the deterministic
pipeline uses the underlying tools directly, while the agent-side tools are reused
for verification / Q&A.
"""
from __future__ import annotations

from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    Tool,
    function_tool,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from credit_copilot.agents.guardrails import conclusion_output_guardrail
from credit_copilot.agents.models import Entity, Flag
from credit_copilot.config import Settings, get_settings
from credit_copilot.llm.client import LLMClient, has_llm_key
from credit_copilot.tools.base import ToolResult
from credit_copilot.tools.datawarehouse import (
    get_borrower_overview,
    get_exposure,
    get_facilities,
    get_group_overview,
    get_involved_parties,
    get_ratings,
    search_borrowers,
    search_groups,
)
from credit_copilot.tools.policy_search import search_policy_docs


def _wrap(r: ToolResult) -> dict:
    return {"ok": r.ok, "data": r.data, "error": r.error}


# --- ② Tool calling: thin @function_tool wrappers (JSON-friendly entry points) ---
@function_tool
def search_borrowers_tool(name: str) -> dict:
    """Fuzzy-match borrowers by name; returns the list of matches."""
    return _wrap(search_borrowers(name))


@function_tool
def search_groups_tool(name: str) -> dict:
    """Fuzzy-match borrowing groups by name; returns the list of matches."""
    return _wrap(search_groups(name))


@function_tool
def get_borrower_overview_tool(borrower_id: int) -> dict:
    """Borrower + its group overview."""
    return _wrap(get_borrower_overview(borrower_id))


@function_tool
def get_group_overview_tool(group_id: int) -> dict:
    """Group overview."""
    return _wrap(get_group_overview(group_id))


@function_tool
def get_ratings_tool(entity_type: str, entity_id: int) -> dict:
    """Ratings (including history; time dimension descending: current first)."""
    return _wrap(get_ratings(entity_type, entity_id))


@function_tool
def get_facilities_tool(borrower_id: int) -> dict:
    """Main facilities + sub facilities."""
    return _wrap(get_facilities(borrower_id))


@function_tool
def get_exposure_tool(group_id: int) -> dict:
    """Group consolidated exposure vs. limit (latest as-of date)."""
    return _wrap(get_exposure(group_id))


@function_tool
def get_involved_parties_tool(borrower_id: int) -> dict:
    """Related parties and guarantee structure."""
    return _wrap(get_involved_parties(borrower_id))


@function_tool
def search_policy_docs_tool(query: str, top_k: int = 5) -> dict:
    """Search policy-document chunks; returns the hit list."""
    return _wrap(search_policy_docs(query, top_k=top_k))


MEMO_TOOLS: list[Tool] = [
    search_borrowers_tool,
    search_groups_tool,
    get_borrower_overview_tool,
    get_group_overview_tool,
    get_ratings_tool,
    get_facilities_tool,
    get_exposure_tool,
    get_involved_parties_tool,
    search_policy_docs_tool,
]


def build_model(settings: Settings | None = None) -> OpenAIChatCompletionsModel:
    """Build an OpenAI-compatible model by provider
    (openai -> openai_*, deepseek/qwen/zhipu -> llm_*)."""
    cfg = settings or get_settings()
    if cfg.llm_provider == "openai":
        base_url = cfg.openai_base_url
        model = cfg.openai_model
        key = cfg.openai_api_key or cfg.llm_api_key
    else:
        base_url = cfg.llm_base_url
        model = cfg.llm_model
        key = cfg.llm_api_key
        set_tracing_disabled(True)  # non-OpenAI endpoints must not push tracing
    return OpenAIChatCompletionsModel(
        model=model,
        openai_client=AsyncOpenAI(base_url=base_url, api_key=key or "sk-missing"),
    )


def build_composer_agent(settings: Settings | None = None) -> Agent:
    """Composer agent: summarizes verified facts into "Risk Points & Conclusion"."""
    return Agent(
        name="credit_memo_conclusion",
        instructions=(
            "You are a senior credit analyst. Based on the given facts and compliance "
            "findings, summarize the client's credit risk points and conclusion in one "
            "paragraph of no more than 150 words. Do not fabricate facts that were not "
            "provided. You may use tools to verify figures, but never invent data."
        ),
        model=build_model(settings),
        tools=MEMO_TOOLS,
        output_guardrails=[conclusion_output_guardrail],
    )


_SYSTEM = (
    "You are a senior credit analyst. Based on the given facts and compliance findings, "
    "summarize the client's credit risk points and conclusion in one paragraph of no more "
    "than 150 words. Do not fabricate facts that were not provided."
)


def synthesize_conclusion(entity: Entity, flags: list[Flag]) -> tuple[str, list[str], str]:
    """Section 7 conclusion: OpenAI-compatible goes through SDK Agent+Runner,
    Bedrock through the direct client; failure degrades to a rule summary.

    Returns (conclusion, citations, flag_txt).
    """
    detail_lines = [f"- [{f.level}] {f.rule}: {f.detail}" for f in flags]
    flag_txt = "\n".join(detail_lines) or "- No rules triggered"
    base = "\n".join(detail_lines) or "No compliance restrictions triggered"
    fallback = f"(LLM synthesis unavailable; rule-based conclusion below)\n{base}"
    cfg = get_settings()
    if not has_llm_key(cfg):
        return fallback, [], flag_txt
    prompt = f"Entity: {entity.name}\nCompliance findings:\n{base}"
    try:
        if cfg.llm_provider == "bedrock":
            text = LLMClient().complete(_SYSTEM, prompt)  # Agents SDK has no native Bedrock model
        else:
            result = Runner.run_sync(build_composer_agent(cfg), prompt)
            text = result.final_output
            text = text if isinstance(text, str) else str(text)
        return text, ["[llm]"], flag_txt
    except Exception:  # noqa: BLE001 — any LLM/SDK error degrades to the rule summary
        return fallback, [], flag_txt
