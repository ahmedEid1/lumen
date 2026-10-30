import type { MetadataRoute } from "next";
import { env } from "@/lib/env";

// Like sitemap.ts: regenerate at runtime so the host comes from the
// runtime NEXT_PUBLIC_API_BASE_URL. Without this, Next prerenders
// robots.txt during `pnpm build`, where the variable is unset, and the
// file points crawlers at localhost.
export const revalidate = 3600;

function siteUrl(): string {
  // NEXT_PUBLIC_API_BASE_URL is the API origin; the frontend lives on the same
  // host in production behind the reverse proxy, so we strip any /api suffix.
  try {
    const url = new URL(env.API_BASE_URL);
    return `${url.protocol}//${url.host}`;
  } catch {
    return "http://localhost:3000";
  }
}

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/courses", "/verify/"],
        // Routes that require authentication or expose admin-only surface
        // shouldn't end up in search results.
        disallow: [
          "/dashboard",
          "/profile",
          "/learn/",
          "/studio",
          "/studio/",
          "/admin",
          "/admin/",
          "/login",
          "/register",
          "/reset-password",
          "/forgot-password",
          "/verify-email",
          "/api/",
        ],
      },
    ],
    sitemap: `${siteUrl()}/sitemap.xml`,
    host: siteUrl(),
  };
}
