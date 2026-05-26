# Loop 15 — goal

**Auth polish + Codex rescue #4** — per AUDIT.md §3 (Auth surfaces) + §7 row 15.

Local-first workflow from this loop on: lint + typecheck + unit tests + dev-browser walk + axe-locally pass before any push.

## Why now

- Auth surfaces are 6 polished but feature-thin pages. AUDIT.md flagged: no show/hide password, no strength meter, no confirm field on register, no T&C checkbox, double-mount can burn verify tokens, residual nested `<Link><Button>`.
- Foundations A-E closed in Loops 10-14. The 12 surface loops in §7 start now.
- Codex rescue cadence anchors at Loop 15 (Loops 13/14/15 close out the form-input + table tier).

## What "done" looks like

1. **`<PasswordInput>` primitive** — wraps `<Input>` + adds an Eye/EyeOff toggle on the trailing edge. Used by `/login`, `/register`, `/reset-password` (and `/profile` password change in a future loop). Accessible: button has translated `aria-label`, Input retains its `type="password"`/`text` swap.
2. **`<PasswordStrengthMeter>` primitive** — 5-bar visual indicator + textual feedback. Pure-JS score (no zxcvbn dep — small heuristic: length + class diversity). Used by `/register`.
3. **`/register`:**
   - Replace plain password Input with PasswordInput + meter below.
   - Add confirm-password PasswordInput with inline match validation.
   - Add T&C/privacy Checkbox with link to terms (placeholder href for now — we don't have a /terms page yet, link to /).
4. **`/login`:**
   - Replace plain password Input with PasswordInput.
5. **`/reset-password`:**
   - Replace plain password Input with PasswordInput.
6. **`/verify-email`** + **`/confirm-email-change`:**
   - Add `useRef`-based idempotency guard so React 19 strict-mode double-invoke OR a refresh doesn't burn the token. Pattern: `if (calledRef.current) return; calledRef.current = true;` inside the verify effect.
7. **Nested `<Link><Button>` sweep:**
   - Find remaining instances (Loop 4 hit auth surfaces; check reset-password + verify-email + course-detail-view + studio).
   - Convert to `<Link asChild><Button>...</Button></Link>` OR the existing `<LinkButton>` primitive.
8. **Tests:**
   - PasswordInput: toggle visibility, aria-label flips, value preserved across toggle.
   - PasswordStrengthMeter: score thresholds, label text.
   - Register: confirm-mismatch surfaces inline error, T&C-unchecked disables submit, T&C-checked enables.
   - Verify-email idempotency: assert API called exactly once across double-mount.
9. **Local verification** (don't skip):
   - `make test.web` green.
   - `pnpm exec eslint .` clean (0 errors).
   - `pnpm exec tsc --noEmit --incremental false` clean.
   - `make up` + walk the 5 surfaces in dev browser at `http://localhost:3000`.
   - Local `accessibility.spec.ts` via Playwright against the local stack.
10. **Codex rescue #4** at the end — `codex review --base <pre-loop-15-sha>`. Address legit findings IN-LOOP before pushing.
11. **Single push** when batch is ready. CI + deploy + prod visual review (including auth-gated routes per new ritual).

## Out of scope

- /profile password-change UX (its own polish window).
- 2FA / TOTP / WebAuthn. Future Phase F.
- Real /terms + /privacy pages (just link placeholders).
- Email-verified-required gating (already in place in middleware).
- T&C i18n keys beyond English + Arabic.

## Success criteria

- [ ] PasswordInput primitive + tests ship.
- [ ] StrengthMeter primitive + tests ship.
- [ ] Register form has confirm + T&C + meter.
- [ ] Login + reset-password use PasswordInput.
- [ ] Verify-email + confirm-email-change have idempotency guards.
- [ ] Nested Link>Button audit done (0 remaining outside the primitives' own asChild).
- [ ] `make test.web`: green, file count grows by 2.
- [ ] Local lint + typecheck + axe: clean.
- [ ] Single push, CI passes on first try, deploy + visual review pass.
- [ ] Codex rescue digest written, P2+ findings addressed.
