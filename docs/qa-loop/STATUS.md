# QA + Improvement Loop — running log

A persona-driven walk of the live app. Each iteration appends. Format:

```
## Iter N — YYYY-MM-DD — <short title>
**Surfaces walked:** ...
**Fixes landed:** ...
**Improvements landed:** ...
**Improvements rejected (don't re-propose):** ... (with reason)
**Open / deferred:** ...
**Commits:** ...
```

The reject ledger matters — without it, future iterations re-propose the
same things. Be specific about *why* an idea was rejected.

---

## Iter 1 — 2026-05-27 — kickoff (in flight)

**Starting point:** redesign closed Loop 20 (`4f71a4a`); eval arc closed
L41 (`572477d`) with mean=+0.93 / grounding=+2.78 on `/eval/public`. Prod
healthy at https://lumen.ahmedhobeishy.tech. Working tree clean.

**Surfaces inventoried (frontend routes):**
- Public: `/`, `/courses`, `/courses/[slug]`, `/courses/[slug]/preview/[lessonId]`, `/blog`, `/case-study`, `/demo`, `/eval`, `/eval/methodology`, `/login`, `/register`, `/forgot-password`, `/reset-password`, `/verify-email`, `/verify/[id]`, `/confirm-email-change`
- Student: `/dashboard`, `/dashboard/mastery`, `/dashboard/path`, `/dashboard/reviews`, `/dashboard/tutor/...`, `/learn/[slug]`, `/courses/[slug]/discussions/...`, `/profile`
- Instructor: `/studio`, `/studio/new`, `/studio/[id]`, `/studio/[id]/modules/[moduleId]`, `/studio/draft/[courseId]`, `/studio/draft/[courseId]/replay`
- Admin: `/admin`, `/admin/users`, `/admin/courses`, `/admin/subjects`, `/admin/tags`, `/admin/audit`, `/admin/observability`, `/admin/observability/llm-calls/[callId]`, `/admin/evals`, `/admin/evals/[suite]`, `/admin/evals/[suite]/[reportId]`

### Walk findings (raw)

**Public landing (`/`, anonymous):**
- `/favicon.ico → 404` — no favicon at all
- `/api/v1/auth/refresh → 401` fires on cold mount (AuthProvider's `refresh()` runs unconditionally, even for anonymous visitors)
- Footer "Docs" link points to `/docs` which is FastAPI's Swagger UI — misleading label for product visitors

**Catalog (`/courses`):**
- `picsum.photos` cover images flake with `ERR_CONNECTION_CLOSED` (saw it for `react-18-server-components`, `data-engineering-foundations`) — external dependency for portfolio cover art is fragile
- Title is the default `Lumen — Learn what you actually use.` — every non-`/eval` route has the same root title (per-route metadata gap)

**Demo flow (`/demo`):**
- **Major UX bug.** Headline CTA "Try the demo" redirects anonymous visitors to `/learn/typescript-variance?tutor=open&q=...` which is auth-gated. Visitors land on "Sign in to open this course" with no mention of the seeded `demo@lumen.test / Demo!2026` credentials. The README documents them but a recruiter clicking through hits a dead-end.

**Student dashboard:**
- Greeting + completion + mastery surfaces render cleanly; "0 % mastery" is honest (no quiz attempts seeded for the demo learner)
- Mobile @ 375×812 — no horizontal scroll, header 65px

**Instructor studio (`/studio`):**
- **Pluralization bug** in course-list rows: "1 students" / "1 modules" (should be "1 student" / "1 module")
- Onboarding tour appears on first load — works correctly, dismiss button labeled "Skip"
- Course editor, module editor, lesson editor, AI authoring draft replay all render without console errors

**Admin (`/admin`):**
- **Missing cards** on the admin landing: `/admin/observability` and `/admin/evals` are reachable only via direct URL (the landing's "Admin" card grid lists Subjects / Tags / Courses / Users / Audit only)
- Observability: Celery worker shows "celery inspect probe timed out" + Workers panel reads "no data" — needs follow-up (likely worker is up but the inspect RPC is slow; queue depths read 0)
- LLM Traces / Audit / Subjects / Tags / Courses / Eval admin all render with real data

### Fixes to ship this iteration

1. **`app/icon.tsx`** — proper favicon (Next.js convention, derived from Lumen mark)
2. **Per-route metadata** — `Metadata` exports on every public + auth-gated server-renderable surface; client pages get a `metadata.ts` sibling where needed
3. **Footer "Docs" → "API"** — i18n key + label change; the link still points to `/docs` but the label is now honest
4. **Pluralization helper** — `formatCount(n, "student"|"students")` (zero-cost wrapper around `Intl.PluralRules`); use it in the studio course-list + anywhere else "N items" leaks
5. **Demo-flow rescue** — `/demo` now redirects through `/login?next=...&demo=1`; the login page detects `?demo=1`, pre-fills `demo@lumen.test / Demo!2026`, and surfaces a callout: "These demo credentials are public — sign in to watch the tutor work."
6. **Admin landing missing cards** — Observability + Eval harness cards added to the `/admin` grid
7. **Course cover image fallback** — `<CourseCardImage onError>` swaps to a deterministic local SVG placeholder so picsum flakes never paint broken images

### Improvements rejected (don't re-propose)

- *Public indicator cookie + skip refresh-401 on cold mount* — touches auth semantics; would need a non-HTTP-only marker cookie alongside the refresh token so the frontend can decide whether to call `/refresh`. Per the guardrails, anything that changes auth shape is propose-don't-implement. Reason: would be the right fix but is out of scope for a QA-pass iteration. Track separately as a follow-up.

### Improvements deferred (propose, not implementing)

- **Permanent move off `picsum.photos`** — bundle a small set of cover-art SVGs and have the seed pick deterministically per course id. The onError fallback (item #7) covers the immediate console noise but the proper fix is to never depend on an external image service for portfolio cover art at all.

---

**Walk complete.** Applied + shipped over four commits (`bd61b97`,
`ea67155`, `0fc9980`, `928bde2`, `edd215c`, `cdf10db`, `d6ca043`).
Codex review came back clean on the qa-iter1 batch after two rescue
rounds (#1: signed-in /demo bypass; #2: open-redirect guard on
`?next=`).

### CI-only follow-ups uncovered during the deploy chase

- **`tutor-citations.spec.ts` on webkit** — pre-existing race
  between the login form's `router.push("/dashboard")` and webkit's
  Next.js client router. Original failure: stuck at /login for the
  full 5s `toHaveURL` poll; failed all 3 CI retries. Fix shipped in
  `cdf10db` + `d6ca043`:
    1. `data-hydrated="true"` attribute on the auth forms so the
       e2e helpers can wait for React's controlled-input handlers
       to bind before filling (prevents the field-stays-empty path).
    2. `expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 })`
       in the post-login helper so webkit's slower hydration has
       headroom (the default 5s was the immediate trip-wire).
    3. `verify-email/page.tsx` cancellation race: the effect-local
       `cancelled = false` flag was being flipped to true by
       strict-mode's mount → cleanup → re-mount cycle, leaving the
       page pinned on "Confirming…". Swapped for an `unmountedRef`
       set only by the empty-deps mount/unmount effect, plus a
       `tRef` so the effect doesn't re-run on every locale render.
    4. `auth.setup.ts` pre-warms /login, /register, /forgot,
       /reset, /verify-email, /dashboard so the first cold Next.js
       dev compile happens once before any browser project starts
       (matters on slow VMs; harmless on CI).
  Outcome: webkit still flakes attempt 1+2 of the test in CI but
  passes on attempt 3. Job reports it as 1 flaky → 9 passed → job
  green. Real win: prior run failed all 3 retries hard. Acceptable
  for now; if it stops self-healing, the next narrowing is
  building the local web container with `target: prod` (E2E hits
  pre-compiled bundles instead of dev JIT) — Docker Compose's
  `volumes: []` merging makes the override non-trivial, deferred.

### Open / deferred from this iteration

- **`test.fixme` markers (4 skipped in CI):**
  `instructor-golden.spec.ts:39` and `ingest-multimodal.spec.ts:77`,
  each on chromium + webkit. Both need a real LLM provider to
  return structured outline / preview JSON; CI's noop provider
  returns plain text. Un-skipping cost: ~30-60 min — either special
  -case the noop provider to emit canned structured JSON for these
  two task tags, or route just these tests against Groq with bumped
  retries. Both surfaces are covered by the eval harness against
  the real provider, so the E2E gap is shape-regression only.
  **Decision: leave as is for now.** Revisit when a UI change in
  `/studio/draft` or the ingest preview breaks the layout — the
  E2E would be the regression net at that point.

- **Dashboard sub-route metadata** (mastery / path / reviews) —
  inherit "Dashboard · Lumen" from `dashboard/layout.tsx` today;
  could be more specific. Next iteration polish.

- **Dynamic `/admin/evals/[suite]/[reportId]` metadata** — would
  need server-side fetch of the report id. Next iteration.

- **Permanent picsum.photos replacement** — see above; onError
  fallback is the band-aid, bundled SVGs is the proper fix.

- **Local-vs-CI parallel webkit gap** — the QA VM can't sustain
  4 concurrent webkit + chromium contexts hitting cold Next.js dev
  compiles; `data-hydrated` waitFor times out at 60s under heavy
  parallel load. CI's dedicated runners handle it fine. Not a code
  fix — environmental. Documented for the next time the test
  reliability question comes up.

### Commits

`bd61b97` feat(qa-iter1): UX polish from a 3-persona walk of prod
`ea67155` fix(qa-iter1): /login forwards already-signed-in users to ?next
`0fc9980` sec(qa-iter1): clamp /login ?next= to same-origin paths
`928bde2` fix(qa-iter1): /reset-password logs out before pushing to /login
`edd215c` fix(qa-iter1): one-shot auto-forward on /login (kills webkit race)
`cdf10db` fix(qa-iter1): data-hydrated marker so E2E waits for React onChange
`d6ca043` fix(qa-iter1): tighten E2E auth race-fixes for CI webkit
`fa2470e` docs(qa-iter1): close out the iteration log + log the test.fixme gap
`4c6ef4d` ci: remove required-reviewer gate from production env
`c7d2587` fix(tutor): render [L:lesson_id] wire tokens as numbered superscripts

---

## Iter 2 — 2026-05-28 — backend↔UI parity sweep + deferred surface walk (in flight)

**Starting point:** prod on c7d2587 (qa-iter1's full batch + auto-deploy
+ tutor citation fix). Deploy gate removed.

### Parity-audit inventory (BE endpoints with no FE consumer)

Ran `docker compose exec api python -c "from app.main import app; …"` to
dump 126 OpenAPI paths; cross-referenced with frontend usage in
`apps/frontend/src/`. After filtering false positives (FE uses the
endpoint via a parameter-templated path that escapes simple grep), the
real orphans are:

| Endpoint | Decision |
|----------|----------|
| `GET /api/v1/search/courses` | **Delete** — functional duplicate of `/courses?q=` (both call `courses_repo.search_courses`). FE never consumed. |
| `GET /api/v1/users/me/export` | **Wire** — GDPR-style profile export. Added "Download my data" card on `/profile`. |
| `GET /api/v1/admin/llm-calls/summary` | **Defer to iter 3** — needs a real cost-rollup card on `/admin/observability`. |
| `GET /api/v1/admin/rate-limit-stats` | **Defer to iter 3** — observability card. |
| `POST /api/v1/admin/evals/runs` | **Defer to iter 3** — "Run new eval" button + suite picker on `/admin/evals`. |
| `GET/POST/DELETE /api/v1/admin/mcp-clients` (+ `{client_id}`) | **Defer to iter 3** — full new admin page (`/admin/mcp-clients`); Phase I1 backend without a UI. |

Health endpoints (`/health/live`, `/health/ready`) excluded — used by
docker healthchecks + CI, not the SPA.

### Iter 2 — walk findings

Surfaces walked beyond iter 1's coverage:

- **`/blog`, `/case-study`, `/eval/methodology`** — render clean, no
  fixes needed. Per-route titles populate. No broken links.
- **`/courses/[slug]/preview/[lessonId]`** — **parity gap found**.
  The free-preview feature was wired end-to-end (column +
  auth-bypass branch + UI link + page) but **zero seeded lessons
  had is_preview=True**, so the link never surfaced and the
  public-preview code path never fired in real use. Fixed via
  seed update (first lesson of first module per course) + alembic
  migration 0029 backfilling existing rows. After deploy: 11
  preview lessons live.
- **`/studio/draft/[courseId]/replay`** — renders with proper play-
  by-play structure, replay totals, accept/revise/restart CTAs.
  No findings.
- **`/admin/observability/llm-calls/[callId]`** — renders the call
  trace with header + steps. No findings.
- **`/dashboard/tutor/[conv]/turn/[msg]`** — renders with agent run
  totals, underlying LLM call, step-by-step timeline, retrieval
  audits. No findings.
- **`/admin/evals/[suite]`** — **prod-only data gap found**.
  Showed "No runs yet for this suite" on prod even though
  /eval/public had a promoted tutor run with mean=+0.93. SSH'd
  to prod box → `docker exec lumen-prod-api-1 ls /app/evals/
  reports/` returned only `.gitkeep`. Reports + PROMOTED.json
  live on the container's ephemeral filesystem; every image
  rebuild restores from the build snapshot, wiping the reports
  the eval-baseline workflow had written. Fixed via named
  `eval-reports` volume in docker-compose.prod.yml mounted on
  api + worker. Operator must re-run eval-baseline post-deploy
  to repopulate the surface (historical reports unrecoverable).
- **`/courses/[slug]/discussions/[id]`** — skipped, no seeded
  threads. Verified the parent /courses/[slug]/discussions
  empty-state in iter 1.
- **`/verify-email` token flow** — skipped at the token level; the
  static page renders correctly and the cancellation race fix
  shipped in qa-iter1's c7d2587.
- **`/admin/evals/[suite]/[reportId]`** — would require a promoted
  report on the local dev DB (file-based, none present in dev).
  Covered by the volume-persistence fix.

### Iter 2 — batch 1 (d7bb1cb)

- Deleted `apps/backend/app/api/v1/search.py` + removed the
  `include_router` in `app/api/router.py`. Migrated the 4
  `test_search.py` cases to hit `/api/v1/courses` (same repo
  function, same response shape). The dropped "requires q" test
  flipped to "browse listing without q returns the catalog".
- Wired `/api/v1/users/me/export` on `/profile`: new
  `<ExportDataCard>` between sessions + danger-zone. Click →
  fetches the JSON payload → downloads as
  `lumen-export-YYYY-MM-DD.json`. i18n keys added EN + AR.

### Iter 2 — batch 2 (3ced529 + f052bee)

- Demo + ts-variance seeds set `is_preview=True` on the first
  lesson of the first module per course.
- Alembic migration 0029 backfills the same on existing rows
  (idempotent seed wouldn't touch them on prod).
- Codex review caught a CI line-length blip (f052bee — ruff
  format on `app/seeds/demo.py`).

### Iter 2 — batch 3 (ae9124b)

- Persists eval reports across image rebuilds via named volume
  `eval-reports` mounted at `/app/evals/reports` on api + worker.
  Post-deploy operator step: re-run eval-baseline workflow to
  repopulate /eval/public (historical reports unrecoverable).

### Iter 2 — parity gaps deferred to iter 3

Documented but not yet shipped:

| Endpoint | Decision |
|----------|----------|
| `GET /api/v1/admin/llm-calls/summary` | Cost rollup card on `/admin/observability`. ~150 LoC. |
| `GET /api/v1/admin/rate-limit-stats` | Observability card. ~120 LoC. |
| `POST /api/v1/admin/evals/runs` | "Run new eval" button + suite picker. ~200 LoC + a backend that doesn't block 60s synchronously (current impl is sync). |
| `GET/POST/DELETE /api/v1/admin/mcp-clients` (+ `{id}`) | Full new admin page; Phase I1 MCP CRUD has no UI. ~400 LoC. |

---

## Iter 3 — 2026-05-28 — parity gap closure (observability + eval ops)

**Starting point:** iter 2 closed; 3 of 4 deferred parity gaps
chosen for this iteration.

### Iter 3 — batch 1 (ba5749e)

Two new tabs on `/admin/observability`:

- **LLM Cost** wires `GET /api/v1/admin/llm-calls/summary?days=14`.
  Headline tiles (calls, spend) + by-feature table + by-day table.
  Refetches every 60s.
- **Rate Limits** wires `GET /api/v1/admin/rate-limit-stats`. Total
  429 count in the rolling window + by-endpoint breakdown sorted
  descending. Refetches every 30s.

### Iter 3 — batch 2 (454b7d4)

`/admin/evals` gets a "Run now" form above the suite-card grid:

- Suite picker, optional limit input, "Run now" button
- Wires `POST /api/v1/admin/evals/runs` (synchronous backend, so
  the form copy + spinner state make the long wait visible)
- onSuccess invalidates the `["admin", "evals"]` query namespace
  so the suite cards refresh with the new mean inline
- "No runs yet" empty-state copy on each card now points at the
  form first, CLI fallback secondary

### Iter 3 — deferred to iter 4

| Endpoint | Reason for defer |
|----------|------------------|
| `GET/POST/DELETE /api/v1/admin/mcp-clients` (+ `{id}`) | ~400 LoC for a full new admin page (list + mint-secret + revoke flows). Substantial enough to be its own iteration. |

### Iter 3 — post-deploy operator step

The eval-reports volume (iter 2's ae9124b) lands with this
iteration's CI. Once deployed, re-run the eval-baseline workflow to
repopulate `/eval/public`:

```
gh workflow run eval-baseline.yml -f suite=tutor -f limit=30 \
  -f promote=true
```

The historical reports (the +0.93 mean from L41) are not
recoverable — they were on the ephemeral container fs.

### Iter 3 — commits

`ba5749e` feat(qa-iter3): /admin/observability — LLM cost + rate-limit tabs
`454b7d4` feat(qa-iter3): "Run now" form on /admin/evals

---

## Iter 4 — 2026-05-28 — mcp-clients admin page

**Starting point:** iter 3 closed; one parity gap deferred — the
MCP client CRUD endpoints had no UI.

### Iter 4 — batch 1 (738573a + 2c20150)

New `/admin/mcp-clients` page covering all three endpoints:

- **List** (`GET /api/v1/admin/mcp-clients`) — table with client
  short-id, owner, scopes, last_used_at, created_at. Toggle for
  "include revoked" rows.
- **Mint** (`POST /api/v1/admin/mcp-clients`) — Dialog with owner
  picker (debounced search against `/admin/users?q=…`), name,
  comma-separated scopes (default `*`). One-time-secret reveal
  Dialog on success — copy button + "I've saved it" close. Secret
  is wiped from React-Query mutation cache after reveal (Codex
  rescue) so the "unrecoverable" promise is honest.
- **Revoke** (`DELETE /api/v1/admin/mcp-clients/{id}`) — per-row
  two-step inline confirm (Cancel / Confirm swap). Soft-delete
  keeps audit history available via the include-revoked toggle.

Added `admin.tile.mcpClients.*` i18n keys + tile on /admin landing.

### Iter 4 — commits

`738573a` feat(qa-iter4): /admin/mcp-clients page (close last parity gap)
`2c20150` fix(qa-iter4): mcp-clients — codex rescue

### Backend↔UI parity audit — RESULT

All 4 deferred orphans from iter 2 are closed:

| Endpoint | Status | Shipped in |
|----------|--------|------------|
| `GET /api/v1/admin/llm-calls/summary` | ✓ UI on /admin/observability | iter 3 |
| `GET /api/v1/admin/rate-limit-stats` | ✓ UI on /admin/observability | iter 3 |
| `POST /api/v1/admin/evals/runs` | ✓ "Run now" form on /admin/evals | iter 3 |
| `GET/POST/DELETE /api/v1/admin/mcp-clients` (+ `{id}`) | ✓ /admin/mcp-clients page | iter 4 |


