"""Domain models and deterministic helpers (no framework dependency; independently testable)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

SECTION_TITLES = [
    "Borrower & Group Overview",
    "Ratings",
    "Credit Facilities",
    "Exposure & Limit Utilization",
    "Related Parties & Guarantees",
    "Policy & Compliance Check",
    "Risk Points & Conclusion",
]

GRADES = [
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
    "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-",
    "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D",
]
_GRADE_RANK = {g: i for i, g in enumerate(GRADES)}


def _grade_at_or_below(grade: str, boundary: str) -> bool:
    """Whether ``grade`` is at or below ``boundary``.

    Implementation: compares positions in ``_GRADE_RANK`` (a larger index is worse);
    unknown grades map to index 999 so they are treated as "at or below".
    """
    return _GRADE_RANK.get(grade, 999) >= _GRADE_RANK.get(boundary, 999)


@dataclass
class Entity:
    kind: str                 # "borrower" / "group"
    id: int
    name_cn: str = ""
    name_en: str = ""
    group_id: int | None = None

    @property
    def name(self) -> str:
        """Display name: English first, with the Chinese name in parentheses when present.

        Implementation: ``f"{name_en} ({name_cn})"`` when a Chinese name exists, else
        just ``name_en``.
        """
        return f"{self.name_en} ({self.name_cn})" if self.name_cn else self.name_en


@dataclass
class Flag:
    level: str                # error / warning / info
    rule: str
    policy_ref: str           # e.g. "rating-access-policy#Rating Threshold"
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


class EntityResolutionError(Exception):
    """Entity-resolution failure: 0 matches or >1 match.

    Equivalent to an OpenAI Agents SDK input-guardrail tripwire: it intercepts
    before the agent runs, avoiding a hard "guess" at the wrong entity.
    """

    def __init__(self, message: str, candidates: list[Entity] | None = None) -> None:
        """Initialize the exception.

        Implementation: passes ``message`` to the parent ``Exception`` and keeps the
        ambiguous ``candidates`` so the API can relay them to the user.
        """
        super().__init__(message)
        self.message = message
        self.candidates = candidates or []


_QUOTED = re.compile(r"[『「《\"'`]([^』」》\"'`]+)[』」》\"'`]")

_CN_VERBS = ("生成", "撰写", "分析", "查询", "查")
_CN_SUFFIXES = ("的授信尽调报告", "授信尽调报告", "的尽调报告", "尽调报告",
                "授信报告", "的报告")

_EN_LEADING = re.compile(
    r"(?i)^(please\s+)?(generate|create|write|analyze|query|make|produce)\b\s*"
    r"(a\s+|an\s+|the\s+)?(credit\s+|due[\s-]*diligence\s+)?(report|memo)\s+(for|of|about|on)\s+"
)
_EN_LEADING_VERB = re.compile(
    r"(?i)^(please\s+)?(generate|create|write|analyze|query|make|produce)\b\s*"
)
_EN_TRAILING = re.compile(r"(?i)\s+(credit\s+|due[\s-]*diligence\s+)?(report|memo)\.?\s*$")


def extract_entity_hint(query: str) -> str:
    """Extract the entity name from a query (bilingual deterministic heuristic).

    Implementation: (1) quoted names win (``_QUOTED``); (2) strip a leading Chinese verb
    and a trailing Chinese report suffix; (3) strip English leading patterns
    (``generate a report for …``) and a trailing ``report``/``memo``; then trim
    surrounding punctuation/whitespace.
    """
    m = _QUOTED.search(query)
    if m:
        return m.group(1).strip()
    hint = query.strip()

    # Chinese: strip a leading verb, then a trailing report suffix.
    for verb in _CN_VERBS:
        if hint.startswith(verb):
            hint = hint[len(verb):].lstrip()
            break
    for suffix in _CN_SUFFIXES:
        if hint.endswith(suffix):
            hint = hint[: -len(suffix)].rstrip()
            break

    # English: strip "generate a report for …" / "analyze …" prefixes and a trailing "report".
    hint = _EN_LEADING.sub("", hint)
    hint = _EN_LEADING_VERB.sub("", hint)
    hint = _EN_TRAILING.sub("", hint)

    return hint.strip(" \t\n，。,:：")
