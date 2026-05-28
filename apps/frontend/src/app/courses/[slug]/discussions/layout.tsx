import type { Metadata } from "next";

// The discussions pages are client components, so they can't export
// metadata themselves — without this server layout they inherit the
// /courses segment's "Catalog · Lumen" title, which is wrong on a
// Discussions page. The string title resolves through the parent
// template ("%s · Lumen") to "Discussions · Lumen" and also covers the
// nested single-thread route.
export const metadata: Metadata = {
  title: "Discussions",
};

export default function DiscussionsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
