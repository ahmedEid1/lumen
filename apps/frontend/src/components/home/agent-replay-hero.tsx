"use client";

/**
 * L29 — landing-page hero: animated SSE replay.
 *
 * Per plan-v7, the home hero is supposed to feel like watching the
 * tutor work, not a screen recording. In a streaming-flag-on world
 * we'd literally subscribe to a seeded demo SSE stream; today the
 * flag is off, so this component is the next-honest thing:
 *
 *   - A pure-CSS animation that walks through the canonical
 *     event sequence (planner_start → tool_call_start ×2 → synth
 *     chunks → turn_complete).
 *   - Each event row matches the wire shape the real `StreamingTutorPanel`
 *     renders, so a recruiter who clicks /demo and sees the live
 *     thing recognises it.
 *   - `prefers-reduced-motion: reduce` snaps to the final composite
 *     (the plan-v7 §L29 requirement).
 *   - Single "Try the demo →" CTA below, deep-linking to /demo.
 *
 * No JS animation tick; everything is CSS. The component is a
 * client component because it lives inside a server-rendered home
 * page and the CSS-keyframe sequence wants a fresh start on mount.
 */

import Link from "next/link";
import { ArrowRight, Code2, Search, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";

const CANONICAL_QUESTION =
  "I keep getting `Type 'string' is not assignable to type 'T'` — why?";

const CANONICAL_RESPONSE_HEAD =
  "TypeScript thinks `T` could be anything the caller picks, so returning a `string` from a function declared `<T>(x: T): T` violates the contract. Three fixes…";

export function AgentReplayHero() {
  const t = useT();
  return (
    <section
      className="relative overflow-hidden border-b border-border"
      aria-labelledby="hero-headline"
    >
      <div className="container mx-auto grid gap-10 px-6 py-16 sm:py-24 lg:grid-cols-[1.1fr_1fr] lg:py-32">
        {/* Left column — narrative copy. */}
        <div className="max-w-xl">
          <p className="mb-6 font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("home.cartouche")}
          </p>
          <h1
            id="hero-headline"
            className="font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl md:text-6xl"
          >
            {t("home.heroTitle1")}{" "}
            <span className="text-muted-foreground">
              {t("home.heroTitle2")}
            </span>
          </h1>
          <p className="mt-6 font-body text-base leading-relaxed text-muted-foreground sm:text-lg">
            {t("home.replayHeroBody")}
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            {/* Codex rescue (L26→L31 arc): use `Button asChild` so the
                CTA renders a single <a> with Button's styles —
                wrapping Link around Button produced invalid nested
                interactive content (<a><button>). */}
            <Button asChild size="lg" variant="default">
              <Link href="/demo">
                {t("home.replayHeroTryDemo")}
                <ArrowRight className="ms-1 h-4 w-4" aria-hidden />
              </Link>
            </Button>
            <Button asChild size="lg" variant="ghost">
              <Link href="/eval">{t("home.replayHeroPublicEval")}</Link>
            </Button>
          </div>
        </div>

        {/* Right column — the animated replay panel. */}
        <div
          className="motion-replay surface min-h-[420px] flex-1 overflow-hidden p-5 sm:p-6"
          role="img"
          aria-label={t("home.replayHeroAriaLabel")}
        >
          {/* User bubble — appears first, stays through the loop. */}
          <div className="motion-replay__user mb-4 flex flex-col gap-1 items-end">
            <div className="max-w-[90%] whitespace-pre-wrap rounded-md border border-border bg-muted px-3 py-2 font-body text-sm">
              {CANONICAL_QUESTION}
            </div>
          </div>

          {/* Assistant bubble — tools list + text appearing in stages. */}
          <div className="motion-replay__assistant flex flex-col gap-3 items-start">
            <ul
              className="flex flex-col gap-1 font-mono text-[11px] uppercase tracking-wider text-foreground"
              aria-label="Tools used"
            >
              {/* Codex/axe rescue: the tool-row labels need full
                  text-foreground contrast against the surface bg —
                  inherited `text-muted-foreground` was 1.38:1 in
                  dark mode, well below the 4.5:1 WCAG AA threshold.
                  Latency badges step down to /80 (still > 4.5:1). */}
              <li className="motion-replay__tool motion-replay__tool-1 flex items-center gap-2">
                <Search className="h-3 w-3 text-primary" aria-hidden />
                <span>retriever</span>
                <span className="motion-replay__tool-latency tabular-nums text-foreground/80">
                  82 ms
                </span>
              </li>
              <li className="motion-replay__tool motion-replay__tool-2 flex items-center gap-2">
                <Code2 className="h-3 w-3 text-primary" aria-hidden />
                <span>code_runner</span>
                <span className="motion-replay__tool-latency tabular-nums text-foreground/80">
                  214 ms
                </span>
              </li>
            </ul>

            <div className="motion-replay__synth max-w-[90%] rounded-md border border-border px-3 py-2 font-body text-sm">
              <span className="motion-replay__synth-text whitespace-pre-wrap">
                {CANONICAL_RESPONSE_HEAD}
              </span>
              <span
                className="motion-replay__cursor ms-0.5 inline-block h-3 w-1 align-middle bg-primary"
                aria-hidden
              />
            </div>

            <p className="motion-replay__caption font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              <Sparkles className="me-1 inline h-3 w-3 align-[-1px] text-primary" aria-hidden />
              {t("home.replayHeroCaption")}
            </p>
          </div>
        </div>
      </div>

      {/* CSS animation. Reduced-motion users get the final-frame composite. */}
      <style>{`
        /* Stage timing (loops at 14s — generous so a recruiter has
           time to read the captions). */
        @keyframes lumenReplayUser {
          0%, 8% { opacity: 0; transform: translateX(8px); }
          16%, 100% { opacity: 1; transform: translateX(0); }
        }
        /* Codex/axe rescue: keep tool rows at opacity 1 throughout
           so axe-core's contrast check never samples a faded frame.
           The earlier 0.2 start made the labels render at ~1.7:1
           against the surface bg even though they declared
           text-foreground. The latency badges still fade in (small
           numeric content) — the build-up feel comes from those
           instead. */
        @keyframes lumenReplayTool1 {
          0%, 100% { opacity: 1; }
        }
        @keyframes lumenReplayTool2 {
          0%, 100% { opacity: 1; }
        }
        @keyframes lumenReplaySynth {
          0%, 40% { opacity: 0; transform: translateY(4px); }
          48%, 100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes lumenReplayLatency {
          0%, 24% { opacity: 0; }
          32%, 100% { opacity: 1; }
        }
        @keyframes lumenReplayLatency2 {
          0%, 36% { opacity: 0; }
          44%, 100% { opacity: 1; }
        }
        @keyframes lumenReplayCursor {
          0%, 100% { opacity: 0; }
          48%, 92% { opacity: 1; }
        }
        @keyframes lumenReplayCaption {
          0%, 60% { opacity: 0; }
          68%, 100% { opacity: 0.85; }
        }

        .motion-replay__user {
          animation: lumenReplayUser 14s ease-out infinite;
        }
        .motion-replay__tool-1 {
          animation: lumenReplayTool1 14s ease-out infinite;
        }
        .motion-replay__tool-1 .motion-replay__tool-latency {
          animation: lumenReplayLatency 14s ease-out infinite;
        }
        .motion-replay__tool-2 {
          animation: lumenReplayTool2 14s ease-out infinite;
        }
        .motion-replay__tool-2 .motion-replay__tool-latency {
          animation: lumenReplayLatency2 14s ease-out infinite;
        }
        .motion-replay__synth {
          animation: lumenReplaySynth 14s ease-out infinite;
        }
        .motion-replay__cursor {
          animation: lumenReplayCursor 14s ease-in-out infinite;
        }
        .motion-replay__caption {
          animation: lumenReplayCaption 14s ease-out infinite;
        }

        @media (prefers-reduced-motion: reduce) {
          .motion-replay__user,
          .motion-replay__tool-1,
          .motion-replay__tool-2,
          .motion-replay__tool-1 .motion-replay__tool-latency,
          .motion-replay__tool-2 .motion-replay__tool-latency,
          .motion-replay__synth,
          .motion-replay__caption {
            animation: none;
            opacity: 1;
            transform: none;
          }
          .motion-replay__cursor {
            animation: none;
            opacity: 0;
          }
        }
      `}</style>
    </section>
  );
}
