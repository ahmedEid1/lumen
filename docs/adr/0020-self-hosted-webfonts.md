# ADR-0020: Self-hosted webfonts (no build-time Google Fonts fetch)

- **Status:** Accepted
- **Date:** 2026-05-28
- **Deciders:** @ahmedEid1

## Context

Typography (`apps/frontend/src/lib/fonts.ts`) loaded Inter + JetBrains
Mono via `next/font/google`. That loader fetches the woff2 from
`fonts.gstatic.com` **at build time**, baking a hard dependency on
Google's CDN being reachable from the build environment.

On 2026-05-28 the multi-arch container build started failing in CI:

```
Failed to fetch `Inter` from Google Fonts.
> Build failed because of webpack errors
```

It failed twice in a row (not a one-off), blocking **all** deploys —
Google was rate-limiting / refusing the GitHub-hosted runner IPs. A
build that depends on a third-party network call also contradicts
Lumen's "MIT-licensed, self-hostable" positioning: anyone self-hosting
behind a restricted network would hit the same wall.

## Decision

Self-host the fonts. The variable woff2 files (Inter + JetBrains Mono,
`latin` subset, sourced from the @fontsource distribution of the same
typefaces) live in `apps/frontend/src/lib/fonts/` and are loaded via
`next/font/local`. The exported `.variable` class names and the
`--font-inter` / `--font-inter-display` / `--font-jetbrains-mono` CSS
variables are unchanged, so `layout.tsx` and `globals.css` need no
edits and rendering is identical (same typefaces, same family wiring).

## Alternatives considered

- **Keep `next/font/google`, re-run on failure** — rejected: the
  failure recurred deterministically; re-run roulette doesn't fix a
  structural external dependency, and it leaves every future deploy at
  the mercy of Google's CDN reachability.
- **`@fontsource` CSS imports** — viable (font files via npm, fetched
  during the build's existing `pnpm install`), but it would replace
  next/font's CSS-variable generation and force a re-wire of
  `globals.css`. `next/font/local` is lower-churn and preserves the
  exact variable wiring.

## Consequences

- **Positive:** the container build no longer makes any network call
  for fonts; builds are reproducible offline; self-hosters are
  unaffected by font-CDN reachability. ~90 KB of woff2 added to the
  repo (latin variable subsets).
- **Neutral:** font upgrades are now a manual file refresh rather than a
  version string. Acceptable — Inter/JetBrains Mono move slowly.
- **Negative:** none observed. Verified the local production Docker
  build compiles + prerenders all 38 routes, and `document.fonts`
  reports interDisplay/interBody/jetbrainsMono `loaded`.

## References

- `apps/frontend/src/lib/fonts.ts`
- next/font/local docs: https://nextjs.org/docs/app/api-reference/components/font
- Incident: CI run 26566441948 (Build container images — Google Fonts fetch failure).
