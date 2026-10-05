"""OpenAI Agents SDK：成文 Agent + @function_tool 工具注册 + 模型选择。

② 工具调用：``MEMO_TOOLS`` 把框架无关的工具（tools/）薄封装成 ``@function_tool``，
返回 JSON 友好结构；确定性管线直接用底层工具，Agent 侧工具供「核验/问答」复用。
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


# --- ② 工具调用：@function_tool 薄封装（框架无关工具的 JSON 友好入口） ---
@function_tool
def search_borrowers_tool(name: str) -> dict:
    """按名称模糊匹配借款人，返回匹配列表。"""
    return _wrap(search_borrowers(name))


@function_tool
def search_groups_tool(name: str) -> dict:
    """按名称模糊匹配借款集团，返回匹配列表。"""
    return _wrap(search_groups(name))


@function_tool
def get_borrower_overview_tool(borrower_id: int) -> dict:
    """借款人 + 所属集团概况。"""
    return _wrap(get_borrower_overview(borrower_id))


@function_tool
def get_group_overview_tool(group_id: int) -> dict:
    """集团概况。"""
    return _wrap(get_group_overview(group_id))


@function_tool
def get_ratings_tool(entity_type: str, entity_id: int) -> dict:
    """评级（含历史，时间维降序：当前有效在前）。"""
    return _wrap(get_ratings(entity_type, entity_id))


@function_tool
def get_facilities_tool(borrower_id: int) -> dict:
    """主额度 + 子额度。"""
    return _wrap(get_facilities(borrower_id))


@function_tool
def get_exposure_tool(group_id: int) -> dict:
    """集团合并敞口 vs 限额（最新时点）。"""
    return _wrap(get_exposure(group_id))


@function_tool
def get_involved_parties_tool(borrower_id: int) -> dict:
    """相关方与担保结构。"""
    return _wrap(get_involved_parties(borrower_id))


@function_tool
def search_policy_docs_tool(query: str, top_k: int = 5) -> dict:
    """检索政策文档 chunk，返回命中列表。"""
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
    """按 provider 构建 OpenAI 兼容模型（openai → openai_*，deepseek/qwen/zhipu → llm_*）。"""
    cfg = settings or get_settings()
    if cfg.llm_provider == "openai":
        base_url = cfg.openai_base_url
        model = cfg.openai_model
        key = cfg.openai_api_key or cfg.llm_api_key
    else:
        base_url = cfg.llm_base_url
        model = cfg.llm_model
        key = cfg.llm_api_key
        set_tracing_disabled(True)  # 非 OpenAI 端点不推 tracing
    return OpenAIChatCompletionsModel(
        model=model,
        openai_client=AsyncOpenAI(base_url=base_url, api_key=key or "sk-missing"),
    )


def build_composer_agent(settings: Settings | None = None) -> Agent:
    """成文 Agent：把已核验事实概括成「风险点与结论」。"""
    return Agent(
        name="credit_memo_conclusion",
        instructions=(
            "你是资深信贷分析师。基于给定事实与合规结论，用一段不超过 150 字的话概括该客户"
            "授信风险点与结论，不要编造未提供的事实。可用工具核验数字，但不要杜撰数据。"
        ),
        model=build_model(settings),
        tools=MEMO_TOOLS,
        output_guardrails=[conclusion_output_guardrail],
    )


_SYSTEM = (
    "你是资深信贷分析师。基于给定事实与合规结论，用一段不超过 150 字的话概括该客户"
    "授信风险点与结论，不要编造未提供的事实。"
)


def synthesize_conclusion(entity: Entity, flags: list[Flag]) -> tuple[str, list[str], str]:
    """第 7 章结论：OpenAI 兼容走 SDK Agent+Runner，Bedrock 走直连 client；失败降级为规则摘要。

    返回 (conclusion, citations, flag_txt)。
    """
    detail_lines = [f"- [{f.level}] {f.rule}：{f.detail}" for f in flags]
    flag_txt = "\n".join(detail_lines) or "- 未命中任何规则"
    base = "\n".join(detail_lines) or "未命中任何合规限制规则"
    fallback = f"（LLM 合成不可用，以下为规则结论）\n{base}"
    cfg = get_settings()
    if not has_llm_key(cfg):
        return fallback, [], flag_txt
    prompt = f"主体：{entity.name}\n合规结论：\n{base}"
    try:
        if cfg.llm_provider == "bedrock":
            text = LLMClient().complete(_SYSTEM, prompt)  # Agents SDK 无原生 Bedrock 模型
        else:
            result = Runner.run_sync(build_composer_agent(cfg), prompt)
            text = result.final_output
            text = text if isinstance(text, str) else str(text)
        return text, ["[llm]"], flag_txt
    except Exception:  # noqa: BLE001 —— 任何 LLM/SDK 异常都降级为规则摘要
        return fallback, [], flag_txt
