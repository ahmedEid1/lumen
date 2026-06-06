# Screenshots & GIFs

This directory holds every image and GIF the top-level [`README.md`](../../README.md) embeds. Treat the contents as code: when the UI changes meaningfully, recapture — stale screenshots are the fastest way to make a portfolio README read as abandoned.

## Inventory (captured 2026-06-06, post-redesign, 2.0.0-two-role on prod)

| File | Surface | Source |
|---|---|---|
| `gifs/define-build.gif` | Full define→build loop: goal → AI intake → brief → orchestrator build → finished course | **Prod**, real Groq build (intake 6×, build 16× time-compression) |
| `gifs/tutor.gif` | RAG tutor turn: question → retriever fires → streamed answer | **Prod**, 2× |
| `gifs/cmdk.gif` | ⌘K command palette over the dashboard | **Prod**, ~1× |
| `gifs/hero.gif` | Home-page agent-replay hero (one full 14 s CSS cycle) | **Prod**, 1× — kept for reuse even though the README currently embeds the static `home.png` |
| `home.png` | Home page, final composite frame of the replay hero | Prod |
| `catalog.png` | Public catalog with filters | Prod |
| `dashboard.png` | Learner dashboard (demo account, populated) | Prod |
| `built-course.png` | Freshly built private course in the learn workbench | Prod |
| `brief-review.png` | Brief review step (level / time budget / outcomes) | Prod |
| `tutor-answer.png` | Tutor answer with retriever row, in the workbench | Prod |
| `eval-page.png` | Public `/eval` page with the sealed-run scores | Prod |
| `agent-trace.png` | Tutor-turn trace drill-down: timeline + retrieval audits | **Local seeded stack** (owner-visible surface; the seeded curated turn is the richest example — note the seed uses the `noop` provider, so its cost badge reads $0) |
| `trace-drilldown.png` | Same surface, top of page (CostBadge + LLM-call row) | Local seeded stack |
| `studio-replay.png` | AI authoring build replay, step-by-step | Local seeded stack |
| `social-preview.png` | The prod `/opengraph-image` render — upload via GitHub *Settings → Social preview* (manual, repo admin only) | Prod |

## Conventions

- Viewport **1280×800 at `deviceScaleFactor: 2`** (2560×1600 PNGs), dark theme, English locale, onboarding pre-dismissed.
- PNGs run through `pngquant --quality 65-90` before commit — keep each under ~300 KB (the dark UI compresses to well under 100 KB).
- GIFs: ≤900 px wide, 12 fps, palette-optimized (`ffmpeg palettegen/paletteuse` → `gifsicle -O3 --lossy=25 --colors 128`), target ≤3 MB each.
- Auth for capture scripts: **API login once per role** (`POST /api/v1/auth/login` via `context.request`), persist `storageState`, never fill the login form in a browser. Note the SPA rotates the refresh token on every page bootstrap, and presenting a consumed token revokes the whole chain — persist storage state after every context, or expect to re-login.

## Regenerating

- The local "hero pack" (trace drill-down, studio replay, admin observability/evals at 1440×900) has a maintained generator: `apps/frontend/tests/e2e/screenshots.spec.ts` (run it against a seeded `make up` stack; it overwrites `hero.png`, `trace-timeline.png`, `studio-replay.png`, `observability.png`, `evals.png` — names not currently embedded by the README except `studio-replay.png`).
- The prod captures were taken with a throwaway Playwright harness following the conventions above (login as `demo@lumen.test`, record `recordVideo` contexts, encode with the ffmpeg pipeline). The walkthrough screencast tooling lives in `tools/recording/`.
