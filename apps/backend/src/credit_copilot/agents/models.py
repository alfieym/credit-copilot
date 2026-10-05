"""领域模型与确定性辅助（无框架依赖，可独立测试）。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

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


class EntityResolutionError(Exception):
    """实体消歧失败：0 命中或 >1 命中。

    等价于 OpenAI Agents SDK 的 input guardrail tripwire——在 Agent 运行前
    就拦截，避免「硬猜」错误主体。
    """

    def __init__(self, message: str, candidates: list[Entity] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.candidates = candidates or []


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
