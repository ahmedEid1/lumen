/**
 * L21b — feature detect for streaming SSE.
 *
 * The browser API surface (`TransformStream`, `TextDecoderStream`,
 * `ReadableStream`) is necessary but not sufficient: iOS Safari
 * 15.0-15.3 has all three but the `body` reader on `fetch` responses
 * silently buffers the full payload before yielding any chunks,
 * defeating the streaming UX. Apple fixed this in 15.4.
 *
 * For those broken versions we fall back to the legacy non-streaming
 * POST path (plan-v7 §V7-Sec → §F15). UA sniffing is ugly but is
 * the only reliable signal — feature-detection alone returns a false
 * positive on 15.0-15.3.
 */

export function supportsStreaming(): boolean {
  if (typeof window === "undefined") return false;
  if (typeof TransformStream === "undefined") return false;
  if (typeof TextDecoderStream === "undefined") return false;
  if (typeof (globalThis as { ReadableStream?: unknown }).ReadableStream === "undefined") {
    return false;
  }

  // iOS Safari < 15.4: feature surface present, behaviour broken.
  const ua = navigator.userAgent;
  const iosMatch = ua.match(/OS (\d+)_(\d+)/);
  // The chained-iOS-browser UAs (Chrome/Edge/Firefox-on-iOS use the
  // same WebKit but with `CriOS`/`EdgiOS`/`FxiOS` suffixes — they're
  // also affected since they wrap the same broken WKWebView, but
  // listing them keeps the detection conservative.
  if (iosMatch && /Safari/.test(ua)) {
    const major = parseInt(iosMatch[1], 10);
    const minor = parseInt(iosMatch[2], 10);
    if (major < 15 || (major === 15 && minor < 4)) {
      return false;
    }
  }
  return true;
}
