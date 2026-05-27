import { redirect } from "next/navigation";

/**
 * L20.5 — one-click demo deep-link.
 *
 * Server-side redirect to the TypeScript Generics/Variance course
 * (seeded by `app/seeds/ts_variance_demo.py`) with the AI tutor
 * mounted-open and the canonical demo question prefilled. The lesson
 * picker lands the visitor on the "canonical error" lesson — the one
 * the tutor's RAG answer cites back.
 *
 * Why this URL shape: `/learn/[slug]` reads its tutor state and
 * composer prefill from `searchParams` (added in L20.5 alongside this
 * route), so a redirect is enough. Anonymous visitors hit the
 * existing sign-in prompt — Lumen's demo learner creds
 * (demo@lumen.test / Demo!2026) are documented in the README so the
 * journey from "I saw the screencap" to "I clicked /demo and watched
 * the tutor work" stays in two clicks.
 *
 * The redirect URL is composed from constants only, so Next can
 * generate this route statically without runtime work. No
 * `dynamic = "force-static"` annotation needed — Next infers it.
 */

// The canonical demo question. Locked here so the URL the screencap
// records is stable. Lockdown of the *content* of this question is
// gated on the 10/10 tool-sequence eval in L25; until then this is the
// production-tested draft.
const CANONICAL_QUESTION =
  "I keep getting `Type 'string' is not assignable to type 'T'` on this function — here's my code, why does this happen and how do I fix it?";

// The lesson the tutor should ground its first answer in. The slug is
// stable because the seed is idempotent and the lesson order is fixed
// by index inside its module (`order=1` in module 2 — "The canonical
// error" lesson). The frontend's `/learn` page resolves this to the
// lesson id at render time.
const CANONICAL_LESSON_TITLE_HINT = "canonical-error";

export default function DemoPage() {
  const params = new URLSearchParams({
    tutor: "open",
    q: CANONICAL_QUESTION,
    lesson: CANONICAL_LESSON_TITLE_HINT,
  });
  redirect(`/learn/typescript-variance?${params.toString()}`);
}
