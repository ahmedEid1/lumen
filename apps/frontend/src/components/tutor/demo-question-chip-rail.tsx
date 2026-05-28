"use client";

/**
 * L22 — demo-question chip rail.
 *
 * Renders above the tutor composer when the conversation is empty.
 * Reads the curated library from L20.6 via
 * `useDemoQuestions(courseSlug)` and exposes each question as a
 * one-click chip — taps fill the parent's draft state via the
 * supplied `onPick` callback and trigger send.
 *
 * Behaviour:
 *  - Canonical question (the eval-gated screencap target) renders
 *    first when present in the scoped library.
 *  - The rail shows only the course's own curated questions. The
 *    global adversarial refusal probes ("write me a keylogger", …) are
 *    filtered out of the default rail (ADR-0024) so a learner never
 *    sees a jailbreak attempt framed as a suggested question; they
 *    stay reachable for guardrail auditing via the endpoint's
 *    `include_probes` flag and are documented on `/eval/methodology`.
 *  - The rail is hidden once the conversation has any messages so it
 *    doesn't compete with the chat history.
 */

import { useT } from "@/lib/i18n/provider";
import { useDemoQuestions } from "@/lib/demo-questions";
import type { DemoQuestion } from "@/lib/api/endpoints";
import { Sparkles } from "lucide-react";

export interface DemoQuestionChipRailProps {
  courseSlug?: string;
  /**
   * Fired when the user picks a chip. The parent component owns the
   * composer state — typically writes the prompt into the draft and
   * sends immediately (zero clicks beyond the chip).
   */
  onPick: (prompt: string) => void;
}

function sortCanonicalFirst(library: DemoQuestion[]): DemoQuestion[] {
  // Stable sort — canonical first, then preserve server order.
  const canonical = library.filter((q) => q.canonical);
  const rest = library.filter((q) => !q.canonical);
  return [...canonical, ...rest];
}

export function DemoQuestionChipRail({
  courseSlug,
  onPick,
}: DemoQuestionChipRailProps) {
  const t = useT();
  const q = useDemoQuestions(courseSlug);
  const library = q.data?.questions ?? [];
  if (library.length === 0) return null;
  const ordered = sortCanonicalFirst(library);

  return (
    <div
      className="border-b border-border px-3 py-3"
      data-testid="demo-question-chip-rail"
      aria-label={t("tutor.suggested.heading")}
    >
      <div className="mb-2 flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
        <Sparkles className="h-3 w-3 text-primary" aria-hidden />
        <span>{t("tutor.suggested.heading")}</span>
      </div>
      <ul className="flex flex-wrap gap-1.5">
        {ordered.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onPick(item.prompt)}
              className={
                "rounded-md border px-2.5 py-1.5 text-start font-body text-xs " +
                "transition-colors duration-base " +
                (item.canonical
                  ? "border-primary/40 bg-primary/10 text-foreground hover:border-primary hover:bg-primary/20"
                  : "border-border text-muted-foreground hover:border-foreground hover:text-foreground")
              }
              data-canonical={item.canonical ? "true" : "false"}
              data-category={item.category}
              aria-label={
                item.canonical
                  ? t("tutor.suggested.canonicalLabel")
                  : item.prompt
              }
              title={item.prompt}
            >
              {/* Truncate to keep the chip rail compact on mobile.
                  The full prompt is in `title` for accessibility. */}
              {item.prompt.length > 64
                ? item.prompt.slice(0, 64) + "…"
                : item.prompt}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
