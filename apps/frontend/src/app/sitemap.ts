import type { MetadataRoute } from "next";
import { Catalog } from "@/lib/api/endpoints";
import { env } from "@/lib/env";

export const revalidate = 3600;

function siteUrl(): string {
  try {
    const url = new URL(env.API_BASE_URL);
    return `${url.protocol}//${url.host}`;
  } catch {
    return "http://localhost:3000";
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = siteUrl();
  const now = new Date();

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${base}/`, lastModified: now, changeFrequency: "weekly", priority: 1.0 },
    { url: `${base}/courses`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${base}/blog`, lastModified: now, changeFrequency: "weekly", priority: 0.5 },
    { url: `${base}/eval`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    { url: `${base}/eval/methodology`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${base}/case-study`, lastModified: now, changeFrequency: "monthly", priority: 0.8 },
  ];

  // Best-effort enumeration of publicly-LISTED courses (S2.12). The catalog
  // endpoint is already visibility-filtered server-side (publicly_listed_sql),
  // so a private / pending / delisted / quarantined course never appears here.
  // We additionally guard on `visibility === "public"` as defense-in-depth.
  // If the API is unreachable at build/regen time, skip the dynamic entries
  // instead of failing the route — robots/sitemap should never 500.
  let courses: MetadataRoute.Sitemap = [];
  try {
    const page = await Catalog.courses({ page: 1, page_size: 100, sort: "-published_at" });
    courses = page.items
      .filter((c) => c.visibility === "public")
      .map((c) => ({
        url: `${base}/courses/${c.slug}`,
        lastModified: new Date(c.published_at ?? c.created_at),
        changeFrequency: "weekly",
        priority: c.is_featured ? 0.8 : 0.7,
      }));
  } catch {
    courses = [];
  }

  return [...staticRoutes, ...courses];
}
