# Loop 3 — Result

## What shipped

Seven primitives + one hook + one vitest spec covering all eight. Zero application — Loop 4 wires them into surfaces.

| File | Lines |
|---|---|
| `apps/frontend/src/lib/use-hydrated.ts` | 21 |
| `apps/frontend/src/components/ui/spinner.tsx` | 41 |
| `apps/frontend/src/components/ui/skeleton.tsx` | 64 |
| `apps/frontend/src/components/ui/alert.tsx` | 96 |
| `apps/frontend/src/components/ui/empty-state.tsx` | 47 |
| `apps/frontend/src/components/ui/field.tsx` | 84 |
| `apps/frontend/src/components/ui/link-button.tsx` | 51 |
| `apps/frontend/tests/primitives-foundation.test.tsx` | 247 |
| `docs/redesign/loop-3-{goal,options,spec,result}.md` | ~470 |

Total: ~1120 LoC. Well under the 2000-line soft cap.

## Binary criteria — all met

- [x] `<Skeleton variant="line"|"text"|"card"|"image"|"circle" />` — 5 shape variants, default line, `aria-hidden`, animate-pulse
- [x] `<EmptyState icon title body cta />` — composed primitive consuming the `surface` utility, lucide icon at decoration opacity
- [x] `<Alert tone="info"|"success"|"warning"|"destructive" icon title>` — cva tones, `role="alert"` only for destructive (others `role="status"`), info tone exercises the loop-1 `--info` token
- [x] `<Field label htmlFor hint error required>` — clones the child input with `aria-invalid` + `aria-describedby`, required mark `*` decorative-only
- [x] `<Spinner size="sm"|"md"|"lg">` — wraps lucide `Loader2`, `role="status"` + `aria-label="Loading"` default
- [x] `<LinkButton href external?>` — consumes `<Button asChild>` + `<Link>`, single anchor in the DOM (no nested button), external links get `target="_blank"` + `rel="noopener noreferrer"`
- [x] `useHydrated()` — hook returning `false` on SSR + first client render, `true` after `useEffect` flushes
- [x] All primitives consume loop-1 tokens (`bg-info`, `border-info/40`, `text-success` etc.) — no raw Tailwind hues
- [x] `primitives-foundation.test.tsx` ships 25 sub-tests covering variants + ARIA + token consumption + composition
- [x] `make test.web` — **35 files / 185 tests passed in 16.60s** (+1 file / +25 tests vs. Loop 2)
- [x] Visual-regression re-run — **8/8 baselines stable in 12.5s, zero pixel diff** vs `c72bcc7`
- [x] No application of new primitives to existing surfaces — Loop 4 owns that

## Verification

```
$ make test.web
…
Test Files  35 passed (35)
     Tests  185 passed (185)

$ docker compose --profile e2e run --rm e2e visual-regression.spec.ts --project=chromium --reporter=list
…
8 passed (12.5s)
```

## 3-bullet retro

- **Loop-level brainstorm beat per-primitive brainstorm.** The first instinct was 3 options × 7 primitives = 21 alternatives; that's noise. Brainstorming the *cross-cutting* design calls (cva vs cn, shape-vs-size variants, Alert vs Field error split) generated the actual leverage. The per-primitive shape then fell out of those decisions in one pass. `loop-3-options.md` is half the length of `loop-1-options.md` but covers more ground.
- **`React.cloneElement` is the right move for Field's ARIA wiring**, but the `Object.assign`-style precedence (child's existing `aria-describedby` + the field's `hint-id`/`error-id` get space-joined; child's explicit `aria-invalid` wins over ours when explicit but our injected `aria-invalid=true` lands when the child hadn't set one). Wrote a short test for both directions so the contract is pinned.
- **No-application loops compound the value of the foundation.** This is the third no-pixel-diff loop in a row (1: tokens, 2: visual-regression baselines, 3: primitives). Loop 4 onwards starts moving pixels — and now there's a CI signal + a primitive vocabulary + a useHydrated hook ready to consume. Each subsequent loop will ship faster because the foundation is sized exactly to what surface loops want.

## Follow-ups discovered (not done this loop)

- **`.skeleton` CSS utility in globals.css** (lines 245-249) is still in scope; future loops can migrate existing CSS-only call sites to `<Skeleton variant=… />`. Schedule with the surface-level loops that touch those sites.
- **`<Field>`'s required-mark style** is decorative-only `*`; a future a11y review might prefer the long-form `<span class="sr-only">required</span>` for screen reader explicitness. Defer until the auth migration in Loop 4 surfaces real consumer feedback.
- **Lazy chunking for the `Alert` tone classes** — currently each `iconToneClasses`/`titleToneClasses` lookup is by string key; a future loop could fold them into the cva variants table for consistency with `button.tsx`. Cosmetic; the current split keeps the cva config readable.

## What to watch in Loop 4

Loop 4 composes `<AuthCard>` from `<Field>` + `useHydrated` + `<Button>` and migrates the 6 auth surfaces (login, register, forgot-password, reset-password, verify-email, verify/[id], confirm-email-change). Watch:
1. The `useHydrated()` hook killing the disabled-submit race that caused Loop 2's auth-gated baselines to capture the login page instead of the post-login target.
2. The 6 byte-identical card chromes collapsing to one `<AuthCard>`. Login + register public baselines will re-bless — call it out in the result doc.
3. Adding `dashboard`, `profile`, `studio`, `admin` × 2 themes to the visual-regression ROUTES array.
4. Codex rescue across loops 1+2+3+4 diffs — first scheduled rescue per AUDIT.md §7.
