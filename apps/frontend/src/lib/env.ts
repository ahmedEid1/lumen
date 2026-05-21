// Public env (NEXT_PUBLIC_*) is statically inlined by Next.js at build time.

const STATIC_API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const STATIC_WS_BASE = process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8000";

/**
 * Browser-side API base. In the dev docker stack the bundle is built
 * with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` (so the host
 * browser can reach the published api port). When the same bundle is
 * loaded by Playwright inside the `e2e` container — where the page
 * is served from `http://web:3000` — `localhost` resolves to the e2e
 * container itself and every API call fails silently. Detect that
 * case at runtime and switch to the docker-network hostname (`api`).
 *
 * The condition is intentionally narrow (`hostname === "web"`) so a
 * real prod deployment with hostname `lumen.example.com` keeps using
 * its configured `NEXT_PUBLIC_API_BASE_URL`.
 */
function browserApiBase(): string {
  if (typeof window === "undefined") return STATIC_API_BASE;
  if (window.location.hostname === "web") return "http://api:8000";
  return STATIC_API_BASE;
}

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
