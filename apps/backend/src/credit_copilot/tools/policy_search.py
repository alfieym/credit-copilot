"""政策文档检索（RAG-lite）：分块 + BM25 关键词打分。

「工具调用」的另一半：政策约束走检索而非 LLM 记忆。当前为纯离线 BM25
（无需 embedding key，符合降级原则）；阶段1 可在此之上叠加 BGE-M3 向量初筛 + 重排。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from credit_copilot.tools.base import ToolResult

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs" / "policy"

_CJK_RE = re.compile(r"[一-鿿]+")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class Chunk:
    """一个政策 chunk：可被引用（citation）。"""

    id: str          # 形如 "评级准入政策#评级准入线"
    doc_title: str
    text: str

    def cite(self) -> str:
        return f"[p:{self.id}]"


def _tokenize(text: str) -> list[str]:
    """简单分词：ASCII 词 + CJK 二元组（覆盖中文短语匹配）。"""
    tokens = _WORD_RE.findall(text.lower())
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens += [run[i : i + 2] for i in range(len(run) - 1)]
    return tokens


def load_chunks(docs_dir: Path = DOCS_DIR) -> list[Chunk]:
    """把 ``docs/policy/*.md`` 按 ``## `` 标题分块。"""
    chunks: list[Chunk] = []
    for path in sorted(docs_dir.glob("*.md")):
        title = path.stem
        # 去掉文件名里的序号前缀（"01-行业准入政策" -> "行业准入政策"）
        title = re.sub(r"^\d+-", "", title)
        text = path.read_text(encoding="utf-8")
        # 去掉开头的 h1 标题行，再按 "## " 标题切块
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
    """构建轻量索引：chunks、df、每个 chunk 的 token 计数、平均长度。"""
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
    """检索政策 chunk，返回 :class:`ToolResult`（内部异常统一降级）。"""
    try:
        hits = _bm25(query, top_k)
        return ToolResult.success([(c, s) for c, s in hits])
    except Exception as e:  # noqa: BLE001 —— 检索失败不击穿报告，降级为空
        return ToolResult.failure(f"政策检索失败: {e}", fallback=True)
