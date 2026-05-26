import { useEffect, useState } from "react";

/**
 * Returns `false` on the SSR render and on the first client render
 * before `useEffect` flushes; `true` thereafter. Replaces the four
 * copy-pasted `mounted` paragraphs in `app/login/page.tsx:47-58`,
 * `app/register/page.tsx:34-35`, `app/forgot-password/page.tsx:30-31`,
 * `app/reset-password/page.tsx:44-45`.
 *
 * Use when a client-only effect (e.g. a `<Button disabled={!hydrated}>`
 * gate, a portal mount) would otherwise cause a hydration mismatch
 * or a "click before listeners attach" race.
 */
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  return hydrated;
}
