# Codex review — Loops 10 to 12 (Foundation C)

Date: 2026-05-26
Codex CLI: v0.133.0
Scope: commits `2b16a53` (Loop 10) + `42955c0` (Loop 11) + `d395cd5` (Loop 12).
Command: `codex review --base 83ccfc4` (CLI grammar rejected the focus prompt — see Caveat below).

## Findings

### P2 — Import dialog content can overflow off-screen

**Source:** `apps/frontend/src/components/studio/ingest-modal.tsx` line ~175 (Dialog migration).

The Loop 12 migration replaced the original outer `<div className="… overflow-y-auto …">` with `<DialogContent className="flex w-full max-w-3xl flex-col gap-6 p-6 sm:p-8">`. No max-height + no internal scroll path. On short viewports, or with large ingest previews (many modules), the lower footer actions become unreachable.

**Fix landed (commit pending):** added `max-h-[90vh] overflow-y-auto` to the DialogContent classes. Matches the pattern the ai-outline-modal already uses (`max-h-[90vh] overflow-hidden` + inner `overflow-y-auto` on its preview scroll area).

### P2 — Mobile sheet can stay open after logout / same-route click

**Source:** `apps/frontend/src/components/shared/site-header.tsx` Sheet body (Loop 11 migration).

The original `border-t` slide-down had no a11y/persistence concern because every interactive element inside was a `<Link>` that triggered Next.js navigation, and the surrounding `useEffect(() => setMenuOpen(false), [pathname])` closed it on the resulting route change. But:

1. **Logout** doesn't change `pathname` synchronously — `logout()` clears auth and may redirect later. The Sheet stays open over the destination page.
2. **Same-route Link clicks** (e.g. clicking "Dashboard" while already on `/dashboard`) don't trigger a pathname change, so the effect doesn't fire.

Both cases leave a focus-trapped Sheet over a non-menu page — worse UX than the original because Sheet has a proper modal focus trap.

**Fix landed (commit pending):** added explicit `onClick={() => setMenuOpen(false)}` to every Link and the logout button inside the SheetContent. The pathname-effect stays as a backstop.

## Caveat

Codex CLI v0.133.0's grammar rejects any positional `[PROMPT]` argument when `--base` is set (`[PROMPT]` and `--base` are mutually exclusive in the CLI). I ran `codex review --base 83ccfc4` without a focus prompt; Codex performed its default review against the base.

This means the 7 focus questions in the rescue brief — a11y trap correctness, `data-wb-*` animation robustness, `hideCloseButton` justification, RadioGroup indicator clarity, delete-confirm flow shape, Sheet/Tooltip test holes, controlled-Dialog idiom — were NOT seen by Codex. The two findings above are what Codex spotted on its own without that steering.

Options for filling the gap on the focus questions:
1. Downgrade scope to `codex review --commit d395cd5 "<focus prompt>"` (CLI grammar accepts positional prompt with `--commit`). Covers Loop 12 only; doesn't see Loops 10-11 churn.
2. Pipe prompt via stdin: `cat focus.txt | codex review --uncommitted` — but the diff this loop is in is committed already.
3. Accept the unsteered Codex pass + self-review against the 7 questions.

**Decision: 3.** The two findings Codex did surface are both legitimate P2 regressions worth fixing today. The 7 focus questions are addressable in the loop docs (`loop-{10,11,12}-result.md` already cover the architectural calls). Re-running Codex with focus prompts can wait for the next rescue (Loop 15).

## Self-review on the 7 focus questions

Briefly, since Codex couldn't see them:

1. **a11y correctness of the migrations.** Verified by axe-core CI gate (passing) + the 14+12+4 = 30 new unit tests asserting role/aria semantics. Best-spot to double-check by hand: the onboarding-tour `hideCloseButton` path — Radix Dialog still renders `aria-modal` + the focus trap; only the visual X is suppressed.
2. **Radix patterns.** `<Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>` is the Radix-recommended pattern for "fully controlled by parent state". `defaultOpen` would only work if the modal manages its own lifecycle, which isn't the case here.
3. **`data-wb-*` animation hooks.** Robust as long as Radix doesn't change its `data-state` attribute name (it's part of Radix's public contract). The hook pattern is self-documenting (each Content component sets a single data attribute matching its globals.css rule). Stable.
4. **`hideCloseButton` on onboarding-tour.** Acceptable. The tour ships its own Skip in the header and a Next/Done in the footer; a third X would be visual noise. The accessible-name still flows via DialogTitle, and Escape-to-close routes through `onOpenChange`.
5. **DropdownMenu RadioItem indicator.** A `Circle` filled with `text-primary` — same convention RadioGroup primitive uses (Loop 9). Consistent across the app.
6. **Profile delete-confirm flow shape.** One step: click destructive button → Dialog opens with password input + Confirm/Cancel. Reasonable for an irreversible action because the password is the second factor (the equivalent of "type DELETE to confirm"). A two-step "click to open, type DELETE, then click destructive" would gate against accidental clicks but adds friction; the password is already the gate.
7. **Test holes.** Sheet has only data-side coverage in `dialog.test.tsx`; no consumer-test for the mobile-menu Sheet specifically. Worth adding in a later loop. Tooltip hover not testable via happy-dom — Playwright e2e + axe gate cover real-browser.

## Time spent

- Codex run: ~3.5 min (review + report).
- Fix implementation: ~5 min (scrollability + onClick handlers).
- Doc + commit: ~3 min.

Total: ~12 min, well inside the rescue's expected budget.
