/**
 * Defend against open-redirect via `?next=`. Returns a path that is
 * provably same-origin (or the dashboard fallback). Threat model:
 * a crafted `/login?next=https://attacker.example` or
 * `/login?next=//attacker.example` would otherwise hand any user who
 * has a session cookie — under the qa-iter1 auto-forward effect —
 * off to a phishing target the instant they touch /login.
 *
 * Same-origin = must start with a single `/` and not look like a
 * protocol-relative path (`//foo`) or a Windows-style traversal
 * (`/\foo`). Anything else falls back to /dashboard.
 *
 * QA-loop iter 1 / Codex rescue #1.
 */
export function safeNext(raw: string | null | undefined): string {
  if (!raw) return "/dashboard";
  if (!raw.startsWith("/")) return "/dashboard";
  if (raw.startsWith("//") || raw.startsWith("/\\")) return "/dashboard";
  return raw;
}
