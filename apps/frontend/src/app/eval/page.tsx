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
    "Public eval surface — how the Lumen tutor scores on its golden datasets and adversarial probe corpus. Frozen on admin-promoted runs.",
  openGraph: {
    title: "Lumen — Public eval",
    description:
      "How the tutor scores. Golden datasets + LLM-as-judge + adversarial refusal-rate; frozen on admin-promoted runs.",
    type: "website",
  },
};

export default function EvalPage() {
  return <EvalPublicView />;
}
