/**
 * Supported UI locales.
 *
 * Adding a third locale: add the code here, create a messages/<code>.ts
 * with the full key set, set `dir: 'rtl'` if the script reads right-to-
 * left, and add the BCP-47 label to LOCALE_LABELS.
 */
export const LOCALES = ["en", "ar"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

export const LOCALE_DIR: Record<Locale, "ltr" | "rtl"> = {
  en: "ltr",
  ar: "rtl",
};

export const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
  ar: "العربية",
};

export function isLocale(value: string | null | undefined): value is Locale {
  return value === "en" || value === "ar";
}
