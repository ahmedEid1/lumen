import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Studio", template: "%s · Lumen" },
  description: "Author and manage your Lumen courses.",
};

export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return children;
}
