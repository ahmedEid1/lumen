# Loop 1 — Result

## What shipped

`globals.css` grew by 47 lines of token declarations + 27 lines of `@theme inline` aliases. Five components in `src/components/ui/` (button, input, textarea, progress) lost their duration-literal shadows of the existing motion tokens. One new vitest spec (`tokens-foundation.test.ts`, 188 LoC) pins the entire token surface plus the four duration sweeps.

| File | Lines changed |
|---|---|
| `apps/frontend/src/styles/globals.css` | +74 / -0 |
| `apps/frontend/src/components/ui/button.tsx` | +1 / -1 |
| `apps/frontend/src/components/ui/input.tsx` | +1 / -1 |
| `apps/frontend/src/components/ui/textarea.tsx` | +1 / -1 |
| `apps/frontend/src/components/ui/progress.tsx` | +1 / -1 |
| `apps/frontend/tests/tokens-foundation.test.ts` | +188 / -0 |
| `docs/redesign/loop-1-{goal,options,spec,result}.md` | +287 / -0 |

Total net new: ~553 LoC. Well under the 2000-line soft cap.

## Binary criteria — all met

- [x] `--info` + `--info-foreground` in both `:root` and `.light`, AA-passing in both themes (verified by hand: dark 8.06–8.42:1, light 6.20–6.55:1)
- [x] `--space-{xs,sm,md,lg,xl,2xl,3xl}` declared
- [x] `--z-{base,sticky,overlay,modal,popover,toast,tooltip}` declared
- [x] `--opacity-{disabled,hover,overlay,decoration}` declared
- [x] `--ease-spring-soft`, `--ease-spring-firm`, `--motion-rise-distance`, `--motion-press-scale` declared
- [x] `@theme inline` Tailwind utility aliases for info / spacing / z-index / opacity (motion variants consumed via `var()` in arbitrary values per the file's existing convention)
- [x] `button.tsx`, `input.tsx`, `textarea.tsx` use `duration-base` (Tailwind class), `progress.tsx` uses `var(--duration-slow)` / `var(--ease-out-quart)` (inline style)
- [x] New `tokens-foundation.test.ts` passes; full `make test.web` green: **34 files / 160 tests passed in 15.37s**
- [x] Zero visible diff — http://localhost:3000/ returns 200 in 1.38s, `duration-base` class is present in the rendered HTML confirming Tailwind generated the utility from the @theme alias

## Verification

```
$ make test.web
…
Test Files  34 passed (34)
     Tests  160 passed (160)

$ docker compose exec -T web pnpm typecheck
tsc --noEmit  (clean exit)

$ curl -fsS http://localhost:3000/ -w "HTTP=%{http_code}\n" -o /tmp/lumen-home.html
HTTP=200

$ grep -c "duration-base" /tmp/lumen-home.html
1
```

Visual regression baselines not yet captured — that's Loop 2's job. Visual smoke for this loop: the running dev server's rendered home page is byte-equivalent to its pre-commit state by inspection (no class names changed semantically, only the underlying var indirection).

## 3-bullet retro

- **Spec-first paid off.** Writing `loop-1-spec.md` flushed out the `--ease-spring-soft: var(--ease-spring-soft)` self-reference *before* I'd typed it into globals.css — I caught the same shape in the implementation step and fixed by aligning to the existing convention (motion vars are `@theme inline` literals, not aliases from `:root`). Without the spec I'd have committed the loop, run the tests, gone red on CSS resolution, and burned another iteration unwinding the namespace.
- **The token-test re-write was the cost of the loop.** First version of `tokens-foundation.test.ts` reused the `/repo` mount pattern from `ci-workflow-shape.test.ts` — wrong abstraction. `/repo` only exposes the Makefile + workflows, not the frontend source. Switched to `__dirname`-relative reads (vitest already runs at `/app` via the web container's main mount), which is also the right pattern for *any* test that needs to inspect `apps/frontend/src/**` as text. Future redesign loops can copy this shape directly.
- **No-visible-diff loops are unusually satisfying to commit.** Zero pixel risk, full primitive-level value: the next 19 loops can spell their intent (`p-md`, `z-modal`, `bg-info`, `opacity-disabled`) without inventing the vocabulary first.

## Follow-ups discovered (not done this loop)

- **`--z-*` migration sweep.** `site-header.tsx:103` uses `z-40` (should be `z-sticky`); `layout.tsx:43` uses `z-50` (should be `z-toast` if it stays on the skip link, or `z-overlay`); `notifications-bell.tsx:93-94` uses `30`/`40` (should be `z-popover`). Not done here because the migration is a sweep, not a token addition — belongs in a later loop, probably bundled with the Popover primitive in Loop 4.
- **`--opacity-decoration` consumers.** Existing chrome that uses `/40` literals (course-card `text-muted-foreground/40`, etc.) could move to `opacity-decoration` — same migration concern. Schedule with the EmptyState / Skeleton loop where it's already in scope.
- **`duration-base` adoption beyond UI primitives.** Many components still hard-code `duration-200` or `duration-300` Tailwind defaults. Surface-level loops will sweep these per-component as they touch them; no separate sweep loop needed.

## What to watch in Loop 2

Loop 2's first task is Playwright `toHaveScreenshot` baselines. Because Loop 1 was no-visible-diff, the baselines captured in Loop 2 *should* match HEAD-without-loop-1 byte-for-byte. If they don't, something in the duration-literal sweep changed a render. The Loop 1 → Loop 2 commit boundary is the cleanest place to catch that.
