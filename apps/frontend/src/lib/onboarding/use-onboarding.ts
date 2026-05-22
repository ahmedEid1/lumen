"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * First-login onboarding visibility hook.
 *
 * Persistence is intentionally localStorage-only for v1 — no backend
 * field. The tour describes intended product shape and only fires for
 * brand-new users; a localStorage miss after device-reset that re-shows
 * the tour is acceptable UX (a fresh device is functionally a fresh
 * onboarding moment). When the spec calls for synced state across
 * devices, swap to a `me.onboarding_seen_at` column without changing
 * the consumer surface.
 *
 * The hook intentionally starts ``visible = false`` so SSR + the first
 * hydration paint never mount the modal; the effect on mount reads
 * localStorage and flips it on iff the flag is absent. That avoids the
 * tour briefly flashing for returning users on slow hydration.
 *
 * @param storageKey Full key, e.g. ``"lumen.onboarding.learner.dismissed"``.
 *                   Caller owns the key shape so we can add roles later
 *                   without rewriting this hook.
 */
export function useOnboarding(storageKey: string): {
  visible: boolean;
  dismiss: () => void;
  complete: () => void;
} {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const seen = window.localStorage.getItem(storageKey);
      if (seen !== "1") setVisible(true);
    } catch {
      // Private-mode / storage-disabled — treat as "already seen" so we
      // don't pester users on every navigation when we can't persist.
    }
  }, [storageKey]);

  const persist = useCallback(() => {
    try {
      window.localStorage.setItem(storageKey, "1");
    } catch {
      // Best-effort — see comment above.
    }
  }, [storageKey]);

  const dismiss = useCallback(() => {
    persist();
    setVisible(false);
  }, [persist]);

  // ``complete`` is semantically distinct from ``dismiss`` even though
  // both currently set the same flag — analytics in a future iteration
  // will care which path the user took.
  const complete = useCallback(() => {
    persist();
    setVisible(false);
  }, [persist]);

  return { visible, dismiss, complete };
}
