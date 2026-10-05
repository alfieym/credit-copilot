"""政策检索（RAG-lite）：分块 + BM25 命中。"""
from __future__ import annotations

from credit_copilot.tools.policy_search import load_chunks, search_policy_docs


def test_load_chunks():
    chunks = load_chunks()
    assert len(chunks) >= 8  # 4 篇文档 × ≥2 章节


def test_search_realestate_hits_industry_policy():
    r = search_policy_docs("房地产 集团敞口")
    assert r.ok is True
    docs = {c.doc_title for c, _ in r.data}
    assert any("行业准入" in d for d in docs)


def test_search_empty_query_degrades():
    r = search_policy_docs("")
    assert r.ok is True
