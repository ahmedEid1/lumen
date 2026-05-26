# Loop 3 — Options

Three loop-level design calls. Each primitive's API shape is a derivative of these decisions; per-primitive 3-options-with-tradeoffs would balloon to 21 alternatives without changing the loop's shape, so the brainstorm runs at the level that actually matters.

## Decision 1 — variant authoring: cva vs plain cn

`button.tsx` + `badge.tsx` already use `cva` (`class-variance-authority`); `card.tsx` + `input.tsx` + `textarea.tsx` use plain `cn()` because they have no variants.

- **Option A: All new primitives use cva.** Consistency. Even single-shape primitives get a stub variant config.
- **Option B: cva only for primitives with 2+ variants, cn for the rest.** Skeleton/Alert/EmptyState get cva (have variants); Field/Spinner/LinkButton/useHydrated don't. Matches the existing repo split.
- **Option C: No cva — express variants via component composition (e.g. `<Skeleton.Line />`, `<Skeleton.Card />`).** Most explicit but spawns ~20 sub-components.

**Decision: B.** Mirrors the existing split (`button.tsx` cva, `card.tsx` cn). No invented patterns. `Spinner` and `LinkButton` reach for cn because they're effectively one-shape wrappers; `Skeleton`/`Alert`/`EmptyState` reach for cva because they have a real variant surface that callsites need to switch on.

## Decision 2 — Skeleton variant shape

The audit found 5 different "loading" conventions across surfaces. What replaces them needs to match the *shapes* surfaces actually want to skeleton.

- **Option A: Size variants (sm/md/lg).** Skeleton just sets a height; consumers wrap in their own widths. Most permissive.
- **Option B: Shape variants (line/text/card/image/circle).** Skeleton encodes the *intent* — `<Skeleton variant="image" />` returns an aspect-ratio'd block; `<Skeleton variant="text" />` returns 3 short bars; `<Skeleton variant="circle" />` returns a round element for avatars.
- **Option C: Shape + size matrix.** Both axes; `<Skeleton variant="text" size="sm" />`. Most flexibility, most API surface.

**Decision: B.** Surfaces want to spell "this slot is loading what would be an image", not "this slot is 200px tall". Shape variants compose: a CourseCard loading skeleton is `<Skeleton variant="image">` + `<Skeleton variant="text">` + `<Skeleton variant="text">`. Width is always `w-full` (consumer wraps in the layout width). Size doesn't add value at this stage.

## Decision 3 — Alert vs. Inline error pattern

`<Alert>` is a banner; `<Field error="…">` is inline form error text. They overlap.

- **Option A: One `<Alert>` primitive for both.** Form errors render an Alert inline. Visual weight risks dominating the input.
- **Option B: Two primitives — `<Alert>` for page-level banners, inline error text inside `<Field>`.** Clear domain split.
- **Option C: `<Alert>` only, with a `compact` variant for inline use.** Single source of truth, two visual densities.

**Decision: B.** Alert is for "this whole page has a state notice — the email is unverified, the course is in draft". Field error is for "this single input rejected your value — must be ≥ 12 chars". Different audiences, different visual weight. Conflating them produces oversized form errors and undersized page banners.

## Decision matrix summary

| Concern | Decision |
|---|---|
| Variant authoring | cva when 2+ variants; cn otherwise (matches repo) |
| Skeleton variants | Shape-based (line / text / card / image / circle) |
| Alert vs Field error | Two primitives — Alert for banners, Field.error for inline |
| Token consumption | `--info` (Alert), `--ease-out-quart` (Skeleton pulse), `--space-*` (no migration this loop) |
| Tests | One `primitives-foundation.test.tsx` parametrised over all 7 |
| Application | Out of scope — Loop 4 |

Implementation order: independent primitives in any order, then `useHydrated()` (zero deps), then the single test file.
