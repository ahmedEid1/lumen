import type { Metadata } from "next";

// The free-preview lesson view at /courses/[slug]/preview/[lessonId] is a
// client component, so it can't export metadata itself — without this
// server layout it inherits the /courses segment's "Catalog · Lumen"
// title, which is wrong on a single-lesson preview. A static "Preview"
// resolves through the root template ("%s · Lumen") to "Preview · Lumen".
// Static (not per-lesson) for the same reason as the /learn layout: avoid
// an SSR fetch just to title the tab.
export const metadata: Metadata = {
  title: "Preview",
};

export default function PreviewLayout({ children }: { children: React.ReactNode }) {
  return children;
}
