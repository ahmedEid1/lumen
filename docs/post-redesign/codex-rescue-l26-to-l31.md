# Codex rescue — L26 → L31 portfolio arc

**Date:** 2026-05-27
**Diff scope:** `4611235..HEAD` (L25 + L26 + L27 + L28 + L29 + L30 + L31)
**Attempts:** 3 (first two hit `API Error: 529 Overloaded` — Anthropic
capacity, not a Codex bug; retry on the third succeeded once capacity
recovered).
**CLI quirk:** `codex review --base <sha>` rejects positional prompts.
The focus-area brief was passed via `--title` only; Codex consequently
returned a narrower review than the brief asked for. Documented in
[[codex-cli-flags]] memory.

## Findings (verbatim from Codex)

### P2: Nested interactive content on every new CTA

> `apps/frontend/src/components/home/agent-replay-hero.tsx:64-69`
> (+ same pattern in eval-public-view, eval-methodology-view,
> case-study-view, cost-cap-closing-cta)
>
> `Link` produces an anchor while `Button` still renders a native
> `<button>`, so these CTAs become invalid nested interactive
> content (`<a><button>`). This can confuse keyboard/screen-reader
> navigation and trigger React/HTML validation warnings; use
> existing `LinkButton` or `Button asChild` pattern instead.

**Fix:** swept all 5 surfaces to `Button asChild`. The Button
component already supports `asChild` via `@radix-ui/react-slot`; the
fix is one-line per CTA:

```tsx
// Before (invalid):
<Link href="/demo">
  <Button>Try the demo</Button>
</Link>

// After (single interactive element):
<Button asChild>
  <Link href="/demo">Try the demo</Link>
</Button>
```

Affected files (10+ CTA call sites total):

- `apps/frontend/src/components/home/agent-replay-hero.tsx` — 2 CTAs
- `apps/frontend/src/app/eval/eval-public-view.tsx` — 2 footer CTAs
- `apps/frontend/src/app/eval/methodology/eval-methodology-view.tsx` — 2 footer CTAs
- `apps/frontend/src/app/case-study/case-study-view.tsx` — 3 footer CTAs
- `apps/frontend/src/components/tutor/cost-cap-closing-cta.tsx` — 2 CTAs

### P3: `/case-study` missing from sitemap

> `apps/frontend/src/app/sitemap.ts:24-25`
>
> The new public `/case-study` page is not advertised in the sitemap,
> while the `/eval` routes added in the same change are. When
> crawlers or share/debug tooling rely on `/sitemap.xml`, the case
> study page will be discoverable only through in-page links rather
> than the canonical route list.

**Fix:** added the `/case-study` entry to `staticRoutes` in
`sitemap.ts`. The L30 commit had attempted this edit but it silently
failed due to a Read-freshness race in the edit tool — Codex caught
the result.

## What Codex did NOT review (due to `--base` CLI quirk)

The original focus-area brief included 8 numbered concerns;
`codex review --base` accepts a `--title` but rejects a positional
prompt, so only the title's summary reached Codex. The areas Codex
did not specifically dig into:

1. Honest-empty contract on `/eval` (no fake numbers)
2. Methodology numeric claims (judge-vs-human agreement band, small-N
   noise, 13-of-15 probe count)
3. Case-study numeric framing (the 18%→3% prompt-iteration story)
4. Adversarial disclosure posture
5. i18n parity across 100+ new keys
6. Sparkline coordinate-math edge cases
7. Routing metadata + per-route OG wiring
8. README "What to look at first" file-path resolution

These didn't surface findings either — could be clean OR could be
unreviewed. The `--commit`-per-loop pattern would deliver deeper
focus-area coverage but at the cost of N invocations.

## Test results

```
$ pnpm exec eslint <changed paths>                # clean
$ pnpm exec tsc --noEmit --incremental false      # clean
$ pnpm exec vitest run                             # 61 / 329 green
```

The existing render-boundary tests on `EvalPublicView`,
`CaseStudyView`, `CostCapClosingCta`, and `AgentReplayHero` all
pass — the `asChild` pattern preserves the DOM shape from
the rendered-button's perspective (they still look like
`role="link"` elements with the Button's styles).

## Rescue scope

2 fixes (1 P2 sweep across 5 files + 1 P3 sitemap entry) + 1 docs
file in one commit. The CTA refactor is the dominant change;
sitemap is a one-line addition.

## Files

**Modified:**
- `apps/frontend/src/components/home/agent-replay-hero.tsx`
- `apps/frontend/src/app/eval/eval-public-view.tsx`
- `apps/frontend/src/app/eval/methodology/eval-methodology-view.tsx`
- `apps/frontend/src/app/case-study/case-study-view.tsx`
- `apps/frontend/src/components/tutor/cost-cap-closing-cta.tsx`
- `apps/frontend/src/app/sitemap.ts`

**Docs:**
- `docs/post-redesign/STATUS.md` (rescue row added)
- `docs/post-redesign/codex-rescue-l26-to-l31.md` (this file)
- `CHANGELOG.md` (rescue entry)
