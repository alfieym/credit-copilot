"""Policy-document search (RAG-lite): chunking + BM25 keyword scoring.

The other half of tool-calling: policy constraints are retrieved rather than held in
LLM memory. Currently a pure offline BM25 (no embedding key needed, consistent with
the degradation principle); phase 1 can layer a BGE-M3 vector pre-filter + rerank on top.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from credit_copilot.tools.base import ToolResult

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs" / "policy"

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class Chunk:
    """A policy chunk that can be cited."""

    id: str          # e.g. "rating-access-policy#Rating Threshold"
    doc_title: str
    text: str

    def cite(self) -> str:
        return f"[p:{self.id}]"


def _tokenize(text: str) -> list[str]:
    """Simple English word tokenization (lowercased)."""
    return _WORD_RE.findall(text.lower())


def load_chunks(docs_dir: Path = DOCS_DIR) -> list[Chunk]:
    """Split ``docs/policy/*.md`` into chunks on ``## `` headings."""
    chunks: list[Chunk] = []
    for path in sorted(docs_dir.glob("*.md")):
        title = path.stem
        # strip the numeric filename prefix
        # ("01-industry-access-policy" -> "industry-access-policy")
        title = re.sub(r"^\d+-", "", title)
        text = path.read_text(encoding="utf-8")
        # drop the leading h1 title line, then split on "## " headings
        text = re.sub(r"(?m)^#\s+.*\n?", "", text)
        for part in re.split(r"(?m)^##\s+", text):
            part = part.strip()
            if not part:
                continue
            lines = part.splitlines()
            heading = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            if not body:
                continue
            chunks.append(Chunk(id=f"{title}#{heading}", doc_title=title, text=body))
    return chunks


@lru_cache(maxsize=1)
def _index() -> tuple[list[Chunk], dict[str, int], dict[str, list[str]], float]:
    """Build a lightweight index: chunks, df, per-chunk token counts, and average length."""
    chunks = load_chunks()
    df: dict[str, int] = {}
    chunk_tokens: dict[str, list[str]] = {}
    for c in chunks:
        toks = _tokenize(c.text)
        chunk_tokens[c.id] = toks
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    avg_len = sum(len(v) for v in chunk_tokens.values()) / max(len(chunks), 1)
    return chunks, df, chunk_tokens, avg_len


def _bm25(query: str, top_k: int) -> list[tuple[Chunk, float]]:
    chunks, df, chunk_tokens, avg_len = _index()
    n = len(chunks)
    qtoks = _tokenize(query)
    scored: list[tuple[Chunk, float]] = []
    k1, b = 1.5, 0.75
    for c in chunks:
        toks = chunk_tokens[c.id]
        len_c = len(toks)
        score = 0.0
        for t in qtoks:
            tf = toks.count(t)
            if tf == 0:
                continue
            idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * len_c / avg_len))
        if score > 0:
            scored.append((c, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def search_policy_docs(query: str, *, top_k: int = 5) -> ToolResult:
    """Search policy chunks, returning a :class:`ToolResult`
    (internal errors degrade gracefully)."""
    try:
        hits = _bm25(query, top_k)
        return ToolResult.success([(c, s) for c, s in hits])
    except Exception as e:  # noqa: BLE001 — retrieval failure must not break the report; degrade to empty
        return ToolResult.failure(f"Policy search failed: {e}", fallback=True)
