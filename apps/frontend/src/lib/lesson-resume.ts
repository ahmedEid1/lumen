import type { LessonOut } from "@/lib/api/types";

/**
 * Pick the lesson the learner should land on when they open /learn.
 *
 * Resume-where-you-left-off: prefer the first lesson without
 * ``completed: true``. If every lesson is done (or none exist with
 * a completion flag), fall back to the first lesson in the syllabus.
 * Returns ``null`` only when the course has no lessons at all.
 *
 * Pulled out of the /learn page so it can be unit-tested without
 * spinning up TanStack + auth + router mocks.
 */
export function pickResumeLessonId(lessons: LessonOut[]): string | null {
  if (lessons.length === 0) return null;
  const next = lessons.find((l) => !l.completed) ?? lessons[0];
  return next.id;
}
