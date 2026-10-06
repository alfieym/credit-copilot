"""First scenario: entity resolution + compliance rules + drafting + result
validation (all testable offline)."""
from __future__ import annotations

from credit_copilot.agents.models import CreditMemo, Entity, Section, extract_entity_hint
from credit_copilot.agents.pipeline import (
    _citation_coverage,
    build_compliance_flags,
    compose_report,
    validate_report,
)
from credit_copilot.tools.base import ToolResult


# --- Entity resolution ------------------------------------------------------
def test_extract_entity_hint_quoted():
    assert extract_entity_hint("生成『恒远汽车零部件』的授信尽调报告") == "恒远汽车零部件"


def test_extract_entity_hint_plain():
    assert extract_entity_hint("生成恒远汽车零部件的授信尽调报告") == "恒远汽车零部件"


def test_extract_entity_hint_english():
    assert extract_entity_hint("generate a report for Huayu Auto Parts") == "Huayu Auto Parts"
    assert extract_entity_hint("analyze Meridian Global Holdings") == "Meridian Global Holdings"


# --- Compliance rules (the rule layer of result validation) -----------------
def _facts(overview=None, ratings=None, exposure=None):
    return {
        "overview": ToolResult.success([overview or {}]),
        "ratings": ToolResult.success(ratings or []),
        "exposure": ToolResult.success(exposure or []),
    }


def test_compliance_rating_and_exposure_flags():
    ent = Entity(kind="borrower", id=1, name_en="X")
    facts = _facts(
        overview={"industry": "Energy"},
        ratings=[{"agency": "internal", "grade": "B", "outlook": "Negative", "valid_to": None}],
        exposure=[{"consolidated_exposure_limit": 100_000_000, "total_utilized": 85_000_000}],
    )
    rules = {f.rule for f in build_compliance_flags(ent, facts)}
    assert "Rating Access Threshold" in rules
    assert "Negative Rating Outlook" in rules
    assert "Concentration Warning" in rules


def test_compliance_realestate_flag():
    ent = Entity(kind="borrower", id=1, name_en="X")
    facts = _facts(overview={"industry": "Real Estate"})
    flags = build_compliance_flags(ent, facts)
    assert any(f.rule == "Real Estate Access Restriction" for f in flags)


def test_compliance_no_flags_for_clean():
    ent = Entity(kind="borrower", id=1, name_en="X")
    facts = _facts(
        overview={"industry": "Technology"},
        ratings=[{"agency": "internal", "grade": "AA", "outlook": "Stable", "valid_to": None}],
        exposure=[{"consolidated_exposure_limit": 100_000_000, "total_utilized": 10_000_000}],
    )
    assert build_compliance_flags(ent, facts) == []


# --- Drafting (offline degradation) -----------------------------------------
def test_compose_report_full_offline():
    ent = Entity(kind="borrower", id=1001, name_cn="恒远汽车零部件有限责任公司",
                 name_en="Hengyuan Auto Parts Co., Ltd.")
    facts = {
        "overview": ToolResult.success([{
            "borrower_id": 1001, "borrower_name_cn": "恒远汽车零部件有限责任公司",
            "borrower_name_en": "Hengyuan Auto Parts Co., Ltd.",
            "group_name_cn": "恒远控股集团", "group_name_en": "Hengyuan Holdings Group",
            "industry": "Automotive", "legal_type": "Co., Ltd.", "country": "CN",
        }]),
        "ratings": ToolResult.success([{
            "rating_id": 1, "agency": "internal", "grade": "AA",
            "outlook": "Stable", "valid_to": None,
        }]),
        "facilities": ToolResult.success([{
            "main_facility_id": 2001, "facility_name": "Working Capital · Revolving",
            "facility_type": "Revolving", "currency": "CNY",
            "committed_amount": 50_000_000, "maturity_date": "2027-01-01",
            "sub_facility_id": None,
        }]),
        "exposure": ToolResult.success([{
            "group_id": 1, "consolidated_exposure_limit": 1_000_000_000,
            "total_utilized": 500_000_000,
        }]),
        "parties": ToolResult.success([{
            "role": "borrower", "party_name": "Hengyuan Auto Parts Co., Ltd.",
            "ownership_pct": None,
        }]),
        "policy": ToolResult.success([]),
    }
    memo = compose_report(ent, facts, [])

    assert len(memo.sections) == 7
    assert memo.entity_name == ent.name
    # LLM unavailable -> conclusion degrades to a rule summary
    assert "LLM synthesis unavailable" in memo.sections[-1].content
    # Data-gap disclosure explicitly states there is no financial data (never fabricate)
    assert any("No financial data" in g for g in memo.data_gaps)


# --- Result validation ------------------------------------------------------
def test_validate_report_missing_section():
    memo = CreditMemo(
        entity_name="X",
        sections=[Section(title="Ratings", content="x", citations=["[t:x]"])],
    )
    errs = validate_report(memo)
    assert any("Missing sections" in e for e in errs)


def test_citation_coverage_excludes_conclusion():
    memo = CreditMemo(entity_name="X", sections=[
        Section(title="Borrower & Group Overview", content="x", citations=["[t:a]"]),
        Section(title="Risk Points & Conclusion", content="x"),  # conclusion not in coverage
    ])
    assert _citation_coverage(memo) == 1.0
