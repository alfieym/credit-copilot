"""FastAPI 接口层：报告生成（同步 JSON + SSE 流式进度）。"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from credit_copilot.agents.orchestrator import run_report, run_report_stream

app = FastAPI(title="信贷分析师 Copilot", version="0.1.0")

# 前端（Next.js）直连：开发期放行任意源，生产收紧为 NEXT_PUBLIC_API_BASE_URL 所在域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReportRequest(BaseModel):
    query: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/report")
def report(req: ReportRequest) -> dict:
    """同步生成授信尽调报告，返回结构化 JSON。"""
    memo = run_report(req.query)
    return memo.model_dump()


def _sse(event: str, data: dict) -> str:
    return f"data: {json.dumps({'event': event, **data}, ensure_ascii=False)}\n\n"


async def _stream(query: str) -> AsyncGenerator[str, None]:
    """流式进度：start → 逐阶段 → done/error。"""
    yield _sse("start", {"query": query})
    try:
        for stage in run_report_stream(query):
            if stage.get("status") == "error":
                yield _sse("error", {"message": stage.get("message", "未知错误"),
                                     "candidates": stage.get("candidates", [])})
                return
            if "report" in stage:
                yield _sse("done", {"report": stage["report"].model_dump()})
            else:
                yield _sse("node", {"stage": stage["stage"], "status": stage["status"]})
    except Exception as e:  # noqa: BLE001 —— 任何异常都以 SSE error 事件返回
        yield _sse("error", {"message": str(e)})


@app.post("/report/stream")
def report_stream(req: ReportRequest) -> StreamingResponse:
    """SSE 流式生成授信尽调报告。"""
    return StreamingResponse(_stream(req.query), media_type="text/event-stream")
