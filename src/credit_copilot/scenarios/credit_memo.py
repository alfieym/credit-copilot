"""授信尽调报告生成（Credit Memo）—— 首个场景。

四原则落地：
- 任务拆解：LangGraph 确定性 DAG
  ``resolve_entity → collect_facts(并行) → check_compliance → compose_report → validate_report``，
  校验不过则回炉（有界重试）。
- 工具调用：事实走 DB（canned SQL），政策走 RAG（policy_search），只有成文/推理交给 LLM。
- 异常处理：工具层返回 :class:`ToolResult`，场景层按章节降级（政策检索失败→跳过合规、标注缺口）。
- 结果校验：实体消歧 + 确定性合规规则 + 数值/完整性/引用覆盖率校验（阶段4 再做 DB 真值核验）。
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from credit_copilot.llm.client import LLMClient
from credit_copilot.tools.base import ToolError, ToolResult
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

# --------------------------------------------------------------------------- #
# 领域模型
# --------------------------------------------------------------------------- #
SECTION_TITLES = [
    "借款人及集团概况",
    "评级情况",
    "授信方案",
    "敞口与限额使用",
    "相关方与担保结构",
    "政策合规核验",
    "风险点与结论",
]

GRADES = [
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
    "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-",
    "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D",
]
_GRADE_RANK = {g: i for i, g in enumerate(GRADES)}


def _grade_at_or_below(grade: str, boundary: str) -> bool:
    """评级是否 <= boundary（索引越大评级越差）。"""
    return _GRADE_RANK.get(grade, 999) >= _GRADE_RANK.get(boundary, 999)


@dataclass
class Entity:
    kind: str                 # "borrower" / "group"
    id: int
    name: str
    group_id: int | None = None


@dataclass
class Flag:
    level: str                # error / warning / info
    rule: str
    policy_ref: str           # 形如 "评级准入政策#评级准入线"
    detail: str


class Section(BaseModel):
    title: str
    content: str
    citations: list[str] = Field(default_factory=list)


class CreditMemo(BaseModel):
    entity_name: str
    sections: list[Section] = Field(default_factory=list)
    compliance_flags: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    generated_at: str = ""


# --------------------------------------------------------------------------- #
# 实体消歧（结果校验第 2 关）
# --------------------------------------------------------------------------- #
_QUOTED = re.compile(r"[『「《\"'`]([^』」》\"'`]+)[』」》\"'`]")


def extract_entity_hint(query: str) -> str:
    """从问题里提取主体名称（确定性启发式；生产可换 LLM 抽取）。"""
    m = _QUOTED.search(query)
    if m:
        return m.group(1).strip()
    hint = query.strip()
    for verb in ("生成", "撰写", "分析", "查询", "查"):
        if hint.startswith(verb):
            hint = hint[len(verb):]
            break
    for suffix in ("的授信尽调报告", "授信尽调报告", "的尽调报告", "尽调报告",
                   "授信报告", "的报告"):
        if hint.endswith(suffix):
            hint = hint[: -len(suffix)]
            break
    return hint.strip(" \t\n，。,:：")


# --------------------------------------------------------------------------- #
# 节点：任务拆解
# --------------------------------------------------------------------------- #
class MemoState(TypedDict, total=False):
    query: str
    entity: Entity | None
    facts: dict[str, ToolResult]
    compliance: list[Flag]
    report: CreditMemo | None
    validation_errors: list[str]
    compose_attempts: int


def resolve_entity(state: MemoState) -> dict:
    """第 0 步：实体消歧。0 条→拒答；>1 条→列候选不硬猜；恰好 1 条→通过。"""
    hint = extract_entity_hint(state["query"])
    if not hint:
        return {"validation_errors": ["无法从问题中识别主体名称"]}
    candidates: list[Entity] = []
    b = search_borrowers(hint)
    g = search_groups(hint)
    if b.ok:
        candidates += [
            Entity(kind="borrower", id=r["borrower_id"], name=r["borrower_name"],
                   group_id=r["group_id"])
            for r in b.data
        ]
    if g.ok:
        candidates += [Entity(kind="group", id=r["group_id"], name=r["group_name"]) for r in g.data]
    if not candidates:
        return {"validation_errors": [f"未找到主体「{hint}」"]}
    if len(candidates) > 1:
        names = "、".join(c.name for c in candidates)
        msg = f"名称歧义，命中 {len(candidates)} 个主体：{names}，请精确指定"
        return {"entity": None, "validation_errors": [msg]}
    return {"entity": candidates[0]}


def collect_facts(state: MemoState) -> dict:
    """第 1 步：并行 fan-out 取各章节事实（DB + RAG）。"""
    ent = state.get("entity")
    if ent is None:
        return {}
    facts: dict[str, ToolResult] = {}

    # 先取 overview，拿到 group_id / 行业 / 名称供后续并行任务使用
    overview = (get_borrower_overview(ent.id) if ent.kind == "borrower"
                else get_group_overview(ent.id))
    facts["overview"] = overview
    row = overview.data[0] if overview.ok and overview.data else {}
    group_id = row.get("group_id") or ent.group_id
    industry = row.get("industry") or row.get("group_industry") or ""
    name = row.get("borrower_name") or row.get("group_name") or ent.name

    tasks: dict[str, Callable[[], ToolResult]] = {
        "ratings": lambda: get_ratings("borrower", ent.id) if ent.kind == "borrower"
        else get_ratings("group", ent.id),
        "facilities": lambda: get_facilities(ent.id) if ent.kind == "borrower"
        else ToolResult.failure("集团主体无单户额度明细"),
        "exposure": lambda: (get_exposure(group_id) if group_id
                             else ToolResult.failure("无关联集团")),
        "parties": lambda: get_involved_parties(ent.id) if ent.kind == "borrower"
        else ToolResult.failure("集团主体无单户相关方"),
        "policy": lambda: search_policy_docs(f"{industry} {name}"),
    }
    if ent.kind == "borrower" and group_id is not None:
        tasks["group"] = lambda: get_group_overview(group_id)

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {key: ex.submit(fn) for key, fn in tasks.items()}
        for key, fut in futures.items():
            try:
                facts[key] = fut.result(timeout=30)
            except Exception as e:  # noqa: BLE001 —— 兜底：任何意外都降级为失败
                facts[key] = ToolResult.failure(f"意外异常: {e}", fallback=True)
    return {"facts": facts}


def build_compliance_flags(entity: Entity, facts: dict[str, ToolResult]) -> list[Flag]:
    """确定性合规规则（结果校验的规则层）。"""
    flags: list[Flag] = []
    overview = facts.get("overview")
    row = overview.data[0] if overview and overview.ok and overview.data else {}

    # 1. 行业准入
    industry = row.get("industry") or row.get("group_industry") or ""
    if industry == "房地产":
        flags.append(Flag("warning", "房地产行业准入", "行业准入政策#房地产行业准入",
                          f"{entity.name} 属房地产行业，新增授信须报总行审批"))

    # 2. 评级准入 + 展望
    ratings = facts.get("ratings")
    if ratings and ratings.ok:
        current = [r for r in ratings.data if r.get("valid_to") is None]
        internal = [r for r in current if r.get("agency") == "internal"] or current
        if internal:
            g = internal[0]
            if _grade_at_or_below(g["grade"], "BB-"):
                flags.append(Flag("error", "评级准入线", "评级准入政策#评级准入线",
                                  f"内部评级 {g['grade']} ≤ BB-，禁止新增授信"))
            if g.get("outlook") == "Negative":
                flags.append(Flag("warning", "评级展望负面", "评级准入政策#展望管理",
                                  "展望 Negative，须加强贷后监控，频率由季度提至月度"))

    # 3. 限额与集中度
    exposure = facts.get("exposure")
    if exposure and exposure.ok and exposure.data:
        e = exposure.data[0]
        limit, used = e.get("consolidated_exposure_limit"), e.get("total_utilized")
        if limit and used is not None:
            ratio = used / limit
            if ratio > 1.0:
                flags.append(Flag("error", "集团敞口超限", "限额与集中度政策#单一集团限额",
                                  f"合并敞口 {_money(used)} 超限额 {_money(limit)}（{ratio:.1%}）"))
            elif ratio >= 0.8:
                flags.append(Flag("warning", "集中度预警", "限额与集中度政策#集中度预警",
                                  f"合并敞口使用率 {ratio:.1%} ≥ 80%"))
    return flags


def check_compliance(state: MemoState) -> dict:
    """第 2 步：政策比对。"""
    ent = state.get("entity")
    if ent is None:
        return {"compliance": []}
    return {"compliance": build_compliance_flags(ent, state["facts"])}


def _money(v) -> str:
    try:
        return f"{float(v) / 1_000_000:,.2f} 百万"
    except (TypeError, ValueError):
        return str(v)


def _tr(facts: dict[str, ToolResult], key: str) -> ToolResult:
    return facts.get(key, ToolResult.failure("未采集"))


def compose_report(state: MemoState) -> dict:
    """第 3 步：成文。结构化事实确定性成文，结论段尝试 LLM（失败降级规则摘要）。"""
    ent = state["entity"]
    assert ent is not None, "compose_report 需要已消歧的实体"
    facts = state["facts"]
    flags: list[Flag] = state.get("compliance", [])
    gaps: list[str] = []
    sections: list[Section] = []

    overview = _tr(facts, "overview")
    row = overview.data[0] if overview.ok and overview.data else {}

    # 1. 概况
    if overview.ok and row:
        sections.append(Section(
            title=SECTION_TITLES[0],
            content=(f"借款人：{row.get('borrower_name') or ent.name}；"
                     f"所属集团：{row.get('group_name') or '—'}；"
                     f"行业：{row.get('industry') or '—'}；"
                     f"法律形式：{row.get('legal_type') or '—'}；"
                     f"国家/地区：{row.get('country') or '—'}。"),
            citations=[f"[t:dim_borrower#{row.get('borrower_id', '')}]"],
        ))
    else:
        gaps.append("借款人概况数据缺失")
        sections.append(Section(title=SECTION_TITLES[0], content="无数据"))

    # 2. 评级
    ratings = _tr(facts, "ratings")
    if ratings.ok and ratings.data:
        lines, cites = [], set()
        for r in ratings.data:
            current = "当前" if r.get("valid_to") is None else "历史"
            lines.append(f"- {r.get('agency')} {r.get('grade')}"
                         f"（{current}，展望 {r.get('outlook') or '—'}）")
            cites.add(f"[t:fact_rating#{r.get('rating_id')}]")
        sections.append(Section(title=SECTION_TITLES[1], content="\n".join(lines),
                                citations=sorted(cites)))
    else:
        gaps.append("评级数据缺失")
        sections.append(Section(title=SECTION_TITLES[1], content="无数据"))

    # 3. 授信方案
    facilities = _tr(facts, "facilities")
    if facilities.ok and facilities.data:
        mains: dict[int, dict] = {}
        subs: dict[int, list[dict]] = {}
        for f in facilities.data:
            mid = f["main_facility_id"]
            mains.setdefault(mid, f)
            if f.get("sub_facility_id"):
                subs.setdefault(mid, []).append(f)
        lines = []
        for mid, f in mains.items():
            lines.append(f"- {f.get('facility_name')}"
                         f"（{f.get('facility_type')}，{f.get('currency')}，"
                         f"{_money(f.get('committed_amount'))}，到期 {f.get('maturity_date')}）")
            for s in subs.get(mid, []):
                lines.append(f"  · 子额度 {s.get('sub_type')}："
                             f"限额 {_money(s.get('limit_amount'))}，"
                             f"已用 {_money(s.get('utilization_amount'))}")
        sections.append(Section(title=SECTION_TITLES[2], content="\n".join(lines),
                                citations=[f"[t:dim_main_facility#{mains[m]['main_facility_id']}]"
                                           for m in mains]))
    else:
        gaps.append("授信方案数据缺失")
        sections.append(Section(title=SECTION_TITLES[2], content="无数据"))

    # 4. 敞口与限额
    exposure = _tr(facts, "exposure")
    if exposure.ok and exposure.data:
        e = exposure.data[0]
        sections.append(Section(
            title=SECTION_TITLES[3],
            content=(f"集团合并敞口限额：{_money(e.get('consolidated_exposure_limit'))}；"
                     f"当前已用敞口：{_money(e.get('total_utilized'))}"),
            citations=[f"[t:dim_borrowing_group#{e.get('group_id')}]",
                       "[t:fact_utilization]"],
        ))
    else:
        gaps.append("敞口数据缺失")
        sections.append(Section(title=SECTION_TITLES[3], content="无数据"))

    # 5. 相关方与担保
    parties = _tr(facts, "parties")
    if parties.ok and parties.data:
        lines = [f"- {p.get('role')}：{p.get('party_name')}"
                 + (f"（持股 {p.get('ownership_pct')}%）" if p.get("ownership_pct") else "")
                 for p in parties.data]
        sections.append(Section(title=SECTION_TITLES[4], content="\n".join(lines),
                                citations=["[t:dim_involved_party]"]))
    else:
        gaps.append("相关方数据缺失")
        sections.append(Section(title=SECTION_TITLES[4], content="无数据"))

    # 6. 政策合规核验
    if flags:
        sections.append(Section(
            title=SECTION_TITLES[5],
            content="\n".join(f"- [{f.level}] {f.rule}：{f.detail}" for f in flags),
            citations=sorted({f"[p:{f.policy_ref}]" for f in flags}),
        ))
    else:
        sections.append(Section(title=SECTION_TITLES[5], content="未命中任何合规限制规则"))

    # 7. 风险点与结论（LLM 合成，失败降级）
    conclusion, concl_cites, flag_txt = _synthesize_conclusion(ent, flags)
    if flags:
        conclusion += "\n\n合规结论明细：\n" + flag_txt
    sections.append(Section(title=SECTION_TITLES[6], content=conclusion, citations=concl_cites))

    # 数据缺口声明（结果校验：不编造财务数据）
    gaps.append("无财务数据（当前数据模型未覆盖财务报表，需人工补充）")
    if not _tr(facts, "policy").ok:
        gaps.append("政策文档检索不可用，合规核验仅基于确定性规则")

    report = CreditMemo(
        entity_name=ent.name,
        sections=sections,
        compliance_flags=[f"[{f.level}] {f.rule}" for f in flags],
        data_gaps=gaps,
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
    )
    return {"report": report, "compose_attempts": state.get("compose_attempts", 0) + 1}


def _synthesize_conclusion(ent: Entity, flags: list[Flag]) -> tuple[str, list[str], str]:
    """风险点与结论：LLM 成文，失败降级为规则摘要。"""
    detail_lines = [f"- [{f.level}] {f.rule}：{f.detail}" for f in flags]
    flag_txt = "\n".join(detail_lines) or "- 未命中任何规则"
    base = "\n".join(detail_lines) or "未命中任何合规限制规则"
    system = ("你是资深信贷分析师。基于给定事实与合规结论，用一段不超过 150 字的话概括该客户"
              "授信风险点与结论，不要编造未提供的事实。")
    user = f"主体：{ent.name}\n合规结论：\n{base}"
    try:
        text = LLMClient().complete(system, user)
        return text, ["[llm]"], flag_txt
    except ToolError:
        return f"（LLM 合成不可用，以下为规则结论）\n{base}", [], flag_txt


def validate_report(state: MemoState) -> dict:
    """第 4 步：结果校验（章节完整性 + 引用覆盖率）。"""
    report = state.get("report")
    if report is None:
        return {"validation_errors": ["报告未生成"]}
    errs: list[str] = []
    have = {s.title for s in report.sections}
    missing = [t for t in SECTION_TITLES if t not in have]
    if missing:
        errs.append(f"缺章节: {', '.join(missing)}")
    cov = _citation_coverage(report)
    if cov < 0.9:
        errs.append(f"引用覆盖率不足: {cov:.0%}")
    return {"validation_errors": errs}


def _citation_coverage(report: CreditMemo) -> float:
    """除「风险点与结论」外，其余章节需带引用。"""
    must = [s for s in report.sections if s.title != SECTION_TITLES[6]]
    if not must:
        return 0.0
    return sum(1 for s in must if s.citations) / len(must)


def route_after_resolve(state: MemoState) -> str:
    return "collect_facts" if state.get("entity") is not None else END


def route_after_validate(state: MemoState) -> str:
    if state.get("validation_errors") and state.get("compose_attempts", 0) < 2:
        return "compose_report"
    return END


def build_graph():
    """构建确定性 DAG。"""
    g = StateGraph(MemoState)
    g.add_node("resolve_entity", resolve_entity)
    g.add_node("collect_facts", collect_facts)
    g.add_node("check_compliance", check_compliance)
    g.add_node("compose_report", compose_report)
    g.add_node("validate_report", validate_report)

    g.add_edge(START, "resolve_entity")
    g.add_conditional_edges("resolve_entity", route_after_resolve,
                            {"collect_facts": "collect_facts", END: END})
    g.add_edge("collect_facts", "check_compliance")
    g.add_edge("check_compliance", "compose_report")
    g.add_edge("compose_report", "validate_report")
    g.add_conditional_edges("validate_report", route_after_validate,
                            {"compose_report": "compose_report", END: END})
    return g.compile()


def initial_state(query: str) -> MemoState:
    """构建完整初始状态（供 run_report / API 流式复用）。"""
    return {
        "query": query,
        "entity": None,
        "facts": {},
        "compliance": [],
        "report": None,
        "validation_errors": [],
        "compose_attempts": 0,
    }


def run_report(query: str) -> CreditMemo:
    """入口：运行报告生成，始终返回结构化 CreditMemo（失败时返回带错误说明的 memo）。"""
    graph = build_graph()
    result = graph.invoke(initial_state(query))
    report = result.get("report")
    if report is not None:
        return report
    errs = result.get("validation_errors", []) or ["未知错误"]
    return CreditMemo(
        entity_name=extract_entity_hint(query) or query,
        sections=[Section(title="生成失败", content="；".join(errs))],
        data_gaps=errs,
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
    )
