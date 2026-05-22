"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";
import { useOnboarding } from "@/lib/onboarding/use-onboarding";
import type { TourStep } from "@/lib/onboarding/steps";

/**
 * Reusable first-login onboarding tour.
 *
 * Renders nothing if the user has already dismissed/completed the tour
 * (per ``storageKey`` flag in localStorage). Otherwise mounts an overlay
 * with a single bordered Workbench card centered on screen, advances
 * forward through ``steps``, and persists the dismissal flag on either
 * Skip or Done.
 *
 * Keyboard:
 *   - ``Escape`` skips the tour
 *   - ``ArrowRight`` advances to the next step / completes on the last
 *
 * Visual rules (Workbench, see C0+C1):
 *   - single `surface` card on `bg-card`, no shadows
 *   - the screen's one lime accent is the Next/Done CTA
 *   - Skip is a ghost button so the primary action stays unambiguous
 *
 * See ``docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md`` §4
 * Phase D item 3.
 */
export function OnboardingTour({
  steps,
  storageKey,
  onDone,
}: {
  steps: TourStep[];
  storageKey: string;
  onDone?: () => void;
}) {
  const t = useT();
  const { visible, dismiss, complete } = useOnboarding(storageKey);
  const [index, setIndex] = useState(0);

  const total = steps.length;
  const isLast = index >= total - 1;

  const handleNext = useCallback(() => {
    if (isLast) {
      complete();
      onDone?.();
    } else {
      setIndex((i) => Math.min(i + 1, total - 1));
    }
  }, [isLast, complete, onDone, total]);

  const handleSkip = useCallback(() => {
    dismiss();
    onDone?.();
  }, [dismiss, onDone]);

  // Global keyboard shortcuts while the tour is open. Bound to
  // ``document`` (not the card) because the card receives autofocus on
  // Next but a user may have clicked anywhere on the overlay.
  useEffect(() => {
    if (!visible) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        handleSkip();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        handleNext();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [visible, handleNext, handleSkip]);

  if (!visible || total === 0) return null;

  const step = steps[index];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      aria-describedby="onboarding-body"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 px-6 backdrop-blur-sm"
    >
      <div className="surface flex w-full max-w-md flex-col gap-5 p-6 sm:p-8">
        <div className="flex items-center justify-between gap-3">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("onboarding.step", { n: index + 1, total })}
          </p>
          <button
            type="button"
            onClick={handleSkip}
            className="font-mono text-xs uppercase tracking-wider text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
            aria-label={t("onboarding.dismiss")}
          >
            {t("onboarding.skip")}
          </button>
        </div>

        <h2
          id="onboarding-title"
          className="font-display text-2xl leading-tight tracking-tight"
        >
          {t(step.title)}
        </h2>
        <p
          id="onboarding-body"
          className="font-body text-sm leading-relaxed text-muted-foreground"
        >
          {t(step.body)}
        </p>

        {/* Step indicator + primary CTA. The dots are a passive
            position cue — clicking them does not jump steps (we always
            want forward progress through the script). */}
        <div className="mt-2 flex items-center justify-between gap-4">
          <div
            className="flex gap-1.5"
            aria-hidden="true"
          >
            {steps.map((_, i) => (
              <span
                key={i}
                className={
                  i === index
                    ? "h-1.5 w-6 rounded-full bg-foreground transition-colors duration-[160ms]"
                    : "h-1.5 w-1.5 rounded-full bg-border transition-colors duration-[160ms]"
                }
              />
            ))}
          </div>
          <Button onClick={handleNext} autoFocus>
            {isLast ? t("onboarding.done") : t("onboarding.next")}
          </Button>
        </div>
      </div>
    </div>
  );
}
