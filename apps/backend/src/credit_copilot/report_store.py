"""Report persistence: write a generated CreditMemo to a JSON file (optional save)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from credit_copilot.agents.models import CreditMemo

# The data directory lives under apps/backend/data; this file is at src/credit_copilot/,
# so parents[2] resolves to apps/backend.
REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"

# Characters that must not appear in a filename (cross-platform safety), replaced with underscores.
_INVALID = re.compile(r'[\\/:*?"<>|\s]+')


def _slugify(name: str) -> str:
    return _INVALID.sub("_", name).strip("._")


def save_report(memo: CreditMemo, reports_dir: Path | None = None) -> Path:
    """Write the report to JSON and return the path; creates the directory if missing.

    ``reports_dir`` defaults to REPORTS_DIR; tests may pass tmp_path
    to avoid polluting the real directory.
    """
    base = reports_dir or REPORTS_DIR
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = base / f"{_slugify(memo.entity_name)}_{stamp}.json"
    path.write_text(
        json.dumps(memo.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
