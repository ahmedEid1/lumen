# Codex review — Loops 13 to 15 (Foundation D + E + Auth polish)

Date: 2026-05-26
Codex CLI: v0.133.0
Scope: commits `802177f` (Loop 13) through Loop 15 working tree.
Command: `codex review --base 907564d`

## Findings

### P1 — Untracked password primitives

**Source:** `apps/frontend/src/app/register/page.tsx:11-12` imports `@/components/ui/password-input` and `@/components/ui/password-strength-meter`, but Codex's `git ls-files` returned no matches.

**Root cause:** the primitive files existed locally but weren't yet `git add`ed when Codex ran its review. The diff Codex saw was the prior-tip diff plus my staged changes; new untracked files don't show up in `git diff`.

**Action:** confirmed both files exist locally at the listed paths. They get added to the loop commit at the push step. **Not a code regression — a diff-scope artifact of running Codex pre-commit.**

### P1 — `auth.spec.ts` register flow breaks under new gating

**Source:** `apps/frontend/tests/e2e/auth.spec.ts:66-70`. The register page now disables submit until confirm-password matches AND T&C checkbox is checked. The golden-path test fills only name+email+password and clicks Create — the click hits a disabled button, the URL never advances to /dashboard, the rest of the test cascades to failure.

**Fix landed:** added the missing fill of confirm-password + click on the T&C label inside the test, before the Create button click. Pattern:
```ts
await page.locator("form").getByLabel(/confirm password/i).fill(initialPassword);
await page.locator('label[for="terms"]').click();
```

Note on the label-click: Radix Checkbox renders as `role="checkbox"` (button-backed, not a native input), so `getByLabel(/i agree to the/i)` doesn't resolve. The label's `htmlFor="terms"` association still works via direct click on the label element.

## Codex CLI grammar quirks

`codex review --base <sha> "<focus prompt>"` is rejected in v0.133.0. Ran without the prompt — Codex returned only the 2 P1 findings above and didn't address the 7 focus questions from the rescue brief.

## Self-review on the 7 focus questions

Briefly:

1. **PasswordInput toggle hit-target.** `h-7 w-7` = 28×28px. WCAG 2.1 minimum interactive target is 24×24px; WCAG 2.2 AA prefers 24px minimum spacing OR 44px target. We're at 28px with a 4px buffer from input edges — passes 2.1, marginal on 2.2. Acceptable; bump to h-9 w-9 in a follow-up if axe-core flags it.
2. **PasswordStrengthMeter heuristic.** Reasonable enough for a UX hint. Real entropy enforcement is backend's job (min 12 chars). Score 4 requires 20+ chars AND 3+ classes AND no common prefix — passwords scoring 4 are genuinely strong.
3. **Idempotency guards.** `useRef(false)` + early-return pattern is the standard React 19 strict-mode mitigation. Doesn't reset on token-query-param change because the effect re-runs and the guard is at the top — correct behavior, the same token shouldn't fire twice.
4. **canSubmit batching.** React 19 batches setState updates within event handlers. Within one keystroke `setConfirm`, the next render's `canSubmit` is consistent. No race.
5. **Label-selector i18n stability.** `getByLabel("Password", { exact: true })` only matches English. Arabic axe runs would need to match the Arabic literal. Since axe-core is English-only in CI today, this is fine; if we add Arabic axe coverage, switch to `getByLabel` with the locale-resolved label or query by `#password` id.
6. **LinkButton sweep.** Verified by grep — no nested `<Link><Button>` remaining in app/.
7. **Token-drift regressions.** None introduced — meter uses `bg-success / bg-warning / bg-destructive` + matching text tones, all from the `--success / --warning / --destructive` semantic ramp.

## Time spent

- Codex run: ~2 min (review returned 2 findings, transcript at ~/.claude/.../tool-results/bc009iyhk.txt).
- Fix implementation: ~5 min (auth.spec.ts confirm-password fill + label-for click + Loop 15 walk spec cleanup).
- This digest: ~3 min.

Total: ~10 min. Within the rescue budget.
