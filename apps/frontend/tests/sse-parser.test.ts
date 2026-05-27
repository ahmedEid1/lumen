/**
 * L21b — SSE parser coverage.
 *
 * The WHATWG spec for SSE has enough subtle edge cases that getting
 * the multi-line / multi-byte / CRLF / mid-chunk-boundary handling
 * right is the value-add of writing our own parser. These tests pin
 * the edge cases so a refactor can't regress them silently.
 */
import { describe, expect, it } from "vitest";

import { SseParser } from "@/lib/tutor/sse-parser";

function feedAll(parser: SseParser, ...chunks: string[]) {
  const out = chunks.flatMap((c) => parser.feed(c));
  const tail = parser.flush();
  if (tail) out.push(tail);
  return out;
}

describe("SseParser", () => {
  it("parses one simple event", () => {
    const p = new SseParser();
    const events = feedAll(p, "event: planner_start\ndata: {}\n\n");
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      id: null,
      event: "planner_start",
      data: "{}",
    });
  });

  it("carries the id field through", () => {
    const p = new SseParser();
    const events = feedAll(p, "id: 1717258401234-0\nevent: synth_chunk\ndata: hello\n\n");
    expect(events[0].id).toBe("1717258401234-0");
    expect(events[0].event).toBe("synth_chunk");
  });

  it("joins multi-line data with \\n", () => {
    const p = new SseParser();
    const events = feedAll(
      p,
      "event: synth_chunk\ndata: first line\ndata: second line\n\n",
    );
    expect(events[0].data).toBe("first line\nsecond line");
  });

  it("ignores comment lines", () => {
    const p = new SseParser();
    const events = feedAll(
      p,
      ": this is a keepalive\nevent: tool_call_start\ndata: {}\n\n",
    );
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("tool_call_start");
  });

  it("handles CRLF line terminators", () => {
    const p = new SseParser();
    const events = feedAll(
      p,
      "event: planner_start\r\ndata: ok\r\n\r\n",
    );
    expect(events[0].event).toBe("planner_start");
    expect(events[0].data).toBe("ok");
  });

  it("handles chunks that split a line mid-stream", () => {
    const p = new SseParser();
    // First chunk ends mid-field-value. Parser must hold the partial
    // line in the buffer and continue on the next chunk.
    const events = feedAll(
      p,
      "event: synth_chunk\ndata: hel",
      "lo world\n\n",
    );
    expect(events).toHaveLength(1);
    expect(events[0].data).toBe("hello world");
  });

  it("dispatches multiple events from one feed", () => {
    const p = new SseParser();
    const events = feedAll(
      p,
      "event: a\ndata: 1\n\nevent: b\ndata: 2\n\n",
    );
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ id: null, event: "a", data: "1" });
    expect(events[1]).toEqual({ id: null, event: "b", data: "2" });
  });

  it("treats missing-colon lines as field-only with empty value", () => {
    const p = new SseParser();
    const events = feedAll(p, "event\ndata: ok\n\n");
    // `event` with no colon → field=event, value=""; pending event
    // resets to "message" because empty value is the default.
    expect(events[0].event).toBe("message");
  });

  it("strips a single leading space from values", () => {
    const p = new SseParser();
    const events = feedAll(p, "data:  two-leading-space\n\n");
    // Spec strips ONE leading space, not all.
    expect(events[0].data).toBe(" two-leading-space");
  });
});
