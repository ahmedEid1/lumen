/**
 * Shared notification model helpers — used by the bell popover and the
 * /notifications inbox page so both surfaces deep-link and label rows
 * identically.
 */

export type NotificationItem = {
  id: string;
  kind: string;
  title: string;
  body: string;
  data: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
};

/** Cursor page from GET /me/notifications/inbox. */
export type NotificationInboxPage = {
  items: NotificationItem[];
  next_cursor: string | null;
};

/**
 * Map a notification to a deep-link URL using its kind + data payload.
 *
 * Returns null for kinds that are deliberately non-navigable:
 * - `security.*` — admin heads-up rows; there is no per-event page (the
 *   audit log is the system of record). Read/delete still work.
 * - `account.suspended` — the actionable surface is support, not a page.
 * Unknown future kinds also return null (renders as a plain row) rather
 * than guessing a target.
 *
 * The `/courses/{key}` route resolves slug OR id server-side
 * (`courses_service.slug_or_id`), so linking by course_id is safe.
 */
export function targetHref(n: NotificationItem): string | null {
  const d = n.data || {};
  switch (n.kind) {
    case "enrolled":
    case "lesson_available":
    case "certificate_ready":
      return d.course_id ? `/courses/${d.course_id}` : null;
    case "review_received":
      return d.course_id ? `/courses/${d.course_id}#reviews` : null;
    case "discussion_reply":
      return d.discussion_id && d.course_id
        ? `/courses/${d.course_id}/discussions/${d.discussion_id}`
        : null;
    // The origin owner is told someone cloned their course — link them to
    // the course that was cloned (their own listing).
    case "course_cloned":
      return d.origin_course_id ? `/courses/${d.origin_course_id}` : null;
    default:
      return null;
  }
}
