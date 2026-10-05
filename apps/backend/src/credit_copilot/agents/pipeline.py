"""确定性管线（任务拆解① + 结果校验④）：无 LLM 参与的事实采集与规则层。

OpenAI Agents SDK 是 agent-loop 框架，没有「确定性 DAG」原语，因此
resolve → collect → 规则 → 校验 的确定性流程放在显式 Python 函数里；
SDK 只负责 LLM 成文步（memo_agent.synthesize_conclusion）与 output guardrail。
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from credit_copilot.agents.memo_agent import synthesize_conclusion
from credit_copilot.agents.models import (
    SECTION_TITLES,
    CreditMemo,
    Entity,
    EntityResolutionError,
    Flag,
    Section,
    _grade_at_or_below,
    extract_entity_hint,
)
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


def resolve_entity(query: str) -> Entity:
    """实体消歧（结果校验第 2 关）：0 命中 / >1 命中 → 抛 EntityResolutionError。"""
    hint = extract_entity_hint(query)
    if not hint:
        raise EntityResolutionError("无法从问题中识别主体名称")
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
        raise EntityResolutionError(f"未找到主体「{hint}」")
    if len(candidates) > 1:
        names = "、".join(c.name for c in candidates)
        raise EntityResolutionError(
            f"名称歧义，命中 {len(candidates)} 个主体：{names}，请精确指定", candidates
        )
    return candidates[0]


def collect_facts(entity: Entity) -> dict[str, ToolResult]:
    """并行 fan-out 取各章节事实（DB + RAG），单章失败降级不击穿。"""
    facts: dict[str, ToolResult] = {}
    overview = (get_borrower_overview(entity.id) if entity.kind == "borrower"
                else get_group_overview(entity.id))
    facts["overview"] = overview
    row = overview.data[0] if overview.ok and overview.data else {}
    group_id = row.get("group_id") or entity.group_id
    industry = row.get("industry") or row.get("group_industry") or ""
    name = row.get("borrower_name") or row.get("group_name") or entity.name

    tasks: dict[str, Callable[[], ToolResult]] = {
        "ratings": lambda: get_ratings("borrower", entity.id) if entity.kind == "borrower"
        else get_ratings("group", entity.id),
        "facilities": lambda: get_facilities(entity.id) if entity.kind == "borrower"
        else ToolResult.failure("集团主体无单户额度明细"),
        "exposure": lambda: (get_exposure(group_id) if group_id
                             else ToolResult.failure("无关联集团")),
        "parties": lambda: get_involved_parties(entity.id) if entity.kind == "borrower"
        else ToolResult.failure("集团主体无单户相关方"),
        "policy": lambda: search_policy_docs(f"{industry} {name}"),
    }
    if entity.kind == "borrower" and group_id is not None:
        tasks["group"] = lambda: get_group_overview(group_id)

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {key: ex.submit(fn) for key, fn in tasks.items()}
        for key, fut in futures.items():
            try:
                facts[key] = fut.result(timeout=30)
            except Exception as e:  # noqa: BLE001 —— 兜底：任何意外都降级为失败
                facts[key] = ToolResult.failure(f"意外异常: {e}", fallback=True)
    return facts


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


def _money(v) -> str:
    try:
        return f"{float(v) / 1_000_000:,.2f} 百万"
    except (TypeError, ValueError):
        return str(v)


def _tr(facts: dict[str, ToolResult], key: str) -> ToolResult:
    return facts.get(key, ToolResult.failure("未采集"))


def compose_report(entity: Entity, facts: dict[str, ToolResult], flags: list[Flag]) -> CreditMemo:
    """成文：1-6 章确定性拼装，第 7 章结论走 LLM（失败降级为规则摘要）。"""
    gaps: list[str] = []
    sections: list[Section] = []

    overview = _tr(facts, "overview")
    row = overview.data[0] if overview.ok and overview.data else {}

    # 1. 概况
    if overview.ok and row:
        sections.append(Section(
            title=SECTION_TITLES[0],
            content=(f"借款人：{row.get('borrower_name') or entity.name}；"
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
    conclusion, concl_cites, flag_txt = synthesize_conclusion(entity, flags)
    if flags:
        conclusion += "\n\n合规结论明细：\n" + flag_txt
    sections.append(Section(title=SECTION_TITLES[6], content=conclusion, citations=concl_cites))

    # 数据缺口声明（结果校验：不编造财务数据）
    gaps.append("无财务数据（当前数据模型未覆盖财务报表，需人工补充）")
    if not _tr(facts, "policy").ok:
        gaps.append("政策文档检索不可用，合规核验仅基于确定性规则")

    return CreditMemo(
        entity_name=entity.name,
        sections=sections,
        compliance_flags=[f"[{f.level}] {f.rule}" for f in flags],
        data_gaps=gaps,
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
    )


def validate_report(report: CreditMemo) -> list[str]:
    """结果校验（章节完整性 + 引用覆盖率）。"""
    errs: list[str] = []
    have = {s.title for s in report.sections}
    missing = [t for t in SECTION_TITLES if t not in have]
    if missing:
        errs.append(f"缺章节: {', '.join(missing)}")
    cov = _citation_coverage(report)
    if cov < 0.9:
        errs.append(f"引用覆盖率不足: {cov:.0%}")
    return errs


def _citation_coverage(report: CreditMemo) -> float:
    """除「风险点与结论」外，其余章节需带引用。"""
    must = [s for s in report.sections if s.title != SECTION_TITLES[6]]
    if not must:
        return 0.0
    return sum(1 for s in must if s.citations) / len(must)
