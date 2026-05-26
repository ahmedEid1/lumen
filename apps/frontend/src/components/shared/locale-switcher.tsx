"use client";

import { Languages } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LOCALES, LOCALE_LABELS, type Locale } from "@/lib/i18n/locales";
import { useLocale, useT } from "@/lib/i18n/provider";

/**
 * Locale picker. Was a cycle button (`[en→ar→en→...]`) when LOCALES
 * had only 2 entries — adding Radix DropdownMenu for two options
 * wasn't worth the bytes. With DropdownMenu shipped in Loop 11, the
 * trade-off flipped: a real picker is ~25 LoC, future-proofs for a
 * 3rd locale, and means screen-reader users hear "menu, 2 items"
 * instead of a label that mutates on each click.
 *
 * `aria-label` literal `${t("common.language")}: ${LOCALE_LABELS[locale]}`
 * is preserved so `tests/locale-switcher-aria.test.ts` keeps passing
 * and the e2e regex in `learner-journey.spec.ts:71` (`/language|اللغة/i`)
 * keeps matching.
 */
export function LocaleSwitcher() {
  const { locale, setLocale } = useLocale();
  const t = useT();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`${t("common.language")}: ${LOCALE_LABELS[locale]}`}
        >
          <Languages className="h-5 w-5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[8rem]">
        <DropdownMenuLabel>{t("common.language")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={locale}
          onValueChange={(v) => setLocale(v as Locale)}
        >
          {LOCALES.map((l) => (
            <DropdownMenuRadioItem key={l} value={l}>
              {LOCALE_LABELS[l]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
