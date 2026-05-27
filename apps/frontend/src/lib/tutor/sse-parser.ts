/**
 * L21b — Server-Sent Events parser.
 *
 * SSE wire format (per WHATWG HTML spec):
 *   - Each event is a block of `field: value\n` lines, terminated by
 *     a blank line.
 *   - Fields we care about: `id`, `event`, `data`. Multiple `data:`
 *     lines in one event are joined with `\n`.
 *   - Comments start with `:` and are ignored.
 *
 * Why not native EventSource: it doesn't expose the `Last-Event-ID`
 * header on reconnect *unless* the server set it via the `id:`
 * field on previous events — which our backend does. EventSource is
 * fine for resume, BUT it doesn't accept custom headers, so we
 * can't pass our Bearer token on the WebSocket-like connection.
 * Native browser EventSource = cookie auth only.
 *
 * For Lumen's "Bearer token via Authorization header" auth model, we
 * implement the parser ourselves on top of `fetch` + `ReadableStream`,
 * which DOES accept custom headers. The token gets passed in the
 * request; reconnects re-issue the fetch with the updated
 * `Last-Event-ID`.
 */

export interface SseEvent {
  id: string | null;
  event: string;
  data: string;
}

/**
 * Stream-parse an SSE response body into discrete events.
 *
 * Holds a small buffer (`pending`) for the current in-progress event;
 * yields a frame each time it hits a blank line.
 */
export class SseParser {
  private buffer = "";
  private pendingId: string | null = null;
  private pendingEvent = "message";
  private pendingData = "";

  /**
   * Feed a chunk (UTF-8-decoded) into the parser. Returns any events
   * that completed inside this chunk; callers loop over them.
   *
   * Edge cases handled:
   *  - chunks that split a line mid-CRLF
   *  - chunks that split a field name mid-character
   *  - trailing partial line at end-of-chunk (held in `buffer`)
   */
  feed(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const out: SseEvent[] = [];

    // Process one full line at a time. A line ends in \n. We accept
    // \r\n and \r as equivalent per the spec.
    let newlineIdx: number;
    while ((newlineIdx = this.buffer.search(/[\r\n]/)) !== -1) {
      const line = this.buffer.slice(0, newlineIdx);
      // Eat the terminator (handle \r\n vs \n vs \r).
      let terminatorLen = 1;
      if (
        this.buffer.charAt(newlineIdx) === "\r" &&
        this.buffer.charAt(newlineIdx + 1) === "\n"
      ) {
        terminatorLen = 2;
      }
      this.buffer = this.buffer.slice(newlineIdx + terminatorLen);

      if (line === "") {
        // Blank line → dispatch the pending event.
        const frame = this.dispatch();
        if (frame) out.push(frame);
        continue;
      }

      if (line.startsWith(":")) {
        // Comment — ignore.
        continue;
      }

      // Field: value. The spec allows missing colon; treat the entire
      // line as the field name with an empty value.
      let field: string;
      let value: string;
      const colonIdx = line.indexOf(":");
      if (colonIdx === -1) {
        field = line;
        value = "";
      } else {
        field = line.slice(0, colonIdx);
        value = line.slice(colonIdx + 1);
        if (value.startsWith(" ")) value = value.slice(1);
      }

      switch (field) {
        case "id":
          this.pendingId = value;
          break;
        case "event":
          this.pendingEvent = value || "message";
          break;
        case "data":
          if (this.pendingData) this.pendingData += "\n";
          this.pendingData += value;
          break;
        // We don't currently honour the `retry` field; the reducer
        // owns reconnect timing instead.
      }
    }

    return out;
  }

  /** Flush whatever remains in the buffer as one final event (if any). */
  flush(): SseEvent | null {
    return this.dispatch();
  }

  private dispatch(): SseEvent | null {
    if (this.pendingData === "" && this.pendingEvent === "message") {
      // Nothing to emit (blank line at start of stream).
      return null;
    }
    const frame: SseEvent = {
      id: this.pendingId,
      event: this.pendingEvent,
      data: this.pendingData,
    };
    // Reset for next event. Per spec the id is sticky across events
    // until a new id field arrives — we preserve `pendingId` across
    // dispatches accordingly.
    this.pendingEvent = "message";
    this.pendingData = "";
    return frame;
  }
}
