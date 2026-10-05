/**
 * 基于 fetch 的 SSE 解析器。
 *
 * 后端 `/report/stream` 是 POST 端点，浏览器原生 `EventSource` 只支持 GET，
 * 因此这里用 `fetch` + `ReadableStream` 逐行读取 `data: {json}\n\n` 帧。
 */
export interface SSEEvent {
  event: string;
  [key: string]: unknown;
}

export async function* streamSSE(
  url: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`请求失败：HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const dataLine = frame
        .split("\n")
        .find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      const json = dataLine.slice(5).trim();
      if (!json) continue;
      yield JSON.parse(json) as SSEEvent;
    }
  }
}
