/** 类型化 API client。开发期直连 FastAPI，生产由网关同域反代。 */
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
    throw new Error(`请求失败：HTTP ${res.status}`);
  }
  return (await res.json()) as CreditMemo;
}
