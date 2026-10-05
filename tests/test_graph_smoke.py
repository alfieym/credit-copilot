"""图编排冒烟测试：DAG 可编译（无需 DB/LLM）。"""
from __future__ import annotations

from credit_copilot.scenarios.credit_memo import build_graph


def test_graph_compiles():
    g = build_graph()
    assert g is not None
