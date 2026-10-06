"use client";

import { QueryForm } from "@/components/QueryForm";
import { ReportView } from "@/components/ReportView";
import { useReportStream } from "@/features/report/useReportStream";

export default function Home() {
  const { status, stages, report, error, candidates, run, reset } =
    useReportStream();

  return (
    <div className="flex flex-1 flex-col items-center bg-zinc-50 dark:bg-black">
      <main className="flex w-full max-w-3xl flex-col gap-8 px-6 py-12">
        <header className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold tracking-tight">
              Credit Copilot
            </h1>
            {status !== "idle" && (
              <button
                type="button"
                onClick={reset}
                className="rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-900 dark:hover:text-zinc-200"
              >
                Reset
              </button>
            )}
          </div>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Enter an entity name to generate a structured credit due-diligence
            report (deterministic pipeline + LLM drafting).
          </p>
        </header>

        <QueryForm running={status === "running"} onSubmit={run} />

        <ReportView
          status={status}
          stages={stages}
          report={report}
          error={error}
          candidates={candidates}
        />
      </main>
    </div>
  );
}
