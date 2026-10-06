"""FastAPI interface: report generation (synchronous JSON + SSE streaming progress)."""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from credit_copilot.agents.orchestrator import run_report, run_report_stream
from credit_copilot.report_store import save_report

app = FastAPI(title="Credit Copilot", version="0.1.0")

# The frontend (Next.js) connects directly: allow any origin in dev, tighten to the
# NEXT_PUBLIC_API_BASE_URL origin in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReportRequest(BaseModel):
    query: str
    save: bool = False  # when True, persist the report to data/reports/


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/report")
def report(req: ReportRequest) -> dict:
    """Generate a credit memo synchronously and return structured JSON;
    when save=True also persist to data/reports/."""
    memo = run_report(req.query)
    data = memo.model_dump()
    if req.save:
        data["saved_to"] = str(save_report(memo))
    return data


def _sse(event: str, data: dict) -> str:
    return f"data: {json.dumps({'event': event, **data}, ensure_ascii=False)}\n\n"


async def _stream(query: str) -> AsyncGenerator[str, None]:
    """Streaming progress: start -> per-stage -> done/error."""
    yield _sse("start", {"query": query})
    try:
        for stage in run_report_stream(query):
            if stage.get("status") == "error":
                yield _sse("error", {"message": stage.get("message", "Unknown error"),
                                     "candidates": stage.get("candidates", [])})
                return
            if "report" in stage:
                yield _sse("done", {"report": stage["report"].model_dump()})
            else:
                yield _sse("node", {"stage": stage["stage"], "status": stage["status"]})
    except Exception as e:  # noqa: BLE001 — any exception is returned as an SSE error event
        yield _sse("error", {"message": str(e)})


@app.post("/report/stream")
def report_stream(req: ReportRequest) -> StreamingResponse:
    """SSE streaming credit-memo generation."""
    return StreamingResponse(_stream(req.query), media_type="text/event-stream")
