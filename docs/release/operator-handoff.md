# Operator handoff — what to do when you're ready to ship the streaming demo

**Audience:** the operator (Ahmed) when the post-redesign autonomous
work is done and the demo is ready to go live for real.

**State at handoff (2026-05-27):** L19.5 → L31 shipped. Code is in
`main`, deployed to prod, all gates green, runtime flag is OFF so the
streaming path is dormant.

To take the demo live, do the four items below in order. Each one
unlocks the next.

---

## 0. Prerequisite — AsyncOpenAI streaming integration

**Status:** see `docs/post-redesign/loop-21a.md` "What did NOT ship".

The orchestrator (`apps/backend/app/services/tutor_orchestrator_stream.py`)
yields a noop chunk sequence today. Flipping the runtime flag without
this integration will turn streaming on but the demo will stream
canned placeholder text, not real LLM output.

If the AsyncOpenAI follow-up has landed (check `git log` for a commit
like `feat: AsyncOpenAI streaming in orchestrate_stream`), skip to
step 1. Otherwise: do that first — see the deferred-follow-up section
in this session's STATUS.md or send Ahmed (the future operator) the
sketch at the end of this doc.

---

## 1. Flip `FEATURE_TUTOR_STREAMING=true` on prod

```bash
# SSH to the AWS prod box (IP per docs/deployment/aws-vps.md):
ssh -i ~/lumen-prod.pem ubuntu@<prod-ip>

# Edit the prod env file:
cd /home/ubuntu/lumen
vim .env
# Add (or set):
FEATURE_TUTOR_STREAMING=true

# Restart the api container:
docker compose -f docker-compose.prod.yml restart api

# Verify the flag is live:
curl https://lumen.ahmedhobeishy.tech/api/v1/runtime-flags
# Expected: {"tutor_streaming": true}
```

**What this changes for users:** new tutor turns from `/learn/*` (and
`/demo`) mount `<StreamingTutorPanel/>` instead of the legacy
non-streaming `<TutorPanel/>`. Existing in-flight conversations on
the legacy panel are unaffected.

**Rollback:** set `FEATURE_TUTOR_STREAMING=false`, restart api. Within
60s of the next runtime-flags poll, all clients revert to legacy.

---

## 2. Run a sealed eval snapshot

The L25 substrate (`apps/backend/app/evals/adversarial.py` +
`baseline.py`) is ready; the L26 sparkline + L27 public surface +
L28 methodology page all read from it.

```bash
# In the api container:
docker compose -f docker-compose.prod.yml exec api \
  python -m app.evals run --suite tutor --limit 30

docker compose -f docker-compose.prod.yml exec api \
  python -m app.evals run --suite authoring --limit 10

docker compose -f docker-compose.prod.yml exec api \
  python -m app.evals run --suite ingest --limit 10

# Adversarial corpus is its own command; the runner lands in a
# follow-up. For now manually invoke the scorer:
docker compose -f docker-compose.prod.yml exec api python -c "
from app.evals.adversarial import load_adversarial_dataset, score_answer
# ... wire to your provider of choice
"
```

**Where the results land:** `apps/backend/evals/reports/<suite>-<ts>.jsonl`
inside the container. To expose them on `/admin/evals` (and from
there into the public `/eval` surface), the L27 follow-up adds a
`GET /api/v1/eval/public` endpoint that reads the latest
admin-promoted report. Until that endpoint exists, the public
`/eval` surface stays in honest-empty state — which is the point.

**Cost:** real-LLM eval traffic. Budget ~$0.50-$2.00 per full suite
run depending on the provider. Cost meter shows it at
`/admin/llm-calls` under `feature="eval.tutor"` etc.

---

## 3. Capture the 90s screencap

Shot list: [`docs/release/screencap-script.md`](./screencap-script.md).
Operator checklist at the bottom of that file.

**Tools:** OBS (or QuickTime) at 1440×900 desktop + iPhone 13 + Safari 17
for the mobile-hero still.

**Output paths:**
- `docs/screencast/walkthrough.mp4` — the captioned silent walkthrough
- `docs/screencast/walkthrough-poster.jpg` — poster frame
- `docs/screenshots/hero-mobile.png` — the iPhone 13 still

The README and per-route OG cards already reference these; refreshing
the files in place is enough — no code changes needed.

**Numbers don't lock in advance** (plan-v7 §F14): captions are read at
recording time off the actual UI. If a measured number is bad
(8s first-token, 1/5 grader), don't ship the screencap — go fix the
thing instead.

---

## 4. Approve the repo rename `E-Learning-Platform` → `lumen`

**Why it's gated:** breaks bookmarks. Anyone with the old GitHub URL
gets a 30-day redirect, then 404. Owner sign-off required.

```bash
# Once you've decided to do it:
gh repo rename lumen --repo ahmedEid1/E-Learning-Platform

# Then update local git remote on every clone:
git remote set-url origin https://github.com/ahmedEid1/lumen.git
```

**What else needs updating:**

- README badges (some hardcode `ahmedEid1/E-Learning-Platform`)
- CI workflow self-references (search `.github/workflows/` for the slug)
- The MCP-registry entry (`io.github.ahmedEid1/E-Learning-Platform` →
  `io.github.ahmedEid1/lumen`)
- Any external link in your portfolio site / LinkedIn / Twitter bio

Estimated work: ~20 minutes including the badge sweeps.

---

---

## 5. (Optional) Wire backend error telemetry

The scrubber from L21-Sec is already installed in `main.py` — it
zeros tutor-namespace locals/breadcrumbs/request-bodies before any
event ships. To activate it, you need a DSN.

**Glitchtip free tier** (the v2-locked choice per cost preferences):

```bash
# Sign up: https://app.glitchtip.com (free for 1 user, 1000 events/mo)
# Create a project: "lumen-prod"; copy the DSN.

# On the prod box:
ssh -i ~/lumen-prod.pem ubuntu@<prod-ip>
cd /home/ubuntu/lumen
vim .env
# Add:
SENTRY_DSN=https://<key>@app.glitchtip.com/<project-id>

docker compose -f docker-compose.prod.yml restart api worker beat
```

**What gets scrubbed** (already locked at L21-Sec, see
`apps/backend/app/core/sentry_scrubber.py`):
- Stack-frame locals named `prompt`, `system_prompt`, `user_message`,
  `messages`, `response_text`, `tool_output`, `tool_result`,
  `completion`, `answer`, `agent_response`, `retrieved_chunks`,
  `lesson_body` — replaced with `<scrubbed by lumen.sentry_scrubber>`
- Request bodies on `/tutor` and `/api/v1/tutor/*` paths
- Breadcrumbs tagged `category="tutor"`

**What still ships:** exception class + filename + line number + the
non-tutor parts of the stack trace. Enough to debug, not enough to
leak.

**Verify scrubbing works end-to-end:**

```bash
docker compose -f docker-compose.prod.yml exec api python -c "
from app.core.sentry_scrubber import before_send
event = {'exception': {'values': [{'type': 'ValueError', 'value': 'boom', 'stacktrace': {'frames': [{'vars': {'prompt': 'SECRET', 'innocuous': 'kept'}}]}}]}}
cleaned = before_send(event)
print(cleaned['exception']['values'][0]['stacktrace']['frames'][0]['vars'])
# Expected: {'prompt': '<scrubbed by lumen.sentry_scrubber>', 'innocuous': 'kept'}
"
```

Frontend client-side error capture (via `@sentry/nextjs`) is not
wired today — that's a separate ~150-LoC integration if you want
client-side coverage too.

---

## After all five — distribution

The screencap + the public `/eval` numbers + the `/case-study`
narrative are the three artifacts a recruiter needs. Distribution
drafts land in this order:

1. **Twitter / X thread** — 5 tweets. Hook = the screencap; close =
   "code at lumen.ahmedhobeishy.tech, full repo at github.com/…"
2. **LinkedIn post** — 1 long post, screencap embedded. Tone:
   "what I built in 8 weeks on a real LLM budget."
3. **Show HN** — single post, "Show HN: Lumen — an agentic AI tutor
   that grades itself." Link to `/eval` + the case study.
4. **Cold-outreach template** — one paragraph + a link to `/eval`.

Drafts will live at `docs/release/distribution-drafts.md` once the
screencap is captured. The drafts themselves are L40 in the v7 plan;
the operator writes them after seeing the captured artifact.

---

## Appendix — AsyncOpenAI streaming sketch

If the AsyncOpenAI integration hasn't landed yet, here's the sketch
for the implementer:

```python
# apps/backend/app/services/tutor_orchestrator_stream.py
# Replace the noop synth-chunk loop with:

from app.services.llm import get_provider
import time

async def orchestrate_stream(...):
    # ... planner / tool calls as today
    yield {"event": "planner_start", "data": {...}}
    # ... yield tool_call_start / tool_call_result per sub-agent

    provider = get_provider()  # picks anthropic / openai / noop per env

    # Build the synth prompt from retrieved chunks + user question
    messages = build_synth_prompt(user_message, retrieved_chunks)

    start_ms = time.monotonic()
    first_token_ms = None
    total_text = ""

    async for chunk in provider.stream_chat(
        messages,
        stream_options={"include_usage": True},
    ):
        if first_token_ms is None:
            first_token_ms = (time.monotonic() - start_ms) * 1000
        delta = chunk.text  # provider-specific
        total_text += delta
        yield {"event": "synth_chunk", "data": {"delta": delta}}

    yield {
        "event": "turn_complete",
        "data": {
            "first_token_ms": first_token_ms,
            "total_ms": (time.monotonic() - start_ms) * 1000,
            "cost_usd": chunk.usage_cost,  # from include_usage
        },
    }
```

The `provider.stream_chat()` method is the missing piece — needs an
`AsyncOpenAI` (or Anthropic equivalent) wrapper alongside the
existing sync `chat()` method in `app/services/llm.py`. ~150 LoC
including tests.

Once landed, step 1 above (flag flip) makes the demo actually work
on real LLM traffic.
