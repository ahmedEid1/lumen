"use client";

import { AlertTriangle } from "lucide-react";
import { useT } from "@/lib/i18n/provider";
import type { LLMValidationStatus } from "@/lib/api/types";

/** Drift / auth-fallback notice (R-M11'). Shows when a credential's last
 * validation flagged needs_attention or invalid. */
export function NeedsAttentionBanner({ status }: { status: LLMValidationStatus }) {
  const t = useT();
  if (status !== "needs_attention" && status !== "invalid") return null;
  const message =
    status === "invalid" ? t("byok.error.providerError") : t("byok.error.modelUnavailable");
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}
