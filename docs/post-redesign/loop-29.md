# Loop 29 — Landing-page rewrite: animated agent-replay hero

**Date:** 2026-05-27
**Scope:** Replace the static text hero with an animated SSE-replay
panel. Plan-v7 §L29.

## What shipped

### `<AgentReplayHero />`

`apps/frontend/src/components/home/agent-replay-hero.tsx` (new).
Two-column hero (stacks on mobile):

- **Left column** — cartouche + display headline + a new replay-
  specific subline + two CTAs (Try the demo / Read the evals).
- **Right column** — a `surface`-bordered "live replay" panel that
  walks through the canonical sequence in CSS keyframes:
  1. User bubble appears with the TS-variance question.
  2. `retriever` tool row activates, latency badge appears.
  3. `code_runner` tool row activates, latency badge appears.
  4. Synth bubble fades in with the response head + cursor.
  5. Caption fades in: "Live replay · canonical demo question".

The whole sequence runs at 14s, infinite loop, generous so a
reading recruiter has time to follow each stage. The right column's
visual posture matches `StreamingTutorPanel` exactly — same tool-row
shape, same cursor element, same `aria-live`-ready text — so a
recruiter who clicks /demo and lands on the live thing immediately
recognises it.

**Reduced motion:** all animations swap to `none` + visible/static
under `@media (prefers-reduced-motion: reduce)`. The cursor element
hides. This is plan-v7 §L29's explicit requirement.

**Accessibility:** the panel carries `role="img"` + `aria-label`
that describes the sequence + names the tools + flags the
reduced-motion behaviour. A screen-reader user gets the same
information as a sighted user, just static.

### Home wiring

`apps/frontend/src/app/home-view.tsx` replaces the legacy `<Hero />`
with `<AgentReplayHero />`. The pillars section + featured-courses
grid + closing CTA section all stay; the legacy `Hero` function
body was retired (the i18n keys it consumed are reused inside the
replay hero's left column).

### i18n

5 new keys per locale (en + ar):

| Key | Purpose |
|---|---|
| `home.replayHeroBody` | Subline beside the headline |
| `home.replayHeroTryDemo` | Primary CTA label |
| `home.replayHeroPublicEval` | Secondary CTA label |
| `home.replayHeroAriaLabel` | Replay-panel role=img label |
| `home.replayHeroCaption` | Live-replay caption |

## Tests

| Surface | Tests |
|---|---|
| Canonical question rendered | 1 |
| Both tool rows visible | 1 |
| CTAs route to /demo + /eval | 1 |
| Reduced-motion override in inline `<style>` | 1 |
| `role=img` + aria-label | 1 |
| **L29 total** | **+5 new** |
| Frontend suite | 60 files / 326 tests green |

## What did NOT ship (deferred)

- **Real SSE replay** against the seeded demo user. The
  `feature_tutor_streaming` flag is still OFF in prod; once it
  flips + the streaming POST handler actually serves the canonical
  question against the seed, the CSS-keyframe animation can be
  replaced with a real `useTutorStream` subscription against a
  seeded turn. Today's L29 is the next-most-honest thing: a visual
  representation that matches the live UI exactly.
- **Per-route OG cards** — L31 scope alongside the screencap.

## Verification

```
$ pnpm exec eslint src/components/home src/app/home-view.tsx src/lib/i18n   # clean
$ pnpm exec tsc --noEmit --incremental false                                 # clean
$ pnpm exec vitest run                                                        # 60 / 326 green
```

## Files

**Frontend new:**
- `apps/frontend/src/components/home/agent-replay-hero.tsx`
- `apps/frontend/tests/agent-replay-hero.test.tsx`

**Frontend modified:**
- `apps/frontend/src/app/home-view.tsx` (legacy Hero retired; replay
  hero mounted in its place)
- `apps/frontend/src/lib/i18n/messages/en.ts` (+5 keys)
- `apps/frontend/src/lib/i18n/messages/ar.ts` (+5 keys)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L29 row)
- `docs/post-redesign/loop-29.md` (this file)
- `CHANGELOG.md` (modified)

## Codex rescue note

The post-L28 Codex rescue attempts both hit `API Error: 529
Overloaded` (Anthropic API capacity, not a Codex bug). The diff
through L28 will be reviewed as part of the post-L29 / post-L30
rescue once API capacity recovers. Memory should reflect: when
spawning a Codex rescue and the underlying Claude API is overloaded,
defer and retry — don't burn iterations on a non-determinist
failure.

## Next loop

L30 — `/case-study` MDX. Founding story (expanded from the README
opener) + C4 component diagram + sequence diagram of a turn + three
deep dives (prompt iteration, failure mode, cost/latency) + "what I
did not use and why" + lessons section. Closing CTA to email + the
demo.
