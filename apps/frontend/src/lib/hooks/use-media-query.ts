"use client";

import { useSyncExternalStore } from "react";

/**
 * L35 — SSR-safe media-query subscription via `useSyncExternalStore`.
 *
 * Why this hook exists: L24 introduced a mobile-only `<Sheet>` rendering
 * of the tutor panel + a desktop inline rendering, both mounted at once
 * with the same `data-testid="tutor-panel"`. The Sheet portals to
 * `document.body` regardless of viewport, so Playwright's strict
 * `getByTestId` flagged two matching elements and the e2e suite went
 * red. L31's rescue reverted to the single inline rendering.
 *
 * The real fix is to only render ONE of the two — gated on viewport.
 * The naive `window.matchMedia` approach mismatches SSR (the server
 * renders one branch, the client hydrates to the other → "hydration
 * mismatch" warning + a flash of the wrong layout on first paint).
 *
 * This hook uses `useSyncExternalStore` so:
 * - The server snapshot is always `serverFallback` (default `false`).
 *   The first render matches what the server emitted → no hydration
 *   warning, no DOM mismatch.
 * - The client snapshot reads `window.matchMedia(query).matches`
 *   AFTER hydration, so the second render shows the correct branch.
 * - Subsequent changes (rotation, devtools resize) re-render
 *   automatically via the matchMedia listener.
 *
 * @param query - e.g. `"(min-width: 1024px)"` for Tailwind `lg:`.
 * @param serverFallback - value returned during SSR + first client
 *   render. Pick the branch you want to render server-side; mobile
 *   (`false`) is the conservative default so server payload stays
 *   small (no inline Sheet markup) and the desktop branch hydrates
 *   in.
 */
export function useMediaQuery(query: string, serverFallback: boolean = false): boolean {
  return useSyncExternalStore(
    (notify) => {
      // `matchMedia` only exists on the client. The server snapshot
      // path (below) never calls into this subscribe function, but
      // `useSyncExternalStore`'s subscribe runs in `useEffect` so
      // it's safe to assume `window` is defined here.
      const mql = window.matchMedia(query);
      mql.addEventListener("change", notify);
      return () => mql.removeEventListener("change", notify);
    },
    () => window.matchMedia(query).matches,
    () => serverFallback,
  );
}
