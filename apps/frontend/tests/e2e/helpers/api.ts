/**
 * Thin fetch wrappers around the live FastAPI backend so e2e tests
 * can introspect state that the UI doesn't surface (e.g. the lesson
 * ids inside a course, which the tutor-citations spec needs to match
 * against the model's response).
 *
 * We deliberately don't reach into ``apps/frontend/src/lib/api`` —
 * those clients are designed for the running app's auth context, not
 * a Playwright runner. Calls here are unauthenticated read-only:
 * catalog reads work without a session.
 */

export const API_BASE_URL = process.env.E2E_API_BASE_URL ?? "http://localhost:8000";

export interface CourseDetailLite {
  id: string;
  slug: string;
  title: string;
  modules: Array<{
    id: string;
    title: string;
    lessons: Array<{ id: string; title: string }>;
  }>;
}

/**
 * Fetch a course detail by slug. Returns the slim shape used by the
 * tutor-citations spec (just enough to enumerate lesson ids).
 */
export async function getCourseBySlug(slug: string): Promise<CourseDetailLite> {
  const url = `${API_BASE_URL}/api/v1/courses/${encodeURIComponent(slug)}`;
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`GET ${url} → ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as CourseDetailLite;
}

/**
 * List published catalog courses. We use this to discover the first
 * seeded course's slug rather than hard-coding it — the seed currently
 * publishes ``fastapi-from-zero`` but the spec should not break if a
 * future seed pass renames or reorders.
 */
export interface CourseListItemLite {
  id: string;
  slug: string;
  title: string;
}

export async function catalogList(): Promise<CourseListItemLite[]> {
  const url = `${API_BASE_URL}/api/v1/courses?page=1&page_size=20`;
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`GET ${url} → ${res.status} ${res.statusText}`);
  }
  const body = (await res.json()) as { items: CourseListItemLite[] };
  return body.items;
}

/**
 * Wait for the live API's health endpoint to respond 2xx. Useful at
 * the top of a spec so we fail fast with a clear message if the dev
 * stack isn't up rather than timing out on the first ``page.goto``.
 */
export async function waitForApiHealthy(timeoutMs = 10_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastErr: unknown = null;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/health/live`);
      if (res.ok) return;
      lastErr = new Error(`status ${res.status}`);
    } catch (e) {
      lastErr = e;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(
    `API never became healthy at ${API_BASE_URL} within ${timeoutMs}ms: ${
      lastErr instanceof Error ? lastErr.message : String(lastErr)
    }`,
  );
}
