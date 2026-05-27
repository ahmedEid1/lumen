# Loop 31 — Per-route OG cards + README "what to look at" + screencap shot list

**Date:** 2026-05-27
**Scope:** Plan-v7 §L31. The screencap deliverable itself is
operator-gated (needs `FEATURE_TUTOR_STREAMING=true` in prod + a real
device); L31 ships the surrounding artifacts that are independently
shippable.

## What shipped

### Per-route OG cards

`apps/frontend/src/app/eval/opengraph-image.tsx` (new) +
`apps/frontend/src/app/case-study/opengraph-image.tsx` (new). Both
follow the Loop-19 root-level pattern (1200×630, dark Workbench
chrome, lime accent, mono cartouche + display headline + mono URL
footer). Each card states which surface it's for in the cartouche.

When `/eval` or `/case-study` is shared on Slack / Twitter / LinkedIn,
the preview now shows the page-specific card, not the home page's
generic one. Next 15's file-system convention auto-wires the card to
the route's metadata — no code changes outside the file.

### README "What to look at first" section

Inserted just below the bullet-list of features (above the
architecture diagram). 7 highest-signal file links for a reviewer
who wants to skim:

- Tutor orchestrator + Celery task (event sequence + phase fence)
- SSE wire endpoints + Redis Streams helpers
- Lua cost scripts (microcents integer math)
- Adversarial scorer + 15-probe corpus
- Frontend SSE parser + `useSyncExternalStore` reducer + iOS UA sniff
- ADRs 0017-0019
- Public surfaces (`/eval`, `/eval/methodology`, `/case-study`)

Recruiter-friendly file navigation; a 30-second skim catches the
architectural signal without having to clone the repo.

### Screencap shot list

`docs/release/screencap-script.md` (new). 90-second silent
captioned walkthrough script:

| Window | Action | Caption |
|---|---|---|
| 0:00–0:05 | Landing hero replay mid-cycle | "Watch it think." |
| 0:05–0:12 | Click `/demo` → tutor opens prefilled | "One-click demo. Canonical question prefilled." |
| 0:12–0:25 | Real SSE stream — tools + tokens | "Real SSE. Real tool calls. Latency you can read." |
| 0:25–0:35 | Citation pill → opens lesson | "Every claim cites a lesson." |
| 0:35–0:55 | `/eval` public surface | "Public eval. Refused vs leaked. No fake numbers." |
| 0:55–1:10 | `/eval/methodology` scroll-through | "How the numbers get made. Limits and all." |
| 1:10–1:25 | `/case-study` architecture sketch | "Six boxes, two protocols. Custom orchestrator." |
| 1:25–1:30 | Contact card static frame | "Contact." |

Plus: operator checklist (flag flipped, sealed eval run, demo seed
applied, Caddy SSE pass-through verified, mobile device in dark
mode, no PII in frame).

## What did NOT ship (operator-gated)

The actual screencap MP4 + the iPhone-13 hero PNG. Both require:

1. `FEATURE_TUTOR_STREAMING=true` flipped in prod.
2. A real iPhone 13 + Safari 17 for the mobile capture.
3. A sealed eval run so `/eval` shows real numbers.

The shot list documents what to capture; the actual capture is the
operator's job. Numbers in the captions are deliberately read at
recording time (plan-v7 §F14 — don't lock unmeasured numbers).

## Verification

```
$ pnpm exec eslint src/app/eval/opengraph-image.tsx src/app/case-study/opengraph-image.tsx   # clean
$ pnpm exec tsc --noEmit --incremental false                                                  # clean
$ pnpm exec vitest run                                                                         # 61 / 329 green (unchanged from L30)
```

Backend untouched.

## Files

**Frontend new:**
- `apps/frontend/src/app/eval/opengraph-image.tsx`
- `apps/frontend/src/app/case-study/opengraph-image.tsx`

**Modified:**
- `README.md` ("What to look at first" section above the architecture diagram)
- `docs/post-redesign/STATUS.md` (L31 row)
- `CHANGELOG.md` (L31 entry)

**Docs new:**
- `docs/release/screencap-script.md` (the shot list)
- `docs/post-redesign/loop-31.md` (this file)

## Next loops

L32-L37 are explicitly cuttable in the v7 plan. L38-L40 (Codex audit
+ VR baselines + repo rename + distribution drafts) are mostly
operator-gated:

- **L38 Codex audit** — runs once Anthropic API capacity recovers.
- **L39 VR baselines** — needs the streaming flag flipped (the new
  surfaces produce different visual snapshots when streaming is
  live).
- **L40 repo rename** — requires owner OK per the handoff
  ("Three items need owner confirmation: repo rename to lumen
  breaks bookmarks…").
- **L40 distribution drafts** — Twitter thread / LinkedIn / Show HN
  copy depends on the screencap landing first.

Autonomous-mode work effectively ends here. The remaining loops
need the operator to (a) flip the prod env flag, (b) capture the
screencap on a real device, (c) approve the rename, (d) sign off
the distribution materials.

## Codex rescue note

Still deferred — Anthropic API hit 529 Overloaded on the post-L28
attempts. Will retry once capacity recovers. The rescue should
cover L26 → L31 in one sweep at that point.
