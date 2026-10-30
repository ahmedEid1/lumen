import type { Metadata } from "next";
import { EvalPublicView } from "./eval-public-view";

/**
 * L27 — Public `/eval` surface (read-only, no auth).
 *
 * Per plan-v7 §L27, the page leads with ONE worked example (the
 * canonical demo question + the agent's answer + rubric + tool
 * path + cost + first-token), then aggregate charts, then the
 * adversarial pass-rate WITHOUT disclosing the prompts.
 *
 * L27 ships the layout + honest-empty state. The data is
 * placeholder until a sealed admin-promoted run lands — the
 * page is deliberately explicit about that (no fake numbers).
 * Real-data wiring is a follow-up gated on:
 *   1. The L21a AsyncOpenAI streaming integration (so tutor scores
 *      include first-token-ms).
 *   2. The L21-Sec cost-reserve wiring (so cost-per-turn is real).
 *   3. A scheduled adversarial run + promoted snapshot.
 *
 * L28 builds the methodology page on top of this.
 */
export const metadata: Metadata = {
  title: "Eval",
  description:
    "Public eval surface: how Lumen scores on its golden datasets, judged by an LLM. Shows admin-promoted runs only.",
  openGraph: {
    title: "Lumen — Public eval",
    description:
      "How Lumen scores. Golden datasets judged by an LLM, weak scores included; admin-promoted runs only.",
    type: "website",
  },
};

export default function EvalPage() {
  return <EvalPublicView />;
}
