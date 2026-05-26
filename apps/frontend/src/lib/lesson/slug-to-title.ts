/**
 * Convert a kebab/slug-cased course identifier into a readable
 * Title Case string for UI display.
 *
 * Example:
 *   "data-structures-essentials" → "Data Structures Essentials"
 *   "async-web-apps-in-fastapi"  → "Async Web Apps In Fastapi"
 *
 * Loop 17 introduced this as the pragmatic fix for AUDIT.md §3
 * Path: "MilestoneTable.tsx renders course_slug (URL string) as
 * the display title → user sees `cool-stuff-101` instead of
 * 'Cool Stuff 101'." The real fix would be to add `course_title`
 * to the LearningPathStepOut backend shape; this helper keeps
 * the frontend usable without a backend change.
 *
 * Imperfect: doesn't handle proper nouns (FastAPI becomes
 * Fastapi) and doesn't drop trailing version numbers (101 stays
 * literal). Acceptable trade-off — better than the raw slug.
 */
export function slugToTitle(slug: string): string {
  return slug
    .split("-")
    .map((word) =>
      word.length === 0 ? word : word[0].toUpperCase() + word.slice(1),
    )
    .join(" ");
}
