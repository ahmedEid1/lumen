"use client";

/**
 * L23 — Cost-cap closing CTA.
 *
 * Renders inside the tutor panel when a turn fails with one of the
 * cost-cap error codes:
 *   - `llm.budget_exceeded`  — per-user 24h cap (Phase H1, shipped)
 *   - `tutor.user_cap` / `tutor.ip_cap` / `tutor.global_cap` — the
 *     L21-Sec Lua-script caps (callers land with L21a-followup)
 *
 * Replaces the generic 503/429 surface with a specific message:
 * "you've used your share of the demo budget; reset in N hours;
 * here's where to reach me." A recruiter who hit the cap is exactly
 * the conversion moment.
 *
 * Mounted by both TutorPanel and StreamingTutorPanel via a shared
 * helper that introspects the API error.
 */

import { Calendar, Clock, Mail, Wallet } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";

const COST_CAP_CODES: ReadonlySet<string> = new Set([
  "llm.budget_exceeded",
  "tutor.user_cap",
  "tutor.ip_cap",
  "tutor.global_cap",
]);

/**
 * Best-effort: read the error `code` field off a thrown API error.
 * The endpoints client's thrown errors carry the human-readable
 * `message` on `Error.message`; the underlying `code` is on the
 * shape `{error: {code}}`. For L23 we match against either.
 */
export function isCostCapError(err: unknown): boolean {
  if (!err) return false;
  if (typeof err === "object" && err !== null && "code" in err) {
    const code = (err as { code?: unknown }).code;
    if (typeof code === "string" && COST_CAP_CODES.has(code)) return true;
  }
  const msg =
    err instanceof Error ? err.message : typeof err === "string" ? err : "";
  return (
    msg.includes("budget_exceeded") ||
    msg.includes("user_cap") ||
    msg.includes("ip_cap") ||
    msg.includes("global_cap")
  );
}

export interface CostCapClosingCtaProps {
  resetAt?: Date | null;
  contactEmail?: string;
  calendlyUrl?: string;
}

function _hoursUntil(when: Date | null | undefined): number | null {
  if (!when) return null;
  const ms = when.getTime() - Date.now();
  if (ms <= 0) return 0;
  return Math.ceil(ms / (60 * 60 * 1000));
}

export function CostCapClosingCta({
  resetAt = null,
  contactEmail = "ahmedhobeishy.tools@gmail.com",
  calendlyUrl = undefined,
}: CostCapClosingCtaProps) {
  const t = useT();
  const hours = _hoursUntil(resetAt);
  return (
    <div
      className="surface m-4 flex flex-col gap-3 p-5"
      role="alert"
      data-testid="cost-cap-closing-cta"
    >
      <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
        <Wallet className="h-3.5 w-3.5 text-primary" aria-hidden />
        <span>{t("tutor.costCap.cartouche")}</span>
      </div>
      <p className="font-display text-lg leading-tight tracking-tight">
        {t("tutor.costCap.headline")}
      </p>
      <p className="font-body text-sm text-muted-foreground">
        {t("tutor.costCap.body")}
      </p>
      {hours !== null && hours > 0 && (
        <p className="flex items-center gap-2 font-mono text-xs tabular-nums text-muted-foreground">
          <Clock className="h-3.5 w-3.5" aria-hidden />
          <span>{t("tutor.costCap.resetsIn", { hours: String(hours) })}</span>
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <a
          href={`mailto:${contactEmail}?subject=Lumen%20demo%20conversation`}
          className="inline-flex"
        >
          <Button variant="default" size="sm" type="button">
            <Mail className="me-1.5 h-3.5 w-3.5" aria-hidden />
            {t("tutor.costCap.emailMe")}
          </Button>
        </a>
        {calendlyUrl && (
          <a href={calendlyUrl} target="_blank" rel="noopener noreferrer">
            <Button variant="outline" size="sm" type="button">
              <Calendar className="me-1.5 h-3.5 w-3.5" aria-hidden />
              {t("tutor.costCap.bookCall")}
            </Button>
          </a>
        )}
      </div>
    </div>
  );
}
