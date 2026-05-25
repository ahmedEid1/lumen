import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  poweredByHeader: false,
  // ESLint runs in CI on every PR (.github/workflows/ci.yml lint job) — failing
  // the prod build on lint errors is duplicate enforcement that mostly hurts
  // operators trying to deploy a working branch with warnings still in flight.
  // CI remains the source of truth for lint; prod builds only fail on type or
  // runtime errors. The KI-list-equivalent `any` cleanup is tracked separately.
  eslint: {
    ignoreDuringBuilds: true,
  },
  experimental: {
    typedRoutes: true,
  },
  // proxy /api/v1/* through Next so browser-side fetches
  // are same-origin. The auth cookies are SameSite=Strict — a
  // direct browser→api request from web:3000 to api:8000 (the e2e
  // container case) is cross-site and the cookie never travels,
  // and there's no Bearer-token fallback in the call sites. Routing
  // through Next.js makes the request same-origin for both the
  // host browser (localhost:3000) and the Playwright browser
  // (web:3000), avoiding CORS + the SameSite trap in one shot.
  async rewrites() {
    const internal = process.env.API_INTERNAL_BASE_URL ?? "http://api:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${internal}/api/v1/:path*`,
      },
    ];
  },
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost" },
      { protocol: "http", hostname: "s3" },
      { protocol: "https", hostname: "**" },
    ],
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default config;
