"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { en, type MessageKey } from "./messages/en";
import { ar } from "./messages/ar";
import {
  DEFAULT_LOCALE,
  LOCALE_DIR,
  type Locale,
  isLocale,
} from "./locales";

const MESSAGES: Record<Locale, Record<MessageKey, string>> = { en, ar };

type LocaleCtx = {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
};

const Ctx = createContext<LocaleCtx | null>(null);

const STORAGE_KEY = "lumen.locale";

function pickInitialLocale(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (isLocale(stored)) return stored;
  // Fall back to browser language if it's one we support — gives an
  // Arabic-locale browser the right default on first visit without
  // requiring the user to find the switcher.
  const nav = window.navigator.language.toLowerCase();
  if (nav.startsWith("ar")) return "ar";
  return DEFAULT_LOCALE;
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  // Hydration: SSR renders with DEFAULT_LOCALE; the effect below
  // swaps to the persisted choice on mount. Brief flash is acceptable
  // — alternative is a cookie-driven SSR pass which adds infra weight.
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);

  useEffect(() => {
    const initial = pickInitialLocale();
    setLocaleState(initial);
  }, []);

  // Keep <html lang dir> in sync so the browser applies the right
  // typography defaults (Arabic shaping, RTL bidirectional algorithm).
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.lang = locale;
    document.documentElement.dir = LOCALE_DIR[locale];
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private mode / storage disabled — pick survives in memory only.
    }
  }, []);

  const t = useCallback(
    (key: MessageKey, vars?: Record<string, string | number>) => {
      const dict = MESSAGES[locale] ?? MESSAGES[DEFAULT_LOCALE];
      let s = dict[key] ?? MESSAGES[DEFAULT_LOCALE][key] ?? key;
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          s = s.replaceAll(`{${k}}`, String(v));
        }
      }
      return s;
    },
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLocale(): LocaleCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLocale must be used inside <LocaleProvider>");
  return v;
}

/** Read-only ``t`` for components that don't need to switch locale. */
export function useT() {
  return useLocale().t;
}
