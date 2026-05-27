import type { Metadata } from "next";
import { EvalMethodologyView } from "./eval-methodology-view";

/**
 * L28 — `/eval/methodology` (interview-ready milestone).
 *
 * The narrative companion to `/eval`. Recruiters reading the public
 * surface want to know HOW the numbers were produced — what gets
 * judged, by whom, against what rubric, what the corpus shape is,
 * and what the operator (Ahmed) would do differently if they were
 * scaling this past the demo. This is the closing argument.
 */
export const metadata: Metadata = {
  title: "Eval methodology",
  description:
    "How the Lumen tutor is evaluated — what we measure, the LLM-as-judge rubric, the adversarial probe design, known limits, and what would change at scale.",
  openGraph: {
    title: "Lumen — Eval methodology",
    description:
      "How the Lumen tutor is evaluated. LLM-as-judge + adversarial probes; known limits and trade-offs.",
    type: "article",
  },
};

export default function EvalMethodologyPage() {
  return <EvalMethodologyView />;
}
