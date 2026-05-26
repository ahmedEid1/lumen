"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

/**
 * Workbench PasswordStrengthMeter.
 *
 * 5-segment visual + textual feedback. No zxcvbn dep — small
 * heuristic: length tier + character-class diversity + common
 * weakness penalty. Score is a 0-4 integer mapped to a label.
 *
 * Used by /register (Loop 15). The score isn't enforced — the
 * backend's own password policy is authoritative (min 12 chars).
 * This component is a UX hint, not a gate.
 */

export type StrengthScore = 0 | 1 | 2 | 3 | 4;

export function scorePassword(pw: string): StrengthScore {
  if (!pw) return 0;
  let score = 0;
  // Length tiers
  if (pw.length >= 12) score += 1;
  if (pw.length >= 16) score += 1;
  if (pw.length >= 20) score += 1;
  // Class diversity
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^a-zA-Z0-9]/].filter((re) =>
    re.test(pw),
  ).length;
  if (classes >= 3) score += 1;
  // Penalty: all-same / sequential / dictionary-ish weakness
  if (/^(.)\1+$/.test(pw)) score = Math.min(score, 0);
  if (/^(?:0123|1234|abcd|qwer|password|admin|letmein)/i.test(pw))
    score = Math.min(score, 1);
  return Math.min(score, 4) as StrengthScore;
}

const SCORE_LABELS: Record<StrengthScore, MessageKey> = {
  0: "auth.password.strength.empty",
  1: "auth.password.strength.weak",
  2: "auth.password.strength.fair",
  3: "auth.password.strength.good",
  4: "auth.password.strength.strong",
};

const SCORE_TONES: Record<StrengthScore, string> = {
  0: "bg-border",
  1: "bg-destructive",
  2: "bg-warning",
  3: "bg-warning",
  4: "bg-success",
};

const SCORE_TEXT_TONES: Record<StrengthScore, string> = {
  0: "text-muted-foreground",
  1: "text-destructive",
  2: "text-warning",
  3: "text-warning",
  4: "text-success",
};

export function PasswordStrengthMeter({ value }: { value: string }) {
  const t = useT();
  const score = scorePassword(value);
  return (
    <div className="space-y-1" aria-live="polite">
      <div className="flex gap-1" aria-hidden>
        {[1, 2, 3, 4].map((seg) => (
          <span
            key={seg}
            className={cn(
              "h-1 flex-1 rounded-full transition-colors duration-base",
              score >= seg ? SCORE_TONES[score] : "bg-border",
            )}
          />
        ))}
      </div>
      <p
        className={cn(
          "font-mono text-[10px] uppercase tracking-wider",
          SCORE_TEXT_TONES[score],
        )}
      >
        {t(SCORE_LABELS[score])}
      </p>
    </div>
  );
}
