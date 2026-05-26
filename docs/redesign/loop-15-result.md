# Loop 15 — result

Surface: Auth polish — `<PasswordInput>` + `<PasswordStrengthMeter>` primitives, register confirm + T&C gating, idempotency guards on verify flows, LinkButton sweep, Codex rescue #4.

**First loop run under the LOCAL-FIRST workflow** the user introduced 2026-05-26: lint + tsc + tests + dev-browser walk + local axe + Codex rescue, all verified before pushing.

## What shipped

### Primitives
- **`apps/frontend/src/components/ui/password-input.tsx`** (60 LoC). Wraps Input + Eye/EyeOff toggle button. Translated aria-label + aria-pressed.
- **`apps/frontend/src/components/ui/password-strength-meter.tsx`** (90 LoC). 4-segment visual + label. Pure-JS heuristic — no zxcvbn dep.

### Surface changes
- **`/register`** — PasswordInput + Meter + confirm with inline mismatch + T&C Checkbox. `canSubmit` gates submit on all of: hydrated + email + 12+ char password + matching confirm + T&C agreed.
- **`/login`** — native password input → PasswordInput.
- **`/reset-password`** — native password input → PasswordInput.
- **`/verify-email`** — added `useRef`-based idempotency guard.
- **`/confirm-email-change`** — same idempotency guard.

### Hygiene
- **Nested `<Link><Button>` sweep:** home-view.tsx (4 instances — hero + closing CTAs), not-found.tsx, error.tsx all migrated to `<LinkButton>`.
- **8 e2e `getByLabel(/password/i)` callsites** updated to `getByLabel("Password", { exact: true })` — PasswordInput's Eye toggle's aria-label "Show password" was making the regex match 2 elements.
- **`auth.spec.ts` register golden-path** updated for new required confirm + T&C gating.
- **i18n parity:** new keys added to both en + ar (auth.password.show/hide, auth.password.strength.{empty,weak,fair,good,strong}, auth.register.{confirmPassword,confirmMismatch,terms.label,terms.link,terms.required}).

### Tests
- **`apps/frontend/tests/password-input.test.tsx`** (5 tests). Default type, aria-label translation, toggle flips type + label, value preserved, aria-pressed reflects state.
- **`apps/frontend/tests/password-strength-meter.test.tsx`** (10 tests). Scoring heuristic + label rendering.

### Codex rescue #4
- See `docs/redesign/codex-review-loops-13-to-15.md`.
- 2 P1 findings: missing untracked primitives (diff-scope artifact, not a regression) + auth.spec.ts register flow broken (real, fixed in-loop).

## Local-first workflow verification (the NEW ritual)

Before any push:
- [x] `make test.web`: 48 files / 275 tests green.
- [x] `pnpm exec eslint .`: 0 errors (14 pre-existing warnings unrelated to this loop).
- [x] `pnpm exec tsc --noEmit --incremental false`: clean.
- [x] `make up` + dev-browser walk via local Playwright spec:
  - /login: PasswordInput Eye toggle works.
  - /register: meter goes red→amber→green as password strengthens; mismatch shows inline error; T&C unchecked keeps submit disabled.
- [x] Local axe-core suite (`accessibility.spec.ts`): 12 passed, 1 pre-existing flaky (admin-dashboard, same flake as Loop 12, CI retries=2 covers).
- [x] Local `auth.spec.ts` register flow: 4 passed after the gating + checkbox-click fix.
- [x] Codex rescue ran + 2 P1 findings addressed in-loop.
- [ ] Single push then CI + deploy + prod visual review (incl auth-gated) — pending the actual push step.

## Outcome of the workflow change

- **One CI cycle expected** (vs. Loop 14's 5-cycle chain) because:
  - Lint caught locally (would've been Loop 14's `b240b4e` cycle).
  - Axe caught locally (would've been Loop 14's `77fffcb` cycle + accessibility-test cycles).
  - Codex caught register-flow regression locally (would've been a Loop 12-style retroactive fix).
- The `loop-15-walk.spec.ts` was a one-shot Playwright capture for dev-browser visual verification; deleted before commit per the convention.

## Success criteria

- [x] PasswordInput primitive + tests.
- [x] PasswordStrengthMeter primitive + tests.
- [x] /register has confirm + T&C + meter.
- [x] /login + /reset-password use PasswordInput.
- [x] /verify-email + /confirm-email-change have idempotency guards.
- [x] Nested Link>Button sweep done (verified by grep).
- [x] `make test.web`: green.
- [x] Local lint + typecheck + axe: clean.
- [x] Codex rescue digest written, P2+ findings addressed.
- [ ] Single push + CI + deploy + visual review — pending.

## Estimated vs actual diff

| Surface | Estimate (spec) | Actual |
|---|---|---|
| PasswordInput primitive | ~70 LoC | 60 LoC |
| PasswordStrengthMeter primitive | ~120 LoC | 90 LoC |
| /register changes | ~80 LoC | ~80 LoC |
| /login + /reset-password | ~20 LoC | ~10 LoC |
| Verify idempotency guards | ~10 LoC | ~10 LoC |
| Link>Button sweep | ~30 LoC | ~35 LoC |
| e2e label-selector sweep | (not estimated) | ~10 LoC across 6 files |
| auth.spec.ts register flow fix | (not estimated) | ~10 LoC |
| Tests | ~200 LoC | ~180 LoC |
| i18n keys (en + ar) | ~20 LoC | ~25 LoC each |
| Loop docs + Codex digest | ~500 LoC | ~600 LoC |
| STATUS + CHANGELOG | ~40 LoC | ~50 LoC |

**Total source diff: ~600 LoC.** Smaller than Loop 14 (~1500 LoC); auth polish is denser per LoC because it's primitive + form gating, not table migrations.

## Codex rescue cadence

Next Codex rescue lands at the end of Loop 18 per the every-3rd-loop anchor (Loops 16/17/18 are the next tier — provisionally Block-renderer + Mastery viz + Path viz per AUDIT.md §7).
