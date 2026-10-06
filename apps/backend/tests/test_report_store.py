"""Report persistence: save_report writes JSON, names it as "entity_timestamp",
and sanitizes the filename."""
from __future__ import annotations

import json

from credit_copilot.agents.models import CreditMemo, Section
from credit_copilot.report_store import save_report


def test_save_report_writes_json(tmp_path):
    memo = CreditMemo(
        entity_name="Huayu Auto Parts Co., Ltd. (华宇汽车零部件有限责任公司)",
        sections=[Section(title="Borrower & Group Overview", content="x", citations=["[t:1]"])],
        compliance_flags=["Rating Access Threshold"],
        data_gaps=["No financial data"],
        generated_at="2026-10-06T12:00:00",
    )
    path = save_report(memo, reports_dir=tmp_path)

    assert path.exists()
    assert path.name.startswith("Huayu_Auto_Parts_Co.")
    assert path.suffix == ".json"

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["entity_name"] == "Huayu Auto Parts Co., Ltd. (华宇汽车零部件有限责任公司)"
    assert len(data["sections"]) == 1
    assert data["compliance_flags"] == ["Rating Access Threshold"]


def test_save_report_slugifies_filename(tmp_path):
    memo = CreditMemo(entity_name="A/B:C*D?E", sections=[])
    path = save_report(memo, reports_dir=tmp_path)

    assert "/" not in path.name
    assert ":" not in path.name
    assert path.name.startswith("A_B_C_D_E_")
