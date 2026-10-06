"use client";

import { useState, type FormEvent } from "react";

const EXAMPLES = [
  "generate a report for Huayu Software Services PLC",
  "analyze Meridian Display Technology Co., Ltd.",
];

export function QueryForm({
  running,
  onSubmit,
}: {
  running: boolean;
  onSubmit: (query: string) => void;
}) {
  const [query, setQuery] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q || running) return;
    onSubmit(q);
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter an entity name or query, e.g. Huayu Software Services PLC"
          className="flex-1 rounded-lg border border-zinc-300 px-4 py-3 text-sm outline-none focus:border-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:focus:border-zinc-400"
        />
        <button
          type="submit"
          disabled={running || !query.trim()}
          className="rounded-lg bg-zinc-900 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {running ? "Generating…" : "Generate Report"}
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => setQuery(example)}
            className="rounded-full border border-zinc-200 px-3 py-1 text-xs text-zinc-500 transition-colors hover:border-zinc-400 hover:text-zinc-700 dark:border-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
          >
            {example}
          </button>
        ))}
      </div>
    </form>
  );
}
