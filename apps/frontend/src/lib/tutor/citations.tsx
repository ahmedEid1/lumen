import * as React from "react";
import type { TutorCitation } from "@/lib/api/endpoints";

/**
 * Parse `[L:<lesson_id>]` citation tokens out of a tutor message body
 * and render them as numbered superscript references that link to the
 * citation row below the bubble.
 *
 * Why: the orchestrator prompts the LLM to emit citations inline as
 * `[L:<lesson_id>]`, which is the wire contract that lets the eval
 * harness check coverage (every claim cites its source). But shipping
 * those tokens through to end users as opaque text — saw it on prod
 * 2026-05-28: "you need to update the model with new information
 * without retraining the entire model [L:xNXO2EdYtXrOryYqwsLRR]." —
 * looks like a bug. This helper bridges the wire format to a clean
 * UX: each token becomes a small `[N]` superscript that anchors to
 * the citation pill of the same index below, where the lesson title
 * is human-readable.
 *
 * Token shape: `[L:<lesson_id>]`. Lesson ids are 21-char nanoids, but
 * we accept any non-bracket-non-whitespace tail to stay defensive
 * against ID-shape drift.
 *
 * Index resolution: 1-based, matching the position of the matching
 * citation in `citations`. If the lesson_id isn't in `citations`
 * (e.g., mid-stream before the citations array lands, or a stale id),
 * the token is silently dropped from the rendered output — keeps the
 * prose clean and avoids a confusing `[?]` that promises a link the
 * reader can't actually follow.
 *
 * Returns an array of React.ReactNode chunks suitable for use inside
 * a `whitespace-pre-wrap` container.
 */
const CITATION_TOKEN = /\[L:([^\]\s]+)\]/g;

export function renderTutorBody(
  content: string,
  citations: ReadonlyArray<TutorCitation>,
): React.ReactNode[] {
  const idIndex = new Map<string, number>();
  citations.forEach((c, i) => idIndex.set(c.lesson_id, i + 1));

  const out: React.ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  for (const match of content.matchAll(CITATION_TOKEN)) {
    const start = match.index ?? 0;
    if (start > cursor) {
      out.push(content.slice(cursor, start));
    }
    const lessonId = match[1];
    const idx = idIndex.get(lessonId);
    if (idx !== undefined) {
      out.push(
        <sup
          key={`cite-${key++}`}
          data-testid={`tutor-inline-citation-${idx}`}
          className="ms-0.5 font-mono text-[10px] text-primary"
        >
          <a
            href={`#tutor-cite-${idx}`}
            className="rounded px-0.5 transition-colors hover:bg-primary/10"
            aria-label={`Citation ${idx}: ${citations[idx - 1].lesson_title}`}
          >
            [{idx}]
          </a>
        </sup>,
      );
    }
    // If lesson_id isn't in citations, drop the token quietly.
    cursor = start + match[0].length;
  }
  if (cursor < content.length) {
    out.push(content.slice(cursor));
  }
  return out;
}
