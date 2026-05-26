# Final Codex review — full Loop 0 → Loop 20 diff

Date: 2026-05-27
Codex CLI: v0.133.0
Scope: commits `c3450a8` (pre-Loop-1 baseline) through HEAD.
Command: `codex review --base c3450a8 --title "Lumen UI redesign FINAL — Loop 20 closing pass"`

## Findings

**Two P2 findings, both in Playwright e2e test infrastructure. No P0/P1. No user-facing regressions.**

### P2 — auth.setup.ts cookie domain mismatch (docker-compose only)

**Source:** `apps/frontend/tests/e2e/auth.setup.ts:63`.

When the docker-compose e2e profile sets `E2E_API_BASE_URL=http://api:8000`, the setup POSTs login direct to the API origin (`api`). The Set-Cookie response stores host-only cookies for `api`. The browser later navigates to `http://web:3000` and those cookies aren't sent — so the saved `.auth/<role>.json` is actually unauthenticated in the docker-compose container case. Host-mode runs (where both API and web share `localhost`) hide the bug.

**Fix landed:** rewrote the setup to use the test-fixture `request` (which respects `baseURL`) and POSTs `/api/v1/auth/login` through the web origin. Next.js's `rewrites()` already forwards `/api/v1/*` to the internal API URL, so the request still hits FastAPI but cookies are scoped to the web host. Verified by re-running `accessibility.spec.ts --grep "student dashboard"` against the docker-compose stack → 4/4 passed including the new auth.

### P2 — Setup tests run again in browser projects

**Source:** `apps/frontend/playwright.config.ts:53` (chromium project) and `:58` (webkit).

Playwright's glob discovery picks up `auth.setup.ts` from `testDir`, so both the `setup` project AND the `chromium`/`webkit` projects discover and execute the 3 auth setup tests. The browser projects then re-run setup in parallel with consumer tests, overwriting `.auth/*.json` mid-test → flaky reads.

**Fix landed:** added `testIgnore: /auth\.setup\.ts/` to both browser projects. Setup now runs **only** in the `setup` project, exactly once per test session.

## Coverage of prior rescue findings

The final pass also verified the 6 prior-rescue items are still addressed in HEAD:

- ✓ Loop 12 rescue: `ingest-modal` has `max-h-[90vh] overflow-y-auto` on DialogContent.
- ✓ Loop 12 rescue: mobile-menu Sheet has `onClick={() => setMenuOpen(false)}` on every nav link, profile link, login/register link, and logout button.
- ✓ Loop 15 rescue: `auth.spec.ts` register flow fills confirm-password + clicks T&C checkbox via `getByRole("checkbox")`.
- ✓ Loop 15 rescue: 8 e2e password-label selectors use `getByLabel("Password", { exact: true })`.
- ✓ Loop 16: Course detail decomposed to 5 components + 218-LoC orchestrator.
- ✓ Loop 17: 4 RTL leaks fixed (TraceTimeline, draft-trace-timeline, TraceStepCard, agent-reasoning-panel).

## What Codex did NOT flag

The brief explicitly asked Codex to look at 6 broad-stroke categories: leftover regressions, primitive API consistency, dep bloat, i18n parity, Workbench-rule violations, prior-rescue residue. Codex found nothing in any of those categories. That's a strong signal — 5 of the previous 6 rescues already addressed every cross-cutting concern, and the closing-pass-only-finds-test-infra-issues outcome is the cleanest possible verdict.

## Closing

Both findings landed in this loop's commit. The redesign is complete with **zero user-facing regressions** outstanding from the final review.
