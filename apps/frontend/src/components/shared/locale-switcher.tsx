"use client";

import { Languages } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LOCALES, LOCALE_LABELS } from "@/lib/i18n/locales";
import { useLocale, useT } from "@/lib/i18n/provider";

/**
 * Compact dropdown-free toggle — 2 locales today; we just cycle.
 * Once we hit 3+ this should become a proper dropdown, but adding a
 * Radix dropdown for two options is silly.
 */
export function LocaleSwitcher() {
  const { locale, setLocale } = useLocale();
  const t = useT();
  const next = LOCALES[(LOCALES.indexOf(locale) + 1) % LOCALES.length];
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setLocale(next)}
      title={`${t("common.language")}: ${LOCALE_LABELS[locale]} → ${LOCALE_LABELS[next]}`}
      aria-label={`${t("common.language")}: ${LOCALE_LABELS[locale]}`}
    >
      <Languages className="h-5 w-5" />
    </Button>
  );
}
