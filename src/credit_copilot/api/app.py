"""FastAPI 接口层：报告生成（同步 JSON + SSE 流式进度）。"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from credit_copilot.scenarios.credit_memo import (
    build_graph,
    initial_state,
    run_report,
)

app = FastAPI(title="信贷分析师 Copilot", version="0.1.0")


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
    """流式进度：start → 逐节点 node → done/error。"""
    yield _sse("start", {"query": query})
    graph = build_graph()
    report_obj = None
    errors: list[str] = []
    try:
        for chunk in graph.stream(initial_state(query), stream_mode="updates"):
            node = next(iter(chunk))
            upd = chunk[node]
            if "report" in upd:
                report_obj = upd["report"]
            if "validation_errors" in upd:
                errors = upd["validation_errors"]
            yield _sse("node", {"node": node})
    except Exception as e:  # noqa: BLE001 —— 任何异常都以 SSE error 事件返回
        yield _sse("error", {"message": str(e)})
        return
    if report_obj is not None:
        yield _sse("done", {"report": report_obj.model_dump()})
    else:
        yield _sse("error", {"message": "；".join(errors) or "未生成报告"})


@app.post("/report/stream")
def report_stream(req: ReportRequest) -> StreamingResponse:
    """SSE 流式生成授信尽调报告。"""
    return StreamingResponse(_stream(req.query), media_type="text/event-stream")
