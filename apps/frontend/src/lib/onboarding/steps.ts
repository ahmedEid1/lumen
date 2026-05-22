/**
 * Onboarding step content for the first-login tour.
 *
 * Two role-specific arrays — learners see the dashboard-flavoured tour,
 * instructors see the studio-flavoured one. Every visible string flows
 * through the i18n ``t`` function so RTL / Arabic users get a faithful
 * translation rather than a fallback key.
 *
 * Some copy here references features that ship in Phase E (the AI
 * tutor, multi-modal ingest, spaced-repetition review). That's
 * intentional — the tour describes the product's *intended* shape, and
 * the spec calls out that copy will be revisited as those features
 * land. Keeping the steps stable now means we don't have to rewire the
 * persistence dismissal key when the features arrive.
 *
 * See ``docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md`` §4
 * Phase D item 3.
 */
import type { MessageKey } from "@/lib/i18n/messages/en";

export type TourStep = {
  /** i18n key for the step title (short, label-like). */
  title: MessageKey;
  /** i18n key for the step body (one sentence, two at most). */
  body: MessageKey;
};

type T = (key: MessageKey, vars?: Record<string, string | number>) => string;

/** Three steps shown to a first-time learner on the dashboard. */
// `t` is accepted but unused for now — kept in the signature so callers
// don't have to thread two things (the array + the translator) when
// rendering. Future copy may pull dynamic counts via `t(..., vars)`.
export function learnerSteps(_t: T): TourStep[] {
  return [
    {
      title: "onboarding.learner.s1.title",
      body: "onboarding.learner.s1.body",
    },
    {
      title: "onboarding.learner.s2.title",
      body: "onboarding.learner.s2.body",
    },
    {
      title: "onboarding.learner.s3.title",
      body: "onboarding.learner.s3.body",
    },
  ];
}

/** Three steps shown to a first-time instructor on the studio root. */
export function instructorSteps(_t: T): TourStep[] {
  return [
    {
      title: "onboarding.instructor.s1.title",
      body: "onboarding.instructor.s1.body",
    },
    {
      title: "onboarding.instructor.s2.title",
      body: "onboarding.instructor.s2.body",
    },
    {
      title: "onboarding.instructor.s3.title",
      body: "onboarding.instructor.s3.body",
    },
  ];
}
