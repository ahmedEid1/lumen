import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Create account",
  description: "Create a free Lumen account.",
};

export default function RegisterLayout({ children }: { children: React.ReactNode }) {
  return children;
}
