// Public env (NEXT_PUBLIC_*) is statically inlined by Next.js at build time.

const STATIC_API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const STATIC_WS_BASE = process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8000";

/**
 * Browser-side API base.
 *
 * Iter 105 routed all `/api/v1/*` traffic through Next.js's
 * `rewrites()` so the call is same-origin from the browser's POV.
 * That dodges CORS AND the SameSite=Strict cookie trap (the auth
 * cookies are strict; cross-site fetches never carry them) — both
 * for the host-side dev browser at localhost:3000 and for the
 * Playwright browser inside the e2e container at web:3000.
 *
 * The browser therefore uses a relative base (""). The SSR fetcher
 * keeps using API_INTERNAL_BASE_URL because it runs inside the web
 * container with no relative-URL context.
 */
function browserApiBase(): string {
  if (typeof window === "undefined") return STATIC_API_BASE;
  return "";
}

// WebSockets aren't covered by the Next rewrite; keep the direct
// hostname for now. Iter 105 leaves WS behavior unchanged — fix
// in a future iteration if a WS-using spec ever needs the e2e
// container.
function browserWsBase(): string {
  if (typeof window === "undefined") return STATIC_WS_BASE;
  if (window.location.hostname === "web") return "ws://api:8000";
  return STATIC_WS_BASE;
}

export const env = {
  get API_BASE_URL() {
    return browserApiBase();
  },
  get WS_BASE_URL() {
    return browserWsBase();
  },
  /** Server-only override for SSR fetchers running inside the container. */
  API_INTERNAL_BASE_URL:
    process.env.API_INTERNAL_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://api:8000",
} as const;
