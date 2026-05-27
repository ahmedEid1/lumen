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
}

export function beforeSendScrub<T extends SentryEventLike>(event: T): T {
  // Scrub the top-level event message if it looks risky.
  if (event.message && hasHighRiskSubstring(event.message)) {
    event.message = SCRUBBED;
  }

  // Scrub request body on any /tutor/* URL.
  if (event.request?.url?.includes(TUTOR_PATH_PREFIX)) {
    event.request.data = SCRUBBED;
  }

  // Scrub each breadcrumb. Breadcrumbs tagged `category: "tutor"`
  // get their message + data wiped; other breadcrumbs are
  // inspected for high-risk strings.
  if (event.breadcrumbs) {
    event.breadcrumbs = event.breadcrumbs.map((bc) => {
      if (bc.category === "tutor") {
        return { ...bc, message: SCRUBBED, data: undefined };
      }
      if (bc.message && hasHighRiskSubstring(bc.message)) {
        return { ...bc, message: SCRUBBED };
      }
      return bc;
    });
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
