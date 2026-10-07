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

DOCS_DIR = Path(__file__).resolve().parents[5] / "docs" / "policy"

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class Chunk:
    """A policy chunk that can be cited."""

    id: str          # e.g. "rating-access-policy#Rating Threshold"
    doc_title: str
    text: str

    def cite(self) -> str:
        """Render this chunk as an inline citation (e.g. ``[p:policy#Heading]``).

        Implementation: ``f"[p:{self.id}]"`` — ``id`` is ``{title}#{heading}``.
        """
        return f"[p:{self.id}]"


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercased English word tokens.

    Implementation: ``_WORD_RE.findall(text.lower())`` — only ``[A-Za-z0-9_]+`` runs are
    kept, so punctuation and CJK are dropped (English-only BM25).
    """
    return _WORD_RE.findall(text.lower())


def load_chunks(docs_dir: Path = DOCS_DIR) -> list[Chunk]:
    """Load and split ``docs/policy/*.md`` into citable :class:`Chunk` objects.

    Implementation: for each ``*.md`` file, strip the numeric filename prefix
    (``01-…`` → ``…``), drop the leading ``# `` title line, split the body on ``## ``
    headings, and build ``Chunk(id=f"{title}#{heading}")`` per non-empty body.
    """
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
    """Build (and cache) the BM25 index.

    Implementation: tokenize every chunk once, then compute document frequency (``df``),
    per-chunk token lists (``chunk_tokens``), and the average chunk length. Cached via
    ``@lru_cache`` so the corpus is read only once per process.
    """
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
    """Rank chunks with the BM25 scoring function and return the top-k.

    Implementation: for each chunk compute ``Σ idf * (tf*(k1+1)) / (tf + k1*(1 - b +
    b*len/avg_len))`` over the query terms (k1=1.5, b=0.75), keep non-zero scores, sort
    descending, and slice to ``top_k``.
    """
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
    """Search the policy corpus and return the hits as a :class:`ToolResult`.

    Implementation: delegates to ``_bm25`` and wraps ``(Chunk, score)`` pairs in a
    successful result; any internal error is caught and returned as a
    ``fallback_applied`` failure so a retrieval failure never breaks the report.
    """
    try:
        hits = _bm25(query, top_k)
        return ToolResult.success([(c, s) for c, s in hits])
    except Exception as e:  # noqa: BLE001 — retrieval failure must not break the report; degrade to empty
        return ToolResult.failure(f"Policy search failed: {e}", fallback=True)
