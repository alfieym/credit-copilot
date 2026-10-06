/**
 * fetch-based SSE parser.
 *
 * The backend `/report/stream` is a POST endpoint; the browser-native `EventSource`
 * only supports GET, so we read `data: {json}\n\n` frames line-by-line with
 * `fetch` + `ReadableStream`.
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
    throw new Error(`Request failed: HTTP ${res.status}`);
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
