// Public env (NEXT_PUBLIC_*) is statically inlined by Next.js at build time.

export const env = {
  API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  WS_BASE_URL: process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8000",
  /** Server-only override for SSR fetchers running inside the container. */
  API_INTERNAL_BASE_URL:
    process.env.API_INTERNAL_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://api:8000",
} as const;
