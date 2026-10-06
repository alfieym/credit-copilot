"""Policy search (RAG-lite): chunking + BM25 hits."""
from __future__ import annotations

from credit_copilot.tools.policy_search import load_chunks, search_policy_docs


def test_load_chunks():
    chunks = load_chunks()
    assert len(chunks) >= 8  # 4 docs × ≥2 sections


def test_search_realestate_hits_industry_policy():
    r = search_policy_docs("real estate group exposure")
    assert r.ok is True
    docs = {c.doc_title for c, _ in r.data}
    assert any("industry-access" in d for d in docs)


def test_search_empty_query_degrades():
    r = search_policy_docs("")
    assert r.ok is True
