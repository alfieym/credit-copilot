"use client";

import { STAGE_LABELS } from "@/features/report/useReportStream";
import type { CreditMemo } from "@/features/report/types";

const FLAG_STYLES: Record<string, string> = {
  error: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-900",
  warning: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900",
  info: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950 dark:text-sky-300 dark:border-sky-900",
};

function Stages({ stages }: { stages: { stage: string; status: string }[] }) {
  if (stages.length === 0) return null;
  return (
    <ul className="flex flex-col gap-2">
      {stages.map((s) => (
        <li key={s.stage} className="flex items-center gap-2 text-sm">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              s.status === "done" ? "bg-emerald-500" : "animate-pulse bg-zinc-400"
            }`}
          />
          <span className="text-zinc-600 dark:text-zinc-300">
            {STAGE_LABELS[s.stage] ?? s.stage}
          </span>
        </li>
      ))}
    </ul>
  );
}

function SectionCard({
  title,
  content,
  citations,
}: {
  title: string;
  content: string;
  citations: string[];
}) {
  return (
    <section className="rounded-xl border border-zinc-200 p-5 dark:border-zinc-800">
      <h3 className="mb-2 text-base font-semibold">{title}</h3>
      <p className="whitespace-pre-wrap text-sm leading-6 text-zinc-700 dark:text-zinc-300">
        {content}
      </p>
      {citations.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {citations.map((c) => (
            <span
              key={c}
              className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
            >
              {c}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

export function ReportView({
  status,
  stages,
  report,
  error,
  candidates,
}: {
  status: string;
  stages: { stage: string; status: string }[];
  report: CreditMemo | null;
  error: string | null;
  candidates: string[];
}) {
  if (status === "idle") {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        输入主体名称后点击「生成报告」，将在这里实时展示生成进度与报告结果。
      </p>
    );
  }

  if (status === "error") {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-5 dark:border-red-900 dark:bg-red-950">
        <p className="text-sm font-medium text-red-700 dark:text-red-300">{error}</p>
        {candidates.length > 0 && (
          <div className="mt-3">
            <p className="mb-1 text-xs text-red-600 dark:text-red-400">
              可能是以下主体，请精确指定其一：
            </p>
            <ul className="list-inside list-disc text-sm text-red-700 dark:text-red-300">
              {candidates.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  }

  if (status === "running") {
    return <Stages stages={stages} />;
  }

  if (!report) return null;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h2 className="text-xl font-bold">{report.entity_name} · 授信尽调报告</h2>
        <p className="mt-1 text-xs text-zinc-400 dark:text-zinc-500">
          生成时间：{report.generated_at}
        </p>
      </header>

      {report.compliance_flags.length > 0 && (
        <div className="flex flex-col gap-2">
          {report.compliance_flags.map((flag) => {
            const level = flag.match(/^\[(error|warning|info)\]/)?.[1] ?? "info";
            const text = flag.replace(/^\[(error|warning|info)\]\s*/, "");
            return (
              <div
                key={flag}
                className={`rounded-lg border px-3 py-2 text-sm ${FLAG_STYLES[level]}`}
              >
                {text}
              </div>
            );
          })}
        </div>
      )}

      <div className="flex flex-col gap-4">
        {report.sections.map((section) => (
          <SectionCard key={section.title} {...section} />
        ))}
      </div>

      {report.data_gaps.length > 0 && (
        <div className="rounded-xl border border-zinc-200 p-5 dark:border-zinc-800">
          <h3 className="mb-2 text-base font-semibold">数据缺口</h3>
          <ul className="list-inside list-disc text-sm text-zinc-600 dark:text-zinc-300">
            {report.data_gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
