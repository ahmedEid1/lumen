import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Catalog", template: "%s · Lumen" },
  description: "Browse Lumen's catalogue of AI-grounded courses.",
};

export default function CoursesLayout({ children }: { children: React.ReactNode }) {
  return children;
}
