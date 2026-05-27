/**
 * Tutor-namespace scrubber for frontend Sentry events (L38).
 *
 * Mirrors the backend's `app.core.sentry_scrubber` so a captured
 * exception on either tier zeros the same set of high-risk fields
 * before it ships to Glitchtip/Sentry. Without this, an error
 * thrown anywhere inside the streaming tutor flow could leak the
 * learner's question, the LLM response, or retrieved lesson
 * excerpts into a third-party error tracker — defeating the
 * point of the H6 + L21-Sec privacy posture.
 *
 * What gets scrubbed:
 * - Breadcrumbs tagged `category: "tutor"` (clear text replaced)
 * - Any event/error message containing high-risk substrings
 * - Stack-frame `extra` data on tutor-namespace frames
 * - Request bodies on `/api/v1/tutor/*` paths
 *
 * What still ships:
 * - Exception class, file, line
 * - Stack trace structure (just not the variable contents)
 * - Non-tutor breadcrumbs
 * - Anonymous user id (if set via Sentry.setUser; never PII)
 */

const SCRUBBED = "<scrubbed by lumen.sentry_scrubber>";

// Patterns that trigger full-message scrubbing. Conservative: if any
// substring matches, we drop the original message string and replace
// it with the constant marker. Keeps debugging possible via stack
// trace but prevents prompt/answer leakage.
const HIGH_RISK_SUBSTRINGS = [
  "tutor",
  "synth_chunk",
  "retriever",
  "prompt",
  "lesson_body",
  "completion",
];

const TUTOR_PATH_PREFIX = "/api/v1/tutor";

interface SentryEventLike {
  request?: {
    url?: string;
    data?: unknown;
    query_string?: string;
  };
  breadcrumbs?: Array<{
    category?: string;
    message?: string;
    data?: Record<string, unknown>;
  }>;
  exception?: {
    values?: Array<{
      value?: string;
      stacktrace?: {
        frames?: Array<{
          vars?: Record<string, unknown>;
        }>;
      };
    }>;
  };
  message?: string;
  // L39 rescue (Codex P1) — `extra` and `contexts` are common
  // metadata escape hatches. `Sentry.captureException(err, { extra:
  // { prompt, messages } })` would otherwise smuggle the same data
  // the stacktrace scrubber zeros.
  extra?: Record<string, unknown>;
  contexts?: Record<string, Record<string, unknown> | undefined>;
}

export function beforeSendScrub<T extends SentryEventLike>(event: T): T {
  // Scrub the top-level event message if it looks risky.
  if (event.message && hasHighRiskSubstring(event.message)) {
    event.message = SCRUBBED;
  }

  // Scrub request body on any /tutor/* URL.
  if (event.request?.url?.includes(TUTOR_PATH_PREFIX)) {
    event.request.data = SCRUBBED;
    // L39 rescue (Codex P2) — strip query strings from tutor URLs.
    // A failed SSE reconnect or any tutor request that smuggles
    // learner content into the query (e.g. ?q=…) would otherwise
    // ship in clear.
    event.request.url = SCRUBBED;
    if (event.request.query_string) {
      event.request.query_string = SCRUBBED;
    }
  }

  // Scrub each breadcrumb. Breadcrumbs tagged `category: "tutor"`
  // get their message + data wiped; other breadcrumbs are
  // inspected for high-risk strings.
  if (event.breadcrumbs) {
    event.breadcrumbs = event.breadcrumbs.map((bc) => {
      if (bc.category === "tutor") {
        return { ...bc, message: SCRUBBED, data: undefined };
      }
      // L39 rescue (Codex P1) — a `fetch` / `xhr` breadcrumb to
      // /tutor/* carries the request URL + body under `data` even
      // when the message is innocuous. L40 rescue (Codex P1): the
      // first pass only zeroed payload/body/url but a breadcrumb
      // shaped `{ data: { prompt: "..." } }` still leaked the
      // `prompt` key. Now: walk the entire data dict via scrubMap
      // (which recursively scrubs nested high-risk keys), then
      // overwrite the conventional payload/body/url fields too.
      if (bc.data && hasTutorSignalInData(bc.data)) {
        const cleaned = scrubMap(bc.data);
        cleaned.payload = SCRUBBED;
        cleaned.body = SCRUBBED;
        cleaned.url = SCRUBBED;
        return { ...bc, data: cleaned };
      }
      if (bc.message && hasHighRiskSubstring(bc.message)) {
        return { ...bc, message: SCRUBBED };
      }
      return bc;
    });
  }

  // L39 rescue (Codex P1) — scrub `extra` and `contexts` metadata.
  // `Sentry.captureException(err, { extra: { prompt } })` would
  // otherwise smuggle the same field names the stacktrace scrubber
  // zeros.
  if (event.extra) {
    event.extra = scrubMap(event.extra);
  }
  if (event.contexts) {
    const cleaned: Record<string, Record<string, unknown> | undefined> = {};
    for (const [ctxName, ctxValue] of Object.entries(event.contexts)) {
      cleaned[ctxName] = ctxValue ? scrubMap(ctxValue) : ctxValue;
    }
    event.contexts = cleaned;
  }

  // Scrub stack-frame locals for exception values mentioning tutor.
  if (event.exception?.values) {
    event.exception.values = event.exception.values.map((exc) => {
      const value =
        exc.value && hasHighRiskSubstring(exc.value) ? SCRUBBED : exc.value;
      const stacktrace = exc.stacktrace
        ? {
            ...exc.stacktrace,
            frames: (exc.stacktrace.frames ?? []).map((frame) => {
              if (!frame.vars) return frame;
              const cleaned: Record<string, unknown> = {};
              for (const [k, v] of Object.entries(frame.vars)) {
                cleaned[k] = isHighRiskKey(k) ? SCRUBBED : v;
              }
              return { ...frame, vars: cleaned };
            }),
          }
        : exc.stacktrace;
      return { ...exc, value, stacktrace };
    });
  }

  return event;
}

function hasHighRiskSubstring(s: string): boolean {
  const lc = s.toLowerCase();
  return HIGH_RISK_SUBSTRINGS.some((sub) => lc.includes(sub));
}

const HIGH_RISK_KEYS = new Set([
  "prompt",
  "system_prompt",
  "user_message",
  "messages",
  "response_text",
  "tool_output",
  "tool_result",
  "completion",
  "answer",
  "agent_response",
  "retrieved_chunks",
  "lesson_body",
]);

function isHighRiskKey(k: string): boolean {
  return HIGH_RISK_KEYS.has(k);
}

/**
 * Recursively scrub a dict — high-risk keys replaced with the
 * scrubbed marker, high-risk-substring strings replaced, nested
 * dicts walked depth-first.
 *
 * L40 rescue (Codex P1): the first version was one-level deep and
 * left `contexts: { tutor: { request: { prompt: "..." } } }`
 * fully readable. `MAX_DEPTH` bounds recursion so a cyclic ref or
 * a giant `contexts` payload can't blow the stack.
 */
function scrubMap(
  map: Record<string, unknown>,
  depth: number = 0,
): Record<string, unknown> {
  const MAX_DEPTH = 5;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(map)) {
    if (isHighRiskKey(k)) {
      out[k] = SCRUBBED;
      continue;
    }
    if (typeof v === "string" && hasHighRiskSubstring(v)) {
      out[k] = SCRUBBED;
      continue;
    }
    if (
      v !== null &&
      typeof v === "object" &&
      !Array.isArray(v) &&
      depth < MAX_DEPTH
    ) {
      out[k] = scrubMap(v as Record<string, unknown>, depth + 1);
      continue;
    }
    out[k] = v;
  }
  return out;
}

/**
 * L39 rescue — does this breadcrumb's data dict look tutor-related?
 * A `fetch` breadcrumb to /api/v1/tutor/turns is the canonical case
 * — `data.url` will contain the path. We also key off any high-risk
 * key being present.
 */
function hasTutorSignalInData(data: Record<string, unknown>): boolean {
  const url = data.url;
  if (typeof url === "string" && url.includes(TUTOR_PATH_PREFIX)) {
    return true;
  }
  for (const key of Object.keys(data)) {
    if (isHighRiskKey(key)) return true;
  }
  return false;
}
