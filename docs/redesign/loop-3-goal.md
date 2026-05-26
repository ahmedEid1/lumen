# Loop 3 — Goal

**Land the seven state + form + interaction primitives that the next 16 redesign loops will consume, plus the `useHydrated()` hook that kills the four-copy hydration-gate pattern.**

AUDIT.md §2 names 17 missing primitives; this loop ships the ones that have ★★★ usage gravity and no upstream dependencies — `Skeleton`, `EmptyState`, `Alert`, `Field`, `Spinner`, `LinkButton` — plus the cross-cutting `useHydrated()` hook. The `<AuthCard>` composition that consumes Field + useHydrated, and the application sweep across the 6 auth surfaces + 10 loading sites, ships in Loop 4 alongside the auth-gated visual-regression baselines that Loop 2 deferred.

- **Surface:** seven new files under `apps/frontend/src/components/ui/` + one hook file under `apps/frontend/src/lib/`. Plus a single vitest spec covering all primitives + the hook (matches the existing `tests/badge.test.tsx` pattern but parametrised).
- **Persona:** every future surface loop. Each one of these will be consumed dozens of times before the redesign is done.
- **Binary success criteria:**
  1. `src/components/ui/skeleton.tsx` exports `<Skeleton variant="line"|"text"|"card"|"image"|"circle" />` with shape-correct defaults.
  2. `src/components/ui/empty-state.tsx` exports `<EmptyState icon title body cta />`.
  3. `src/components/ui/alert.tsx` exports `<Alert tone="info"|"success"|"warning"|"destructive">` with icon + title + body slots; the `info` tone exercises the loop-1 `--info` token.
  4. `src/components/ui/field.tsx` exports `<Field label hint error>` wrapping a child input.
  5. `src/components/ui/spinner.tsx` exports `<Spinner size="sm"|"md"|"lg" aria-label?>` — wraps lucide `Loader2` with accessible-name discipline.
  6. `src/components/ui/link-button.tsx` exports `<LinkButton href asChild?>` consuming `Button asChild` — kills the 4 nested-interactive `<Link>` > `<Button>` pairs found by the audit (reset-password:92, verify-email:113, verify/[id]:105, course-detail-view:370).
  7. `src/lib/use-hydrated.ts` exports `useHydrated()` — replaces the copy-pasted `mounted` paragraph in login:57, register:34, forgot:30, reset:44.
  8. Each primitive consumes loop-1 tokens (`--info` for Alert info, `--space-*` for padding, `--ease-out-quart` for transitions) where applicable; no raw Tailwind hues, no hard-coded `duration-[Nms]` literals.
  9. New vitest `tests/primitives-foundation.test.tsx` covers: variant rendering, accessibility (each primitive's required ARIA), token consumption. Existing 161 tests still green.
  10. **Zero visible diff in the running app** — the application sweep is Loop 4. This loop only adds files; existing surfaces are untouched.
  11. Visual-regression spec (Loop 2's 8 public baselines) re-runs green with zero pixel diff vs. `c72bcc7`.

Out of scope for this loop:
- `<AuthCard>` composition + auth-surface migration (Loop 4).
- Replacement of the existing `.skeleton` utility CSS class — keep both for one transitional loop; sweep the CSS-only call sites to the `<Skeleton>` component in Loop 4.
- Switch / Checkbox / RadioGroup — those want `Field` semantics for label + error wiring; ship together once Field is consumed by the auth migration and the patterns are battle-tested. Schedule: Loop 5 (form-input primitives).
- Dialog / Sheet / Popover / DropdownMenu / Tooltip — overlay primitives need Radix install + focus-trap work; that's its own loop (5 or 6).
