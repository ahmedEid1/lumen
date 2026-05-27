/**
 * L21b — SSE client wrapping fetch + ReadableStream.
 *
 * Native `EventSource` doesn't accept custom headers, so we can't
 * pass a Bearer token on it (Lumen's auth model). This module
 * implements the same wire contract via `fetch()` + a streaming
 * `body` reader, which DOES accept headers.
 *
 * Reconnect strategy: on transient close (server-side timeout,
 * network blip), re-issue the fetch with the latest `Last-Event-ID`
 * header. Hand off `trim_detected` events to the caller — they
 * indicate the resume offset has been trimmed and the caller should
 * fall back to `/status` polling.
 */

import { SseParser, type SseEvent } from "./sse-parser";

export interface SseClientOptions {
  url: string;
  token: string | null;
  lastEventId?: string | null;
  signal?: AbortSignal;
  onEvent: (event: SseEvent) => void;
  onError?: (error: Error) => void;
}

/**
 * Open an SSE stream to `url` with a Bearer token.
 *
 * Returns a promise that resolves when the server closes the stream
 * cleanly, or rejects on a transport-level error. Callers wrap this
 * in their own reconnect loop and pass `lastEventId` on each retry.
 */
export async function openSseStream({
  url,
  token,
  lastEventId,
  signal,
  onEvent,
  onError,
}: SseClientOptions): Promise<void> {
  const headers: HeadersInit = {
    Accept: "text/event-stream",
    "Cache-Control": "no-cache",
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (lastEventId) headers["Last-Event-ID"] = lastEventId;

  let response: Response;
  try {
    response = await fetch(url, { headers, signal });
  } catch (err) {
    onError?.(err instanceof Error ? err : new Error(String(err)));
    return;
  }

  if (!response.ok) {
    onError?.(new Error(`SSE handshake failed: ${response.status}`));
    return;
  }
  if (!response.body) {
    onError?.(new Error("SSE response has no body"));
    return;
  }

  const reader = response.body
    .pipeThrough(new TextDecoderStream())
    .getReader();
  const parser = new SseParser();

  try {
    while (true) {
      if (signal?.aborted) break;
      const { value, done } = await reader.read();
      if (done) break;
      const events = parser.feed(value);
      for (const ev of events) {
        onEvent(ev);
      }
    }
    const final = parser.flush();
    if (final) onEvent(final);
  } catch (err) {
    // AbortError on signal.aborted is expected; don't surface it.
    if (signal?.aborted) return;
    onError?.(err instanceof Error ? err : new Error(String(err)));
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // releaseLock can throw if the reader was already released
      // (e.g. abort path); harmless.
    }
  }
}
