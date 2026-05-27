import type { Metadata } from "next";
import { CaseStudyView } from "./case-study-view";

/**
 * L30 — `/case-study`.
 *
 * The long-form narrative companion to /eval. Founding story
 * expanded from the README opener; architecture sketch; what got
 * built and what got deliberately skipped; lessons.
 *
 * Server-rendered shell + client child for i18n string resolution
 * (matches the app's existing pattern).
 */
export const metadata: Metadata = {
  title: "Case study",
  description:
    "Lumen — case study. How an agentic AI tutor was built end-to-end on a real LLM budget; what got skipped, what got measured, what changed mid-flight.",
  openGraph: {
    title: "Lumen — Case study",
    description:
      "How an agentic AI tutor was built end-to-end on a real LLM budget. Architecture, prompt iteration, what I did not use, what I'd do differently.",
    type: "article",
  },
};

export default function CaseStudyPage() {
  return <CaseStudyView />;
}
