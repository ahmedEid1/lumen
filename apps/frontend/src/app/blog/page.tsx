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
};

export default function BlogIndexPage() {
  return <BlogIndex />;
}
