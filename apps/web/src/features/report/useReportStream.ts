"use client";

import { useCallback, useRef, useState } from "react";

import { streamSSE } from "@/lib/sse";
import { API_BASE } from "./api";
import type { CreditMemo } from "./types";

export interface ReportStage {
  stage: string;
  status: "running" | "done";
}

export interface ReportStreamState {
  status: "idle" | "running" | "done" | "error";
  stages: ReportStage[];
  report: CreditMemo | null;
  error: string | null;
  candidates: string[];
}

const INITIAL: ReportStreamState = {
  status: "idle",
  stages: [],
  report: null,
  error: null,
  candidates: [],
};

/** 与后端 orchestrator 的阶段名对齐，用于渲染中文标签。 */
export const STAGE_LABELS: Record<string, string> = {
  resolve_entity: "解析主体",
  collect_facts: "采集事实数据",
  compliance: "合规规则核验",
  compose_report: "撰写报告",
};

export function useReportStream() {
  const [state, setState] = useState<ReportStreamState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async (query: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ ...INITIAL, status: "running" });

    try {
      for await (const ev of streamSSE(
        `${API_BASE}/report/stream`,
        { query },
        controller.signal,
      )) {
        if (ev.event === "node") {
          const stage = String(ev.stage);
          setState((s) => ({
            ...s,
            stages: [
              ...s.stages.filter((x) => x.stage !== stage),
              { stage, status: ev.status === "done" ? "done" : "running" },
            ],
          }));
        } else if (ev.event === "done") {
          setState((s) => ({
            ...s,
            status: "done",
            report: ev.report as CreditMemo,
          }));
        } else if (ev.event === "error") {
          setState((s) => ({
            ...s,
            status: "error",
            error: String(ev.message ?? "未知错误"),
            candidates: (ev.candidates as string[]) ?? [],
          }));
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setState((s) => ({
        ...s,
        status: "error",
        error: err instanceof Error ? err.message : String(err),
      }));
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL);
  }, []);

  return { ...state, run, reset };
}
