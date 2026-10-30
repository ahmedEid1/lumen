import type { Metadata } from "next";
import { BlogIndex } from "./blog-index";

export const metadata: Metadata = {
  title: "Blog",
  description:
    "Notes from building Lumen — architecture decisions, prompt-iteration journals, and the failures that shaped what shipped.",
  openGraph: {
    title: "Lumen — Blog",
    description:
      "Notes from building Lumen. Architecture decisions, prompt-iteration journals, cost-latency math.",
    type: "website",
  },
  // No posts yet: keep the empty index out of search results. It is
  // also left out of sitemap.ts. Drop both once the first post lands.
  robots: { index: false, follow: true },
};

export default function BlogIndexPage() {
  return <BlogIndex />;
}
