import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Admin", template: "%s · Lumen" },
  description: "Operate the Lumen platform.",
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return children;
}
