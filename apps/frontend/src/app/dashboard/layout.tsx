import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Dashboard", template: "%s · Lumen" },
  description: "Your learning activity, mastery, and review queue on Lumen.",
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return children;
}
