# Screencap shot list — 90s walkthrough

**Status:** Operator-run. Gated on `FEATURE_TUTOR_STREAMING=true`
in prod + a real device for the mobile capture.

**Goal:** A 90-second silent captioned walkthrough that survives
muted autoplay on social feeds. Cold open in the first 10 seconds
(no narration, no "hi I'm Ahmed"); the streaming UI carries the
sale.

## Shot list

| Window | Action | Caption | Visual note |
|---|---|---|---|
| 0:00–0:05 | Landing page hero — agent-replay panel mid-cycle (retriever active, code_runner queued) | "Watch it think." | Cold open. No talking head. The animation IS the hook. |
| 0:05–0:12 | Click "Try the demo →" → /demo redirects to /learn/typescript-variance with tutor open + canonical question prefilled | "One-click demo. Canonical question prefilled." | The prefilled composer is the proof that the flow works without onboarding. |
| 0:12–0:25 | Hit Send. Watch the real SSE stream: `planner_start` → `retriever` (with latency badge) → `code_runner` → tokens streaming in | "Real SSE. Real tool calls. Latency you can read." | The cursor cursor-blink during synth is the visual heartbeat. |
| 0:25–0:35 | Cursor scrolls down to the citations under the assistant bubble; click one → opens the lesson in a new tab | "Every claim cites a lesson. Open it. Audit it." | This is the grounding-receipt visual. |
| 0:35–0:55 | Cursor navigates to /eval → public surface visible. Pan over the sealed-run-pending banner + worked example + adversarial card | "Public eval. Refusal rate. Refused vs leaked. No fake numbers." | The honest-empty state IS the credibility signal. |
| 0:55–1:10 | Click "Methodology" → scroll through the five sections | "How the numbers get made. Limits and all." | The "what I'd do at scale" section is the close. |
| 1:10–1:25 | Cursor → /case-study. Show the architecture sketch + scroll to "What I did not use" | "Six boxes, two protocols. Custom orchestrator, no LangChain." | The architecture sketch is the technical-credibility flex. |
| 1:25–1:30 | Cut to a static frame: contact card with email + (Calendly when live) + GitHub repo URL | "Contact." | Plain text close — recruiter audience, not consumer. |

## Numbers DO NOT lock in advance

Per plan-v7 §F14: do not hardcode "1.8s first-token", "$0.014", or
specific eval scores in the captions or voiceover. Read those at
recording time off the actual UI. If the measured numbers are bad
(8s first-token, 1/5 grader), the screencap doesn't ship — and that
is the right outcome.

## Capture environment

- **Desktop**: 1440×900 viewport (the macbook-air baseline that the
  Workbench design system was authored against). Chrome stable.
- **Mobile** (separate capture, for the README hero + og:image):
  iPhone 13 + Safari 17, 390×844, captured from the device's screen
  recorder. Get the tutor mid-stream with the tool rows above the
  fold.

## Captions

Burned-in (white text, lime accent on key phrases, mono uppercase),
matching the Workbench visual identity. No fancy lower-third graphics
— the recruiter audience reads the screen.

## Music

None. The visual is the message. A muted feed plays no music; an
unmuted feed gets clean voiceover (recorded separately as a Loom
follow-up, per the README's `LOOM_URL_TBD` placeholder).

## Output

- `docs/screencast/walkthrough.mp4` — the silent captioned version.
- `docs/screencast/walkthrough-poster.jpg` — the poster frame
  (already referenced in the README badges; refresh on capture day).
- `docs/screenshots/hero-mobile.png` — the iPhone-13 still that
  L24's mobile-pass made room for.

## Operator checklist

1. [ ] `FEATURE_TUTOR_STREAMING=true` is set in prod env.
2. [ ] A sealed eval run is promoted so `/eval` shows real numbers.
3. [ ] `make demo-seed` has been re-run so the TS variance course +
   canonical question are in the prod DB.
4. [ ] Caddy SSE-pass-through config is verified (no proxy-level
   buffering on `text/event-stream`).
5. [ ] The mobile capture device is in dark mode (default theme;
   the screencap shows off the dark Workbench aesthetic).
6. [ ] No personally-identifying email / DM appears in any frame.
