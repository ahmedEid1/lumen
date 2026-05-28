import type { Metadata } from "next";

// The lesson player at /learn/[slug] is a client component, so it can't
// export metadata itself — without this server layout it inherits the
// root default title ("Lumen — Learn what you actually use."), which
// reads like the marketing home page rather than a lesson. A static
// "Learn" resolves through the root template ("%s · Lumen") to
// "Learn · Lumen". Kept static (not a per-lesson generateMetadata)
// deliberately: the course/lesson is loaded client-side, and adding an
// SSR fetch here just to title the tab would couple the player to a
// backend round-trip that can fail or slow first paint — same trade-off
// the discussions layout made.
export const metadata: Metadata = {
  title: "Learn",
};

export default function LearnLayout({ children }: { children: React.ReactNode }) {
  return children;
}
