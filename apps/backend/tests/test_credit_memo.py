"""首个场景：实体消歧 + 合规规则 + 成文 + 结果校验（均离线可测）。"""
from __future__ import annotations

from credit_copilot.agents.models import CreditMemo, Entity, Section, extract_entity_hint
from credit_copilot.agents.pipeline import (
    _citation_coverage,
    build_compliance_flags,
    compose_report,
    validate_report,
)
from credit_copilot.tools.base import ToolResult


# --- 实体消歧 ---------------------------------------------------------------
def test_extract_entity_hint_quoted():
    assert extract_entity_hint("生成『恒远汽车零部件』的授信尽调报告") == "恒远汽车零部件"


def test_extract_entity_hint_plain():
    assert extract_entity_hint("生成恒远汽车零部件的授信尽调报告") == "恒远汽车零部件"


# --- 合规规则（结果校验规则层） ---------------------------------------------
def _facts(overview=None, ratings=None, exposure=None):
    return {
        "overview": ToolResult.success([overview or {}]),
        "ratings": ToolResult.success(ratings or []),
        "exposure": ToolResult.success(exposure or []),
    }


def test_compliance_rating_and_exposure_flags():
    ent = Entity(kind="borrower", id=1, name="X")
    facts = _facts(
        overview={"industry": "能源"},
        ratings=[{"agency": "internal", "grade": "B", "outlook": "Negative", "valid_to": None}],
        exposure=[{"consolidated_exposure_limit": 100_000_000, "total_utilized": 85_000_000}],
    )
    rules = {f.rule for f in build_compliance_flags(ent, facts)}
    assert "评级准入线" in rules
    assert "评级展望负面" in rules
    assert "集中度预警" in rules


def test_compliance_realestate_flag():
    ent = Entity(kind="borrower", id=1, name="X")
    facts = _facts(overview={"industry": "房地产"})
    flags = build_compliance_flags(ent, facts)
    assert any(f.rule == "房地产行业准入" for f in flags)


def test_compliance_no_flags_for_clean():
    ent = Entity(kind="borrower", id=1, name="X")
    facts = _facts(
        overview={"industry": "科技"},
        ratings=[{"agency": "internal", "grade": "AA", "outlook": "Stable", "valid_to": None}],
        exposure=[{"consolidated_exposure_limit": 100_000_000, "total_utilized": 10_000_000}],
    )
    assert build_compliance_flags(ent, facts) == []


# --- 成文（离线降级） -------------------------------------------------------
def test_compose_report_full_offline():
    ent = Entity(kind="borrower", id=1001, name="恒远汽车零部件有限责任公司")
    facts = {
        "overview": ToolResult.success([{
            "borrower_id": 1001, "borrower_name": "恒远汽车零部件有限责任公司",
            "group_name": "恒远控股集团", "industry": "汽车制造",
            "legal_type": "有限责任公司", "country": "CN",
        }]),
        "ratings": ToolResult.success([{
            "rating_id": 1, "agency": "internal", "grade": "AA",
            "outlook": "Stable", "valid_to": None,
        }]),
        "facilities": ToolResult.success([{
            "main_facility_id": 2001, "facility_name": "营运资金 · Revolving",
            "facility_type": "Revolving", "currency": "CNY",
            "committed_amount": 50_000_000, "maturity_date": "2027-01-01",
            "sub_facility_id": None,
        }]),
        "exposure": ToolResult.success([{
            "group_id": 1, "consolidated_exposure_limit": 1_000_000_000,
            "total_utilized": 500_000_000,
        }]),
        "parties": ToolResult.success([{
            "role": "borrower", "party_name": "恒远汽车零部件有限责任公司",
            "ownership_pct": None,
        }]),
        "policy": ToolResult.success([]),
    }
    memo = compose_report(ent, facts, [])

    assert len(memo.sections) == 7
    assert memo.entity_name == ent.name
    # LLM 不可用 → 结论段降级为规则摘要
    assert "LLM 合成不可用" in memo.sections[-1].content
    # 数据缺口明确声明无财务数据（不编造）
    assert any("无财务数据" in g for g in memo.data_gaps)


# --- 结果校验 ---------------------------------------------------------------
def test_validate_report_missing_section():
    memo = CreditMemo(
        entity_name="X",
        sections=[Section(title="评级情况", content="x", citations=["[t:x]"])],
    )
    errs = validate_report(memo)
    assert any("缺章节" in e for e in errs)


def test_citation_coverage_excludes_conclusion():
    memo = CreditMemo(entity_name="X", sections=[
        Section(title="借款人及集团概况", content="x", citations=["[t:a]"]),
        Section(title="风险点与结论", content="x"),  # 结论段不计入覆盖率
    ])
    assert _citation_coverage(memo) == 1.0
