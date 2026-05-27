import { redirect } from "next/navigation";

/**
 * L20.5 — one-click demo deep-link. QA-loop iter 1 — anonymous rescue.
 *
 * Server-side redirect to the TypeScript Generics/Variance course
 * with the AI tutor mounted-open and the canonical demo question
 * prefilled. The lesson picker lands the visitor on the "canonical
 * error" lesson — the one the tutor's RAG answer cites back.
 *
 * Auth: `/learn/[slug]` is auth-gated. Anonymous visitors arriving
 * at /demo used to hit the bare "Sign in to open this course" wall
 * with no path forward (the seeded demo creds live in the README,
 * which a recruiter clicking through has no reason to look at). We
 * now route via `/login?demo=1&next=<learn-url>` so the login page
 * can pre-fill the public demo credentials, surface a callout that
 * tells the visitor those creds exist on purpose, and one-click them
 * straight into the experience. The next-url is encoded once so the
 * `?` inside it doesn't get reinterpreted by the login page's own
 * searchParams parser.
 */

// The canonical demo question. Locked here so the URL the screencap
// records is stable.
const CANONICAL_QUESTION =
  "I keep getting `Type 'string' is not assignable to type 'T'` on this function — here's my code, why does this happen and how do I fix it?";

// The lesson the tutor should ground its first answer in. The frontend's
// `/learn` page resolves this slug-hint to the lesson id at render time.
const CANONICAL_LESSON_TITLE_HINT = "canonical-error";

export default function DemoPage() {
  const learnQuery = new URLSearchParams({
    tutor: "open",
    q: CANONICAL_QUESTION,
    lesson: CANONICAL_LESSON_TITLE_HINT,
  });
  const learnUrl = `/learn/typescript-variance?${learnQuery.toString()}`;
  const loginQuery = new URLSearchParams({
    demo: "1",
    next: learnUrl,
  });
  redirect(`/login?${loginQuery.toString()}`);
}
