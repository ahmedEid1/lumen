### Activation (A5)

Built out the demo seed so the locally-running stack produces a recruiter-legible dataset in one `make seed`, then captured the five-PNG portfolio screenshot pack against it. A new `app/seeds/agentic_demo.py` layers on top of the base seed: five extra published courses (with `picsum.photos` cover URLs) round the catalog up to six total, the existing FastAPI course gets back-filled `cover_url` + `learning_outcomes`, and the seed student picks up a completed FastAPI enrollment (with a minted `certificate_id` + best-effort OB3 `badge_credential`) plus a ~50%-progress in-flight enrollment on Data Engineering. One tutor turn is persisted on FastAPI with matching `agent_traces` (planner + retriever + web_searcher + synth), `llm_calls` (plan + synth), and a `retrieval_audits` row — all timestamped inside the 120 s window the I4 learner-trace service uses for the temporal join — so `/dashboard/tutor/{cid}/turn/{mid}` renders with real content. One draft course (`ai-tutor-design-patterns`) carries a full eight-row self-critique trace (researcher → outliner → critic → reviser → critic → lesson_drafter ×2 → final_critic) so `/studio/draft/{id}/replay` populates. Everything is idempotent — a second `make seed` produces zero new rows. A new Playwright spec at `tests/e2e/screenshots.spec.ts` drives the surfaces and lands five PNGs (hero, trace-timeline, studio-replay, observability, evals) at 1440×900 under `docs/screenshots/`, and the README's `HERO_SCREENSHOT_TBD` placeholder now points at `hero.png`.

### Operator runbook (screenshots)

Bring the dev stack up and seed it (one-time per fresh checkout), then re-capture whenever the visual design moves:

```bash
make up
make migrate
make seed                # picks up agentic_demo.apply automatically

# Capture — runs against the seeded stack, lands PNGs under
# apps/frontend/.screenshots-tmp/ (the e2e container can only
# write under its bind-mounted /work). Takes ~30 s on a warm cache.
docker compose --profile e2e run --rm e2e \
  tests/e2e/screenshots.spec.ts --project=chromium

# Move the captures into docs/screenshots/ and commit.
cp apps/frontend/.screenshots-tmp/*.png docs/screenshots/
git add docs/screenshots/*.png
git commit -m "docs(screenshots): refresh portfolio pack"
```

The spec resolves the conversation + draft IDs at runtime via `/api/v1/courses/{slug-or-id}` and `/api/v1/courses/{id}/tutor/conversations`, so a `make reset` that re-seeds with fresh nanoids still works without editing the spec. The `.screenshots-tmp/` directory is gitignored.

### Operator follow-ups (screenshots)

- **Run `oxipng -o4` on the committed PNGs.** Each file lands between 45 KB and 80 KB straight out of Playwright; that's fine for a single README hero today, but if/when the README grows additional inline screenshots, lossless oxipng tends to halve the bytes-on-disk without touching pixels. `docs/screenshots/README.md` already calls this out as a convention.
- **Catch the "Loading Celery health…" flash on `/admin/observability`.** The screenshot spec sidesteps it by jumping straight to the LLM Traces tab, but the dashboard's default tab momentarily shows a "Loading" stub before the worker-health poll lands. Either pre-fetch the poll on tab focus or show a skeleton with rough shape (table header + 3 placeholder rows) so the first-paint isn't a single-line gray string.
- **`/admin/evals` is "no runs yet" until an eval suite is executed.** The current evals.png is *accurate* but reads as empty until the operator runs `make eval` against a real LLM provider. Either (a) ship a tiny noop-provider judging result as part of the seed so the suite cards always show a score, or (b) document that `make eval` against the noop provider produces a meaningful screenshot — and have the screenshot spec optionally trigger it.
- **The seeded tutor turn uses the `noop` provider's deterministic output.** That's correct for a portfolio demo (no API key needed), but a recruiter inspecting the screenshot sees `noop/lumen-noop-1` rather than `groq/llama-3.3-70b`. Consider adding a `LUMEN_DEMO_PROVIDER_LABEL` env var that lets the seed stamp a chosen provider/model string into the seeded `llm_calls` rows without actually calling a remote API — the temporal join doesn't care which strings live in those columns.
- **Picsum cover URLs occasionally serve a different image on cache-miss.** That's fine for a demo, but if the catalog screenshot ever becomes part of the screenshot pack the operator should pin to a specific Picsum image id (the `seed/<slug>` URL pins to a specific image already, but with no SLA — for full determinism, bake an `apps/backend/app/seeds/assets/covers/` directory of committed PNGs and serve via MinIO).
- **The studio replay scrubs to step 3 (Reviser) deterministically, but the lime-active row is at the *top* of frame, not centred.** Visually the screenshot is fine, but if the page chrome grows, the active card could scroll out of frame. Consider adding a `scrollIntoView({ block: 'center' })` call inside `TraceTimeline` whenever `activeIndex` changes — the spec wouldn't need to know.
