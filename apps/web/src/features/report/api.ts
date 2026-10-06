/** Typed API client. In dev it hits FastAPI directly; in production a gateway reverse-proxies it same-origin. */
import type { CreditMemo } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function fetchReport(query: string): Promise<CreditMemo> {
  const res = await fetch(`${API_BASE}/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) {
    throw new Error(`Request failed: HTTP ${res.status}`);
  }
  return (await res.json()) as CreditMemo;
}
