# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed (iteration 103) — whitelist `http://web:3000` in api CORS
- After iter 102 the e2e bundle correctly POSTed to
  `http://api:8000/api/v1/auth/login`, but the api still
  returned `400 Disallowed CORS origin`. Pre-flight from
  `Origin: http://web:3000` was being rejected because
  `CORS_ORIGINS` only whitelisted `http://localhost:3000`.
  Added `http://web:3000` to:
  - the `CORS_ORIGINS` default in `docker-compose.yml` (so
    a fresh checkout without `.env` works out of the box)
  - `.env.example` (so the next person who copies it forward
    inherits the e2e-friendly value); the comment now also
    pins the JSON-array shape iter 98 first required.
  Local `.env` was edited too (not committed — gitignored).
- **Regression test**:
  `apps/frontend/tests/compose-cors.test.ts` reads the compose
  file and asserts the default `CORS_ORIGINS` substitution
  includes both `localhost:3000` and `web:3000`. A future
  edit that drops the e2e entry fails CI before the symptom
  resurfaces as a silent login failure.
- **Result**: 4/12 → 6/12 specs green —
  `smoke › student signs in and reaches dashboard` now passes
  on both chromium and webkit. The remaining 6 failures
  (instructor-flow, learner-journey enroll/complete,
  learner-journey language-switcher) surface deeper-in-the-flow
  test bugs that belong to iter 104+.

### Fixed (iteration 102) — browser-side API base URL inside the e2e container
- The dev bundle is built with `NEXT_PUBLIC_API_BASE_URL=
  http://localhost:8000` so a host browser can reach the
  published api port. But when Playwright loads the same bundle
  inside the `e2e` container — page served from `http://web:3000`
  — `localhost` resolves to the e2e container itself and every
  API call hits "nothing". `apps/frontend/src/lib/env.ts` now
  exposes `API_BASE_URL` / `WS_BASE_URL` as getters that detect
  `window.location.hostname === "web"` at runtime and swap to
  the docker-network hostname `api:8000` for that case only;
  host browsing (hostname `localhost`) and prod
  (`lumen.example.com` etc.) keep the bundled value.
- **Regression test**:
  `apps/frontend/tests/env-api-base.test.ts` covers all three
  hostname branches with a stubbed `window.location` so a
  revert back to a constant fails CI before login starts
  silently failing in the e2e run.
- **Visible result**: still 4/12 specs green — the bundle now
  correctly POSTs to `http://api:8000/api/v1/auth/login` (verified
  in the Playwright trace), but the api itself returns
  `400 Disallowed CORS origin` because `CORS_ORIGINS` only
  whitelists `http://localhost:3000`. That's iter 103.

### Fixed (iteration 101) — strict-mode `Sign in` selector clash in e2e
- All three sign-in-required e2e specs failed
  `locator.click: strict mode violation: getByRole('button',
  { name: /sign in/i }) resolved to 2 elements` because the
  navbar's "Sign in" link contains a button with the same
  accessible name as the form submit. Scoped the form-submit
  selector to `page.locator("form").getByRole(...)` in
  smoke.spec.ts, learner-journey.spec.ts, and
  instructor-flow.spec.ts. No regression test — the strict-mode
  violation IS the regression check; replacing it would be
  redundant.
- The 4/12 → 4/12 pass count is misleading: this fix removes
  the strict-mode error, but the next-down failure (`expect
  (page).toHaveURL(/\/dashboard/) → received
  "http://web:3000/login"`) takes its place and keeps the
  smoke + learner-journey + instructor-flow specs red. Root
  cause: browser-side fetch from inside the e2e container tries
  `http://localhost:8000` (bundle's `NEXT_PUBLIC_API_BASE_URL`)
  which resolves to the e2e container, not the api. That's
  iter 102.

### Fixed (iteration 100) — Playwright timeouts + worker contention against `pnpm dev`
- **0/12 e2e specs passing**, all `TimeoutError: page.goto:
  Timeout 60000ms exceeded` once iter 99 made them runnable.
  Manual `curl` of `/` and `/login` returned in <1s, so the
  server wasn't broken — it was *contention*. Playwright's
  default 6 parallel workers each cold-loaded a different page,
  Next.js dev mode compiles routes on first hit on a single
  thread, and six compiles serialised behind one mutex blew
  past the 30s default per-test timeout. The combined effect
  was indistinguishable from a hung navigation.
- **Two coordinated changes in `playwright.config.ts`**:
  - lift `timeout` to 90s, `navigationTimeout` to 60s, and
    `actionTimeout` to 15s so one cold compile fits inside the
    test ceiling
  - cap `workers` at 2 (override via `PLAYWRIGHT_WORKERS=N`)
    so concurrent compiles don't trample each other while the
    e2e service still runs against `pnpm dev`. The cap can be
    removed once we point the service at a pre-built
    `pnpm start` target.
- **Regression test**: `apps/frontend/tests/playwright-
  timeouts.test.ts` reads the resolved Playwright config and
  pins minimum floors on `timeout`, `navigationTimeout`,
  `actionTimeout`, and a `workers <= 2` upper bound — so a
  future edit that quietly reverts any of them fails CI before
  the symptom surfaces in the e2e run.
- **Result**: 4/12 specs now green (`smoke › home page loads`
  and `smoke › can navigate to catalog` for both chromium and
  webkit). The remaining 8 surface real test/app bugs (Sign-in
  button selector matches two elements; sign-in redirect to
  /dashboard never fires) which belong to iter 101+.

### Fixed (iteration 99) — Playwright e2e runnable inside the stack
- **`pnpm test:e2e` failed 12/12** with
  `browserType.launch: Executable doesn't exist at
  /root/.cache/ms-playwright/...`. Root cause: the `web` dev
  image is `node:22-alpine` (musl libc) and Playwright only
  ships browser binaries for glibc — so even running
  `pnpm exec playwright install` inside `web` either fails or
  pulls binaries that segfault on first launch.
- **Fix**: dedicated `e2e` service in `docker-compose.yml` using
  `mcr.microsoft.com/playwright:v1.49.1-jammy`. Chromium /
  firefox / webkit are pre-built against the right libc and
  pinned to the same version as `@playwright/test`. The service
  sits behind a `profiles: ["e2e"]` gate so `docker compose up`
  doesn't start it; `make test.e2e` runs it via
  `docker compose --profile e2e run --rm e2e`. Re-uses an
  `e2e-node-modules` volume so `pnpm install` is a one-time cost
  per fresh checkout.
- **Sub-fix**: pin `@playwright/test` to exact `1.49.1` (no
  caret). Without a `pnpm-lock.yaml` in this repo, `^1.49.1`
  resolved to 1.60.0 on a fresh install while the image
  stayed at `v1.49.1-jammy` — and 1.60.0's runtime then
  couldn't find its browsers (different webkit bundle path)
  for the same 12/12 failure dressed up differently. Pin
  enforced by the regression test below.
- **Sub-fix**: bake `pnpm install` into a custom
  `apps/frontend/Dockerfile.e2e` so `node_modules` lives in an
  image layer instead of a Docker volume — pnpm's symlink
  fan-out into a bind/named volume on Windows Docker Desktop
  crawls at ~10 packages/min. Anonymous `/work/node_modules`
  volume keeps the host bind-mount from shadowing the baked
  install.
- **Regression test**:
  `apps/frontend/tests/e2e-image-pin.test.ts` reads
  `docker-compose.yml` + `package.json` and asserts (a) the
  `e2e:` service still exists, (b) the image tag's `vX.Y.Z`
  matches `@playwright/test`, and (c) `@playwright/test` is
  pinned to an exact version (no `^` / `~`) so the resolved
  runtime can't drift above the image's browser bundle.

### Fixed (iteration 98) — six real bugs uncovered by actually running the stack
- **Backend Dockerfile** `deps` stage failed on a clean checkout
  (no `uv.lock`): the fallback `uv pip install -e '.'` needs an
  `app/` directory that doesn't exist yet. Added a stub
  `mkdir app && touch app/__init__.py`; the real source is copied
  in later stages and overrides the stub.
- **Meilisearch host port 7700** sits in Windows / WSL2's
  reserved `7681-7780` range — `docker compose up` failed with
  "ports are not available". Removed the host binding (the API
  reaches search via the docker network anyway); documented how
  to re-enable on a different host port.
- **Meilisearch healthcheck** used `wget http://localhost:7700`
  but busybox wget resolves `localhost` to `::1` first and the
  daemon listens IPv4-only — pinned to `127.0.0.1`.
- **`CORS_ORIGINS`**: pydantic-settings v2 parses `list[str]`
  fields as JSON before the `mode="before"` validator runs;
  comma-separated was rejected. Switched the docker-compose
  default + `.env` to JSON-array syntax with a comment.
- **Structlog config** registered `add_logger_name` with a
  `PrintLoggerFactory` — incompatible (PrintLogger has no
  `.name`), so the first log call after startup crashed. Dropped
  the processor; `CallsiteParameterAdder` already provides
  MODULE / FUNC_NAME / LINENO which is strictly more useful.
- **`EmailStr` rejected `student@lumen.test`** — the upstream
  `email-validator` enforces RFC 6761 and refuses reserved TLDs.
  New `app.core.email_type.Email` Pydantic type uses
  `test_environment=True` so seed accounts and test fixtures
  keep working; swapped at every `EmailStr` site.
- **`user.role.value` AttributeError on first login** — column
  typed `Mapped[Role]` but stored as `String(20)` without a
  TypeDecorator, so SQLAlchemy returns a plain str on read.
  Wrapped the access with `str(user.role)` (correct for both
  StrEnum instances and plain strings).
- **Live verification via Chrome**: signed in as the seeded
  student, dashboard renders, course detail (forum link +
  syllabus) renders, language switcher flips `<html lang="ar"
  dir="rtl">` and nav strings switch to Arabic. All green.

### Tests (iteration 97)
- **Two new Playwright e2e specs** beyond the existing smoke
  test:
  - `learner-journey.spec.ts`: sign-in → catalog → enroll → first
    lesson → mark complete. Plus a `language switcher toggles
    document direction` case that flips `<html dir>` between LTR
    and RTL using iter 93's LocaleSwitcher.
  - `instructor-flow.spec.ts`: sign-in → studio → new course →
    add module → add text lesson → publish → see it on the
    public catalog. Exercises the iter 43 "must have a lesson to
    publish" guard end-to-end via the green path.

### Fixed (iteration 96)
- **Mobile polish.** Three real UX issues after auditing:
  - `/learn/[slug]` re-ordered the 3-column desktop layout so the
    **player is first** on mobile (`order-1 lg:order-none`)
    instead of stacking after the outline — a learner on a phone
    now lands on the lesson, not a list to scroll past.
  - Chat panel on `/learn` was a fixed `h-[600px]` that took the
    whole viewport on mobile — now `h-[400px] lg:h-[600px]`.
  - Admin Audit and Admin Courses tables had no
    `overflow-x-auto` wrapper; wide columns broke the layout on
    small viewports. Wrapped consistent with the existing users /
    cohort tables.
  Audit found the unprefixed `grid-cols-2` / `grid-cols-3` usages
  are intentionally dense (stat tiles, constrained-aside button
  grids) and render correctly on phones.

### Added (iteration 95)
- **RTL polish sweep — 48 directional Tailwind classes → logical
  properties across 23 files.** `pl-N` → `ps-N`, `pr-N` → `pe-N`,
  `ml-N`/`mr-N` → `ms-N`/`me-N`, `left-N`/`right-N` → `start-N`/
  `end-N`, `text-left`/`text-right` → `text-start`/`text-end`,
  `rounded-l-`/`rounded-r-` → `rounded-s-`/`rounded-e-`. These
  compile to CSS `margin-inline-*` / `inset-inline-*` /
  `padding-inline-*` which the browser flips automatically under
  `dir="rtl"`. Switching to Arabic via the iter 93 switcher now
  gets icon-before-text spacing, search-icon position, table
  column alignment, and the skip-to-content focus indicator all
  mirrored correctly without per-locale CSS. One-shot
  `scripts/rtl-sweep.py` kept in-tree so the next contributor
  adding a directional class has a reference for the convention.

### Added (iteration 94)
- **SiteHeader + HeaderSearch translated.** First production
  consumers of iter 93's `t()`. NavLink data shape switched from
  `{href, label}` to `{href, labelKey: MessageKey}` so the type
  system catches a typo'd key at compile time. While translating
  I also swapped `mr-1` / `left-2.5` / `pl-8` / `text-left` for
  Tailwind's logical-property variants (`me-1`, `start-2.5`,
  `ps-8`, `text-start`) — those flip automatically under
  `dir="rtl"` so the icon spacing and search affordance work in
  Arabic without per-locale CSS.

### Added (iteration 93)
- **i18n scaffolding with English + Arabic.** In-house zero-dep
  module (`src/lib/i18n/`): `Locale` type, per-locale message
  dictionary keyed on a closed `MessageKey` union, a
  `LocaleProvider` that persists choice to localStorage and keeps
  `<html lang dir>` in sync. Defaults to the browser language on
  first visit (Arabic-locale browsers land on `ar`). `LocaleSwitcher`
  toggle added to the site header. Parity test
  (`tests/i18n-parity.test.ts`) fails the build if any English key
  is missing or empty in the Arabic file. Component-level use of
  `t()` rolls out across the next iterations — this commit ships
  the foundation + the switcher, not the per-component translation.

### Docs (iteration 92)
- **README features section caught up to iter 51-91.** Added the
  features shipped across the recent runs (discussions, captions,
  FTS ranking, learning outcomes, quiz attempts, HIBP, Idempotency-
  Key, ETag, CSRF guard, OTel, branded HTML emails, …) so a new
  contributor's first read accurately reflects what the platform
  actually does.

### Added (iteration 91)
- **Subscribe / Unsubscribe button on the discussion thread page.**
  Surfaces iter 90 on the UI: Bell icon next to the thread title,
  state-aware label (Subscribe vs Subscribed), tooltip explains
  the consequence in plain English. Hidden for anonymous viewers.
  Toggle hits POST or DELETE based on the current `is_subscribed`
  flag from the detail response.

### Added (iteration 90)
- **Discussion subscriptions.** Iter 79 notified only the thread
  *author* on each reply. Non-authors who found a useful thread
  had to manually re-visit. New `discussion_subscriptions` table +
  endpoints (`POST/DELETE /discussions/{id}/subscribe`) plus
  auto-subscribe for the thread author at create and for any
  replier at reply (GitHub pattern: replying is an interest
  signal). Reply notifications fan out to every subscriber except
  the replier, capped at 200 per reply so a runaway-popular thread
  can't storm the notifications table.
  `DiscussionDetail.is_subscribed` exposes the per-viewer flag so
  the UI can render Subscribe vs Unsubscribe without a second
  round-trip. Migration `0007_discussion_subscriptions`. Covered
  by `tests/test_discussion_subscriptions.py` (6 tests).

### Added (iteration 89)
- **Studio editor for course title / overview / difficulty / cover.**
  Previously those four fields were locked at create time — to fix
  a typo, an instructor had to delete + recreate the course
  (losing enrollments). New "Course details" card on the studio
  page edits all four, with dirty-state Save and a heads-up that
  renaming regenerates the slug. Reuses `Courses.patch` (the
  backend already supports the field-update calls from iter 86's
  outcomes work).

### Docs (iteration 88)
- **ADR-0014 catches the iter 73-87 product surface expansions.**
  Bundles the design rationale for quiz attempt history,
  discussions (cross-references ADR-0013), video captions, FTS
  ranking, and the "What you'll learn" outcomes into one
  reference so the five-feature batch doesn't become folklore.
  Notes the deferred-but-real items (Stripe, materialised
  tsvector + GIN) as out-of-scope with the trigger condition
  for each.

### Added (iteration 87)
- **Studio editor for the iter 86 "What you'll learn" outcomes.**
  New card on the studio course page lets instructors add / remove
  / edit up to 12 bullet outcomes with per-item 240-char input
  limit and an obvious dirty-state Save button. Reuses
  `Courses.patch` so the wire shape stays consistent; server-side
  validators (trim, drop empties, cap count + per-item length)
  remain authoritative.

### Added (iteration 86)
- **Course "What you'll learn" bullet list.** Standard LMS
  conversion element. JSONB `learning_outcomes` column on
  `courses` with Pydantic-side trimming, empty-drop, 240-char
  per-item cap, 12-item list cap. Migration
  `0006_course_learning_outcomes` backfills existing rows with
  `[]`. CourseCreate / CourseUpdate / CourseDetail carry the
  field; the detail page renders a 2-column emerald-check grid
  above the syllabus, hidden when empty. Covered by
  `tests/test_learning_outcomes.py` (6 tests).

### Added (iteration 85)
- **Catalog search uses Postgres full-text with relevance ranking.**
  Pre-iter 85 `?q=` was pure ILIKE substring — no relevance order,
  no quoted-phrase support, partial-word matches only by accident.
  Now uses `websearch_to_tsquery` + `ts_rank` against
  `to_tsvector('english', title || overview)` for tokenised stem-
  aware matching, with the ILIKE substring kept as a fallback so
  "java" still finds "javascript" (FTS would only match "java"
  or "javas"). Title-position weighting in ts_rank surfaces title
  hits above body-only hits. Explicit `?sort=` still wins; rank
  becomes the tiebreaker. No new indexes — at current table sizes
  the inline `to_tsvector` is cheap; promote to a materialised
  tsvector column + GIN index once a course catalog crosses ~1M
  rows. Covered by `tests/test_catalog_fulltext.py` (4 tests:
  title-hit ranks above body-only, partial-word fallback works,
  stem matching via FTS, no-query path honours sort).

### Security (iteration 84)
- **ETag on course detail now carries auth-aware cache hints.** Iter
  76 added the ETag itself but the response had no `Cache-Control`
  / `Vary` headers, leaving the decision up to whatever proxy was
  in front. A CDN could cache an authenticated 200 and serve it
  back to an anonymous caller hitting the same URL — the body
  contains `is_enrolled`, `is_bookmarked`, `progress_pct` per-viewer
  state. Authenticated now → `private, max-age=0, must-revalidate`;
  anonymous → `public, max-age=60, must-revalidate`; both carry
  `Vary: Accept-Encoding, Authorization, Cookie`. The 304 path
  re-emits both headers (raised exceptions don't inherit response-
  object headers). Two new tests in `test_course_detail_etag.py`.

### Added (iteration 83)
- **Branded HTML emails alongside plain text.** Every transactional
  email (password reset, verify, email-change confirm) now goes out
  as multipart — plain text *and* a self-contained HTML alternative
  with inlined CSS so it renders consistently across Gmail / Outlook
  / Apple Mail. Table-based CTA button (the only thing every email
  client respects), with a "or paste this link" plaintext fallback
  for screen readers and clients that strip buttons. No template
  engine — Python f-strings against a tiny shape via
  `app/services/email_template.py`. Heading and paragraphs are
  HTML-escaped so a malicious display name can't inject script.
  Covered by `tests/test_email_html.py` (4 tests).

### Added (iteration 82)
- **WebVTT captions for video lessons.** Accessibility gap — every
  video lesson should be captionable. `VideoLessonData` gains
  optional `captions_url`, `captions_label` (default "English"),
  `captions_lang` (BCP-47, default "en"). The lesson player
  renders `<track kind="captions" default>` so captions are on
  out of the gate (opt-out, not opt-in). The lesson editor gains
  three fields under the video URL — URL, label, language. The
  presign allow-list for `kind="lesson"` adds `text/vtt` so
  instructors can upload captions through the normal flow.
  Covered by `tests/test_video_captions.py` (4 tests: schema
  round-trip, optional with sensible defaults, 500-char URL cap,
  upload allow-list contains text/vtt).

### Docs (iteration 81)
- **ADR-0013 documenting the discussion-thread design.** Captures
  the two-table flat-reply model from iter 77, the "why not
  nested" rationale (every modern Q&A forum has converged on
  Stack-Overflow's answer + comments shape), the visibility
  reuse from ADR-0008, and the notification feedback loop iter
  79 + 80 closed.

### Added (iteration 80)
- **Notification bell deep-links to the relevant entity.** Click on
  a notification now both marks it read and (when the kind carries
  enough payload) navigates to the target: enrolled / cert-ready /
  lesson-available → course detail; review-received → course
  detail + #reviews anchor; discussion-reply → the thread page
  added in iter 78. Hover affordance + cursor only appear when a
  deep-link is available; notifications without a known target
  still mark-as-read on click.

### Added (iteration 79)
- **Discussion replies notify the thread author.** New
  `NotificationKind.discussion_reply` ping in the asker's inbox
  when someone replies to their thread, carrying
  `{discussion_id, reply_id, course_id}` so the bell can deep-
  link. Self-replies don't notify (no signal in self-talk); a
  thread whose author was deleted (FK SET NULL) doesn't crash —
  the notification is silently skipped. Kind is a string column
  so no migration is needed for the new enum value. Covered by
  `tests/test_discussion_reply_notifies.py` (3 tests).

### Added (iteration 78)
- **Discussions UI: list + thread detail pages, link from course
  detail.** `/courses/[slug]/discussions` lists threads (avatar,
  title, author, last-activity relative, reply count chip) with
  an inline "Start a thread" form for signed-in viewers.
  `/courses/[slug]/discussions/[id]` shows the thread body + flat
  replies with avatars, plus a reply composer at the bottom. Trash
  icon appears for the author or admin on both threads and replies
  (the course-owner moderation path is server-enforced; UI just
  shows the affordance when the viewer is the author/admin to keep
  the surface predictable). Link to the discussion forum added to
  the course-detail sidebar.

### Added (iteration 77)
- **Course discussion threads (forum-style Q&A).** Real LMS gap:
  chat scrolls and isn't threadable; reviews are 1-rating-per-learner.
  New flat-thread forum: `Discussion` (title + body + author + soft-
  delete) and `DiscussionReply` (body + author + soft-delete) — no
  nesting, S.O.-style "answer + comments" semantics. Endpoints under
  `/courses/{id}/discussions` (list, create) and `/discussions/{id}`
  (get, patch, delete, reply, delete-reply). Visibility reuses
  `can_view_course` so drafts stay private, archived stays
  accessible to enrolled learners. Soft-delete is author / course
  owner / admin. Replies bump the parent's `updated_at` so the
  list-for-course sort surfaces recently-active threads first.
  Rate-limited (create 10/min, reply 20/min). Migration
  `0005_discussions`. Covered by `tests/test_discussions.py` (7
  tests). Frontend UI follows in iter 78.

### Performance (iteration 76)
- **ETag / If-None-Match on course detail.** The detail endpoint is
  the highest-traffic personalised-but-cacheable read in the API
  (every catalog click, every return to `/learn`). Weak ETag derived
  from `(course_id, updated_at, viewer flags, stats counters)` —
  covers every field that goes into the response, so any
  consequential server-side change (publish, new enrollment, rating
  shift, viewer enrolling, marking a lesson complete) invalidates
  it automatically. Matching `If-None-Match` returns 304 with the
  same ETag and no body; a returning learner / mobile client saves
  the per-detail JSON payload (~ tens of KB once modules + lessons
  are dense). Covered by `tests/test_course_detail_etag.py` (5
  tests: ETag present, 304 on match, ETag changes on rename,
  per-viewer ETag differs (no anon→authed cross-leak), stale
  If-None-Match returns full body).

### Added (iteration 74)
- **Quiz player shows attempt history.** Surfaces iter 73's
  `/me/progress/lessons/{id}/quiz/attempts` endpoint as a "Past
  attempts (N)" strip above the quiz: pass-mark badges (emerald
  for passed, muted for failed), score numbers, ISO timestamp on
  hover. Loaded on mount and refreshed after each submit, so a
  returning learner immediately sees their trend. Gracefully
  hides if the endpoint hiccups — the quiz itself still works.

### Added (iteration 73)
- **Quiz attempt history (append-only).** Previously `submit_quiz`
  overwrote `LessonProgress.payload` on every retake, so a learner
  saw only their latest score and instructors couldn't see whether
  someone struggled before passing. New `quiz_attempts` table is
  append-only — every submission writes a fresh row capturing
  score, passed, the verbatim answers, and submitted_at. Indexed
  on `(enrollment_id, lesson_id, created_at)` for the common
  "latest N attempts" read. New endpoint
  `GET /me/progress/lessons/{id}/quiz/attempts` returns the
  calling user's history (newest first, capped at 50). FK
  cascades on hard-delete of enrollment / lesson; soft-deletes
  leave history intact. Migration `0004_quiz_attempts`. Covered
  by `tests/test_quiz_attempts_history.py` (4 tests: each
  submission creates a row, listing is scoped per-user newest-
  first, empty when never enrolled, 404 for unknown lesson).

### Docs (iteration 72)
- **ADR-0012 documenting the cache + observability stack.** Pairs
  the rationale for the catalog cache headers (iter 66), the JSON-
  only CSP (iter 70), and the OTel wire-up (iter 71). All three
  share the same "cheap when off, useful when on" shape and the
  same "removing this looks safe but isn't" review hazard — so
  documenting them together makes the future "is this load-bearing?"
  question answerable from the docs alone.

### Added (iteration 71)
- **OpenTelemetry tracing wired up.** The OTel dependencies and
  settings (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`) have
  been in the project since the rewrite; this adds the actual SDK
  init. Opt-in (no-op when endpoint is empty so dev/CI/air-gapped
  runs don't phone home), idempotent re-init guards (uvicorn
  `--reload` would otherwise stack exporters). Auto-instruments
  FastAPI (with `/metrics` + `/` excluded — Prometheus scrapes are
  noise), SQLAlchemy, and Redis. Covered by `tests/test_tracing.py`
  (no-endpoint is no-op + idempotent re-init).

### Security (iteration 70)
- **Strict CSP on JSON responses.** Sets `Content-Security-Policy:
  default-src 'none'; frame-ancestors 'none'; base-uri 'none'` on
  every JSON response. JSON doesn't render in a browser, so this
  costs nothing for legitimate clients but kills the "what if
  someone tricks a browser into treating our response as HTML"
  attack class outright. Skipped for HTML responses so Swagger UI
  at `/docs` (which needs inline scripts) keeps working. Covered by
  two new tests in `test_security_headers.py`.

### Security (iteration 69)
- **Strip the `Server` header from every response.** uvicorn
  advertises itself as `Server: uvicorn` by default — common
  information-disclosure finding (helps attackers fingerprint a
  known-version stack). SecurityHeadersMiddleware now removes it
  on the way out. Test added to `test_security_headers.py` (1).

### Added (iteration 68)
- **Export CSV button on the cohort card.** Surfaces the iter 67
  endpoint from the studio cohort view. Plain anchor with `download`
  rather than fetch-blob so the cookie flow and any future Range
  support stay automatic via the browser. Hidden when there are no
  enrolled learners — nothing to export.

### Added (iteration 67)
- **Cohort CSV export for instructors.** `GET /courses/{id}/students.csv`
  returns the same data the cohort UI shows as a downloadable CSV
  (`Content-Disposition: attachment`), so instructors can import
  into a gradebook / spreadsheet without screen-scraping. Reuses
  the existing `cohort_for_course` service so authz, soft-delete
  handling, and the 500-row cap are identical. Returns `Cache-
  Control: private, no-store` — cohort data is per-instructor and
  changes on every enrollment / completion. Covered by
  `tests/test_cohort_csv.py` (3 tests: header + content shape with
  a completer and a pending student, non-owner instructor 403,
  RFC-4180 quoting for special characters in learner names).

### Performance (iteration 66)
- **Cache-Control hints on public catalog reads.** `/subjects`,
  `/tags`, and `/courses` (when called anonymously) now return
  `Cache-Control: public, max-age=60, stale-while-revalidate=300`
  + `Vary: Accept-Encoding, Authorization` so a CDN / reverse
  proxy can absorb a homepage thundering herd. Authenticated
  callers on the same routes get `private, max-age=0, no-store` —
  a Bearer'd body must never linger in a shared cache where it
  could leak to the next anonymous request with the same URL.
  Covered by `tests/test_catalog_cache_headers.py` (3 tests:
  subjects + tags carry public hints; courses splits public/private
  on auth presence).

### Docs (iteration 65)
- **ADR-0011 documenting Idempotency-Key and rate-limit identity.**
  Both decisions answer "who is this request?" — Idempotency to
  scope a replay cache, rate-limiting to scope a token bucket —
  and the same forces apply (NAT-share is unsafe, JWT verification
  is expensive on the hot path, cookies must be hashed not decoded).
  Grouping them in one ADR makes future drift visible: if either
  ever needs to change its identity strategy, the other should be
  re-examined too.

### Added (iteration 64)
- **Email-change UI on the profile page.** Iter 59 shipped the
  backend two-step flow but no UI surfaced it. Profile page now has
  a "Change email" card (current email shown disabled, new email +
  current password fields, friendly "we sent a link to {new email}"
  toast). New `/confirm-email-change` route handles the token from
  the inbox link: calls the confirm endpoint, logs out client-side
  to match the server's refresh-token revocation, and tells the user
  to sign in with the new address. Error states map iter 59's typed
  error codes (`email_change.invalid`, `email_change.stale`,
  `auth.email_taken`) to specific copy instead of falling back to
  the raw server message.

### Tests (iteration 63)
- **Extracted and pinned the iter 35 lesson-resume logic.** The
  "land on the first incomplete lesson, fall back to lesson 1 if
  the course is done" heuristic was inlined in a useEffect inside
  the `/learn/[slug]` page — untestable without spinning up TanStack
  + auth + router mocks. Moved to `src/lib/lesson-resume.ts` as a
  pure `pickResumeLessonId(lessons)` helper and covered in
  `tests/lesson-resume.test.ts` (5 cases: empty course returns
  null, nothing-completed returns lesson 1, mixed returns first
  incomplete, all-complete falls back to lesson 1, single-lesson
  edge cases).

### Tests (iteration 62)
- **Aligned frontend tests with iter 55 + 56 contract changes.**
  `tests/image-upload.test.tsx` was still asserting the old PUT
  presign shape (`{method: "PUT", headers}`) and a PUT request to
  S3; updated to POST + multipart `FormData` carrying every signed
  field plus the `file`. Added a regression for the 403 EntityTooLarge
  → friendly toast translation that iter 56 introduced. Added two
  cases to `tests/notifications-bell.test.tsx` exercising the
  "Mark all read" affordance from iter 55: the button fires the
  read-all endpoint when there's unread, and is hidden when there
  isn't.

### Fixed (iteration 61)
- **Rate-limit buckets are now per-user, not per-IP.** slowapi's
  default `get_remote_address` keyed every bucket by remote address,
  so two learners behind the same NAT (office, school, coffee shop)
  shared one bucket — a single noisy account could lock out every
  colleague on the same gateway. New `_identity_key` derives the
  bucket from the JWT `sub` when an Authorization header is present,
  the hashed auth cookie when not, and only falls back to the IP for
  fully anonymous traffic (where IP is the best identity we have).
  Covered by `tests/test_rate_limit_per_user.py` (2 tests: noisy
  account drains its bucket but a second account on the "same IP"
  in tests can still post; anonymous still keys by IP).

### Docs (iteration 60)
- **Three new ADRs documenting the seams the audit sweep hardened.**
  ADR-0008 captures the soft-delete / unpublished-course visibility
  rules and the two predicates (`get_course`, `can_view_course`)
  that every endpoint should pick from. ADR-0009 records the
  unified password policy + opt-in HIBP gate, including the
  fail-open and padding-row decisions. ADR-0010 pins the request
  hardening middleware order (CSRF → Idempotency → SecurityHeaders
  → RequestId → GZip) with reasoning for why each pair sits where
  it does — so a future contributor inserting a new middleware
  doesn't accidentally widen a hole.

### Added (iteration 59)
- **Email change flow.** Previously email was immutable post-
  registration. New two-step flow: `POST /users/me/email/request`
  verifies the current password, checks the target isn't taken, and
  sends a 1-hour confirmation token to the **new** mailbox (proves
  the user controls it). `POST /users/me/email/confirm` applies the
  change, audits the old → new transition, and revokes every refresh
  token so parallel sessions on other devices have to re-authenticate.
  Token is bound to the current password hash — rotating the password
  mid-flow invalidates outstanding email-change tokens, same posture
  password-reset uses. Covered by `tests/test_email_change.py` (8
  tests: wrong password / taken / same-email-noop on request, full
  round-trip, password rotation invalidates token, race-clash at
  confirm, garbage token rejected, refresh tokens revoked).

### Added (iteration 58)
- **Idempotency-Key support on mutating endpoints.** CLAUDE.md flagged
  this as planned in v1. Opt-in via the `Idempotency-Key` header on
  POST/PUT/PATCH/DELETE. Behaviour follows the draft RFC: same key +
  same body within the 24h TTL returns the cached response (with
  `Idempotent-Replayed: true` so observability can distinguish
  replays from re-executions); same key + *different* body returns
  422 `idempotency.conflict`. Only 2xx responses are cached (so a
  transient 401/5xx doesn't pin a failure), and responses larger
  than 256 KB skip caching to avoid Redis bloat. Login / refresh /
  logout and multipart uploads are skipped — they have their own
  semantics. Redis being down fails open with a warning log; refusing
  the request because the cache is unreachable would be its own
  outage. Covered by `tests/test_idempotency.py` (6 tests: replay,
  conflict, no-key passthrough, GET ignored, 4xx not cached,
  oversized key rejected).

### Security (iteration 57)
- **Origin-header CSRF guard for cookie-auth mutations.** SameSite=strict
  on our auth cookies already blocks the textbook browser CSRF case,
  but the gap is narrow rather than zero: a same-site origin compromise
  (subdomain takeover), an older browser without modern SameSite
  support, or a future cookie-policy regression. New
  `CSRFOriginMiddleware` requires every mutating method (POST/PUT/
  PATCH/DELETE) carrying an auth *cookie* to also carry an `Origin`
  (or fall back to `Referer`) matching one of the configured
  `CORS_ORIGINS`. Bearer-token requests skip the check — they can't
  be CSRF'd because the attacker can't set `Authorization`
  cross-origin without explicit user action; the gate intentionally
  prefers Bearer when both are present. Rejected requests return
  `403 csrf.bad_origin`. Covered by `tests/test_csrf_origin.py` (6
  tests: missing/untrusted/trusted Origin, Bearer-skip, GET-not-checked,
  Referer fallback).

### Security (iteration 56) — BREAKING (upload contract)
- **S3 upload size cap is now enforced by S3, not the client.** The
  presign endpoint switched from `generate_presigned_url(PUT)` to
  `generate_presigned_post` with a `["content-length-range", 1, max]`
  policy condition. Before this change `size_bytes` in the presign
  request was advisory — the server's per-kind cap was checked against
  the client-claimed size, then a PUT URL was returned that S3 would
  accept any size of upload against. A malicious or buggy client
  could PUT a 1GB blob into a 5MB avatar slot. Now S3 verifies the
  policy against the actual upload and rejects oversize at the source.
  **Contract change:** the presign response shape went from
  `{url, headers, ...}` (PUT-with-headers) to `{url, fields, max_bytes, ...}`
  (POST-with-form-fields). Frontend updated; external API consumers
  that hit `/api/v1/uploads/sign` directly need to switch to multipart
  POST with the returned `fields` plus a final `file` form field.
  Covered by `tests/test_uploads_size_enforcement.py` (4 tests:
  method/fields contract, per-kind max_bytes matrix, pre-flight
  too-large still 422s, old `headers` key explicitly absent).

### Added (iteration 55)
- **Mark-all-read for notifications.** Previously a learner with N
  unread notifications had to issue N round trips to clear the badge.
  New `POST /me/notifications/read-all` does it in a single UPDATE,
  returns the count touched so the UI updates without a follow-up
  GET, and is strictly scoped to the calling user. The bell dropdown
  now shows a "Mark all read" link when there's an unread count.
  Covered by `tests/test_notifications_read_all.py` (3 tests:
  scoped to caller, idempotent, auth required).

### Added (iteration 54)
- **Cursor pagination on the admin audit log.** CLAUDE.md specifies
  "cursor for messages/audit" but the endpoint only supported `limit`
  — capping at 500 events made anything older invisible. Added
  `?before=<event_id>` (matches the `chat.history` pattern) returning
  events strictly older than the named anchor. Response shape stays
  `list[AuditEventOut]` so the existing frontend call without the
  cursor continues to work. The admin audit page now offers a "Load
  older events" button that walks back by passing the oldest currently-
  displayed event id. Unknown / stale anchor ids degrade gracefully
  to "no filter" rather than 404, so a deleted-event race doesn't
  blow up the pager UI. Covered by `tests/test_audit_cursor.py` (4
  tests: cursor returns strictly older + skips anchor itself, unknown
  cursor falls through, admin-only gate intact, response shape
  unchanged).

### Security (iteration 53)
- **Rate-limit the two heavy authenticated write endpoints.**
  Before iter 53 only the auth surface had explicit limits. Quiz
  submit (`POST /me/progress/lessons/{id}/quiz`) and chat post
  (`POST /chat/courses/{id}/messages`) were both DOS-able by any
  authenticated learner — the quiz path runs a full grader pass
  and writes `LessonProgress` plus a potential cert; chat fans
  out via Redis pub/sub to every WS subscriber. Added
  `@limiter.limit("20/minute")` to quiz and `@limiter.limit("30/minute")`
  to chat. Covered by `tests/test_rate_limit_writes.py` (3 tests:
  quiz drains to 429, chat drains to 429, fresh-bucket isolation
  between tests).

### Security (iteration 52)
- **Optional HIBP breach-list check on every password-set path.**
  Iter 39's docstring flagged "HIBP / breach-list lookup is future
  work" — now wired via k-anonymity (only the first 5 chars of the
  password's SHA-1 leave the process; the full hash and the password
  itself never do). Applied to register, password-reset confirm, and
  change-password — all three share the new `assert_not_pwned` helper
  so the policy is enforced uniformly. Gated behind `HIBP_ENABLED`
  (off by default) to avoid surprising third-party callouts in dev /
  CI / air-gapped deployments. Fails *open* on timeout or 5xx — a
  HIBP outage cannot lock users out of registration. Pads / count=0
  padding rows are explicitly ignored to prevent false-positive
  "breached" verdicts. Covered by `tests/test_password_hibp.py` (12
  tests: k-anonymity contract verification, padding-row handling,
  fail-open on timeout + 5xx, plus end-to-end rejection through all
  three endpoints and the happy-path-when-disabled regression).

### Security (iteration 51)
- **Defense-in-depth security headers on every API response.** Added
  `SecurityHeadersMiddleware` setting `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`,
  and a restrictive `Permissions-Policy` (camera/mic/geo/payment/usb
  all blocked — the API origin never needs them). Production also
  gets a 2-year HSTS with `includeSubDomains; preload`. Caddy in
  front already sets some of these in prod, but defense in depth
  keeps the API safe behind any future direct-exposure mistake.
  Covered by `tests/test_security_headers.py` (5 tests: headers
  present on public, auth-gated, error, and Swagger UI HTML responses;
  HSTS absent in non-prod to avoid poisoning developer browsers).

### Fixed (iteration 50)
- **Slug-collision retry now covers course rename.** Iter 49's
  `_flush_course_with_slug_retry` shielded `create_course` and
  `duplicate_course`, but `update_course` mutated `course.slug` on
  title change and never flushed — the IntegrityError surfaced on
  the dependency-override commit at request end, an unhandled
  exception → 500. Now `update_course` calls the same helper when
  the title actually changed (no flush overhead when only other
  fields move). Test added to `test_slug_race.py` (PATCH rename
  into a pre-claimed slug still returns 200 with a disambiguated
  `renamed-course-…`).

### Fixed (iteration 49)
- **Concurrent course creation no longer 500s on slug collision.**
  `_unique_slug` ran a non-locking SELECT and returned the first
  unclaimed candidate. Two concurrent creates with the same title
  both saw `awesome-course` free, both INSERTed, and the second
  crashed on `UNIQUE(courses.slug)` → unhandled IntegrityError → 500.
  Introduced `_flush_course_with_slug_retry`: wraps the INSERT in a
  SAVEPOINT (so the outer request transaction stays clean), catches
  the slug-specific IntegrityError, regenerates with a short random
  suffix, and retries. Three attempts is plenty for any plausible
  concurrency; past that, a clean 409 `course.slug_race`. Applied to
  both `create_course` and `duplicate_course`. Covered by
  `tests/test_slug_race.py` (3 tests: pre-claimed obvious slug,
  obvious + first numeric fallback also claimed, and the same path
  exercised through duplicate).

### Fixed (iteration 48)
- **Studio publish button surfaces server errors.** The publish
  mutation in `/studio/[id]` had only an `onSuccess` handler; the
  TanStack mutation silently swallowed any rejection. So the iter
  43 `course.no_lessons` guard (and the older `course.missing_fields`
  / `course.invalid_transition` cases) produced *no* feedback — the
  instructor clicked Publish on an empty course and saw exactly
  nothing, with no way to tell the click had even registered. Added
  a typed `onError` that maps the three known rejection codes to
  helpful messages and falls back to the server's message otherwise.

### Security (iteration 47)
- **Bookmark endpoint respects course visibility.** `add_bookmark`
  loaded the course via `courses_repo.get_course` (filters only
  `deleted_at`), so a user who knew or guessed a draft/archived
  course id could PUT `/me/bookmarks/{id}` and then read the
  bookmark listing to see title/overview/owner/subject/tags — every
  field the catalog hides from non-owners. Same shape as the
  duplicate-course leak fixed in iter 46. Now `can_view_course`
  runs at both bookmark-add and list time; non-owner attempts on a
  private course return 404 (matching detail/duplicate posture).
  Existing bookmarks pointing at a course that has since gone
  back to draft are silently filtered from the listing rather than
  ghost-leaking when visibility flips. Covered by
  `tests/test_bookmark_visibility.py` (5 tests: draft + archived
  rejected for strangers, listing hides post-flip-to-draft, owner
  can bookmark own draft, enrolled learner can bookmark archived).

### Security (iteration 46)
- **`duplicate_course` no longer exposes other instructors' drafts.**
  The docstring claimed *"instructors can copy any **published**
  course to remix it"* but the code loaded the source via
  `courses_repo.get_course` (filters only `deleted_at`), so an
  instructor who knew or guessed a draft's id could duplicate
  another author's unreleased material into their own account —
  every module and lesson. Catalog / detail / search all already
  hide non-published courses from non-owners; duplicate now matches:
  published is duplicable by any instructor, drafts and archived
  are duplicable only by the owner or an admin. Non-owner attempts
  return 404 (not 403) so we don't confirm existence to a caller
  who shouldn't see it. Covered by
  `tests/test_duplicate_visibility.py` (5 tests: other-instructor
  blocked on draft + on archived, owner can dupe own draft, admin
  can dupe anyone, and the original published-source happy path
  still works).

### Fixed (iteration 45)
- **Cert PDF download survives course soft-delete.**
  `download_certificate` loaded the course via
  `courses_repo.get_course`, which filters `deleted_at IS NULL`. So
  once an instructor (or admin) soft-deleted the course, every
  learner who'd earned the cert got a 404 trying to download their
  PDF — a permanent achievement record held hostage by an unrelated
  content-curation decision. The public `verify_certificate`
  endpoint already takes the right posture (no `deleted_at` filter
  on the join), and iter 44 stopped the *learner* from breaking
  their own cert via unenroll. This iteration closes the matching
  server-side path: the PDF endpoint uses `db.get(Course, id)`
  directly so soft-delete doesn't void earned credentials. Covered
  by `tests/test_cert_pdf_survives_delete.py` (2 tests: end-to-end
  earn → soft-delete → still downloadable + verifiable; plus the
  guard-ordering sanity check that an unknown course_id still
  reports `cert.not_enrolled` rather than masking it as 404).

### Fixed (iteration 44)
- **Block unenroll on a completed enrollment.** `DELETE
  /api/v1/me/enrollments/{course_id}` issued a hard
  `db.delete(enrollment)` regardless of completion state. The
  Enrollment row owns the learner's `certificate_id` and (FK
  `ondelete=CASCADE`) all their `lesson_progress` rows, so a single
  DELETE silently invalidated the certificate (`/verify/{cert_id}`
  → 404), threw away every completion timestamp, and lost the quiz
  scores stored on `lesson_progress.payload`. No frontend surface
  currently exposes unenroll, but the API client does — one rogue
  call destroys an achievement record permanently. Refuse with 409
  `enrollment.completed` once the cert has been issued; mid-progress
  unenroll still works as before. Covered by
  `tests/test_unenroll_after_complete.py` (3 tests: refused after
  completion + cert still verifies, mid-progress still allowed,
  unenroll-when-never-enrolled remains an idempotent 200).

### Fixed (iteration 43)
- **Block publishing a course with zero live lessons.**
  `_transition_status` checked only `title` and `overview` before
  letting `draft → published` through. So an instructor could fill in
  two fields, click publish, and push an empty shell into the catalog.
  Students who enrolled landed on a blank syllabus, progress stuck at
  0% forever, with no signal that the author hadn't finished. Now the
  publish path counts live (non-soft-deleted) lessons across the
  course and raises 422 `course.no_lessons` if there are none — same
  rule applies after-the-fact (soft-deleting the last lesson and
  trying to re-publish from draft is rejected). Covered by
  `tests/test_publish_minimum_content.py` (4 tests). Added a
  reusable `seed_lesson` conftest fixture and retrofitted 11 legacy
  tests that had been publishing empty courses as test scaffolding.

### Fixed (iteration 42)
- **`DELETE /admin/tags/{id}` now refuses when the tag is in use.**
  The endpoint issued a raw `db.delete(tag)`; `course_tags.tag_id`
  has `ON DELETE CASCADE`, so the operation silently stripped the
  tag from every course that referenced it — no warning to the
  admin, no audit-friendly trail of what got detached. Brought it
  into line with `delete_subject` (hardened in iter 28): refuse
  with a 409 `tag.in_use` (carrying the count of attached live
  courses) so the admin can clean up first. Soft-deleted courses
  don't block the delete (their join rows cascade quietly with no
  visible impact). Covered by `tests/test_admin_tag_delete.py`
  (5 tests: live-attached refusal, soft-deleted-doesn't-block,
  unused-succeeds, 404, and instructor-can't-call).

### Fixed (iteration 41)
- **Module / lesson reorder rejects partial and malformed mappings.**
  Both reorder paths set every row's `order` to a negative temp value
  (to dodge the `(parent, order)` unique constraint), then assigned
  new orders only to the rows the caller named. A *partial* mapping
  left the unnamed rows stuck at `-1, -2, -3, ...` permanently — and
  since SQL ORDER BY puts negatives first, the syllabus silently
  hoisted them to the top on next render. The official client always
  sends the full ordering, but a buggy mobile build, a network replay,
  or an authenticated bad actor could trigger the bug. We now require
  the mapping to cover every existing id exactly once, reject negative
  or duplicate target values up front (explicit 422 instead of an
  eventual unique-constraint 5xx), and — for lessons — park soft-
  deleted rows just past the live range so they can't collide with a
  new target value either. Covered by
  `tests/test_reorder_completeness.py` (6 tests: partial / negative /
  duplicate / full mappings for modules, plus soft-deleted-skip and
  partial-lesson rejection at the service layer).

### Fixed (iteration 40)
- **Blocked self-reviews on owned courses.** Instructors can enroll in
  their own published course (handy for previewing what learners see)
  but could then post a 5-star review of themselves, padding
  `avg_rating` and the catalog's "top-rated" sort. The notification
  path already had `if course.owner_id != author.id` — the codebase
  knew the scenario but didn't reject it. `reviews.upsert` now
  raises `review.self_review` for the owner, and the frontend hides
  the review editor when viewer owns the course so we don't show a
  button that always 403s. Covered by `tests/test_self_review.py`
  (3 tests: PUT + PATCH rejection, avg_rating staying honest after
  a rejected owner attempt, peer-instructor still allowed to review).

### Security (iteration 39)
- **Unified password strength policy across register / reset / change.**
  Only `RegisterRequest` ran the "mix character classes" check; the
  reset-confirm and change-password endpoints enforced just
  `min_length=12`. So a user who registered with `Password!1234` could
  downgrade to `password12345` via either flow — bypassing the policy
  they agreed to at signup, and giving anyone with a reset token (or
  the user's current session) an easier offline-cracking target.
  Extracted `validate_password_strength` into `app.schemas.auth` and
  wired it to all three sites. Covered by
  `tests/test_password_policy.py` (8 tests: parameterised
  validator accept/reject, schema-level checks on both reset and
  register, end-to-end rejection at reset and change endpoints, plus
  a happy-path change-password to verify the tightening didn't break
  the normal flow).

### Security (iteration 38)
- **Removed the `"*"` content-type wildcard for attachment uploads.**
  The `attachment` kind's allow-list was `{"*"}` — any authenticated
  user could PUT `text/html` / `image/svg+xml` / `application/javascript`
  to the public bucket via a presigned URL, and S3 served those blobs
  inline with the requested Content-Type. Because the bucket sits on
  the platform's own DNS, that turned the upload endpoint into a
  hosted-XSS/phishing surface. Replaced with an enumerated set of
  doc/archive/media/code types learners actually attach. Added
  `ALWAYS_DENIED_TYPES` — applied before every per-kind check — as
  defense-in-depth so any future kind cannot re-open the same hole
  for HTML, SVG, or JavaScript. Covered by
  `tests/test_uploads_content_type_safety.py` (7 tests: structural
  invariants on the allow-list, parameterised rejection of every
  classic XSS carrier, plus the happy path for an attachment PDF).

### Fixed (iteration 37)
- **Password-reset and email-verify links pointed at the API host.**
  Both link builders used `settings.api_base_url` (FastAPI, port 8000
  dev, typically `api.example.com` prod) but the actual reset and
  verification pages are Next.js routes that only exist on the user-
  facing web host (`example.com`). Anyone clicking the link in their
  inbox in prod landed on a 404. Introduced `WEB_BASE_URL` (default
  `http://localhost:3000`) and routed both emails through it; the
  prod-readiness guard now refuses to boot if it's still the dev
  default, mirroring the existing `cors_origins` check. Covered by
  `tests/test_email_link_host.py` (4 tests: prod guard accept/reject,
  reset link host, verify link host).

### Security (iteration 36)
- **Chat WebSocket re-authorises on every post.** The connection
  validated the user and enrollment once at connect, then cached both in
  local variables for the lifetime of the socket. So deactivating an
  account, unenrolling a learner, or unpublishing a course only took
  effect when the socket finally dropped — until then the offender kept
  publishing messages from the stale connect-time session. The message
  branch now reloads the user (`users_repo.get_by_id`) and re-runs
  `ensure_can_chat`; failure sends a typed error frame and closes the
  socket (4401/4403/4404). Typing pings still flow without the recheck
  to keep that path cheap. Covered by `tests/test_chat_ws_revalidate.py`
  — three tests that exercise the underlying primitives the WS now
  depends on (no WS test harness in this repo, so the loop wrapper
  itself is 5 lines on top of well-tested service calls).

### Fixed (iteration 35)
- **Quiz editor stopped reusing question ids after a delete.** The
  `addQ()` helper in the lesson editor minted ids as
  `q${questions.length + 1}`, so deleting the first question and adding
  a new one produced `q1` again — colliding with the next question and
  silently making both share answer keys / grade slots. The helper now
  scans for the lowest unused id. As defense-in-depth on the wire,
  `QuizLessonData` gained a `_unique_question_ids` validator so any
  client (the buggy editor, a mobile app, an import script) sending
  duplicates gets a 422 instead of a corrupt quiz. Covered by
  `tests/test_quiz_question_unique_ids.py`.
- **/learn now resumes at the first incomplete lesson.** The outline
  always defaulted to lesson 1, so a learner 7-of-10 lessons in saw
  lesson 1 selected every time and had to hunt for where they left off.
  Defaults to the first lesson with `completed: false`, falling back to
  lesson 1 only when the course is fully done.

### Added (iteration 34)
- `LessonOut.completed` (per-viewer) on the course-detail endpoint. The
  syllabus on the course page and the lesson outline in `/learn` now show
  a green check next to each lesson the learner has finished, plus a
  strikethrough title style. Anonymous and non-enrolled viewers always
  see `completed: false`. Backed by `repositories.courses.completed_lesson_ids`
  which excludes soft-deleted lessons so the marks line up with what's
  actually in the syllabus. Three regression tests in
  `test_lesson_completion_flag.py` cover the per-viewer flag flip,
  per-viewer isolation, and the anon / non-enrolled fallback.

### Fixed (iteration 33)
- **Certificate PDF's verify URL now points at the real public page.**
  The rendered PDF embedded `verify at /certificates/<id>` — a route
  that doesn't exist; the public verification page lives at
  `/verify/<id>`. Anyone who downloaded a certificate and typed the
  printed URL landed on a 404. Centralised the path in a module
  constant (`VERIFY_PATH = "/verify"`) and updated the rendered
  string. Two regression tests in `test_certificate_pdf.py` lock in
  the new URL and the single-source-of-truth constant.

### Security (iteration 32)
- **Closed the login enumeration timing side-channel.** The authenticate
  path skipped Argon2 verification when the email lookup returned None,
  so a "no such email" response came back roughly an order of magnitude
  faster than a "wrong password" response — a wire-observable oracle
  for which emails are registered. We now run `verify_password` against
  a precomputed dummy hash on the missing-user path, so both branches
  do the same dominant CPU work. `tests/test_login_timing.py` asserts
  the two latencies stay within 3× of each other. Documented in
  `docs/security.md`.

### Fixed (iteration 31)
- **Chat presence no longer drops active senders after 60 seconds.**
  `mark_present` ran once on WebSocket connect; `list_present` filters
  by a 60-second freshness window, so a user who stayed connected and
  kept sending messages fell off the presence list after one minute.
  The WS handler now refreshes the presence sorted-set score on every
  inbound frame — active users stay listed, idle users still expire
  naturally. A `_FakeRedis` test double exercises the
  refresh / absence / stale-cutoff behaviour without standing up a
  real Redis or WebSocket.

### Fixed (iteration 30)
- **Catalog subject tiles stop counting soft-deleted courses.**
  `list_subjects` outer-joined Course with `status == published` only,
  so a course soft-deleted by an instructor still kept inflating the
  badge on the subject tile (the catalog grid shows fewer rows than
  the badge claimed). Outer-join condition now also requires
  `Course.deleted_at IS NULL`. Two regression tests in
  `test_subjects_total.py` cover the soft-delete drop and the
  draft / archived exclusion.

### Fixed (iteration 29)
- **Catalog `?sort=` no longer crashes on unknown / non-column values.**
  `search_courses` resolved the sort field with
  `getattr(Course, name, Course.created_at)`. Crafted values like
  `sort=modules` (relationship), `sort=metadata` (SQLAlchemy
  bookkeeping), or `sort=__class__` returned attributes whose
  `.desc()` raised `AttributeError` and surfaced as a 500. Replaced
  with an explicit allow-list (`created_at`, `published_at`, `title`,
  `is_featured`); unknown values quietly fall back to `created_at`.
  Three regression tests in `test_catalog_sort.py`.

### Fixed (iteration 28)
- **Admin subject deletion no longer 500s when courses are attached.**
  `DELETE /api/v1/admin/subjects/{id}` issued an unconditional DELETE
  and let `Course.subject_id FK ondelete=RESTRICT` crash into the
  unhandled-exception path. The endpoint now pre-counts referencing
  courses (live + soft-deleted, because the FK ignores `deleted_at`)
  and refuses with a clean 409 `subject.in_use` carrying both counts
  in `details`. Four regression tests in `test_admin_subject_delete.py`
  cover the live-course block, the soft-deleted-course block, the
  no-courses success path, and unknown-id 404.

### Fixed (iteration 27)
- **Progress writes against a soft-deleted lesson now 404 cleanly.**
  `POST /me/progress/lessons/{id}` and the quiz submission both routed
  through `courses_repo.get_lesson`, which doesn't filter `deleted_at`.
  An enrolled learner holding a stale lesson id (cached SPA state,
  request replay, etc.) could persist a `LessonProgress` row pointing
  at a removed lesson — the row didn't count toward progress (the count
  query is already filtered, iteration 22) but it cluttered the DB and
  returned a misleading 200. Both endpoints now reject deleted lessons
  with `lesson.not_found`. Two regression tests in
  `test_deleted_lesson_writes.py`.

### Fixed (iteration 26)
- **The learner dashboard no longer renders enrollments to soft-deleted
  courses.** `list_enrollments_for_user` returned every row regardless of
  `Course.deleted_at`, so the "in progress" card linked to a course
  whose detail page 404'd. Repo now joins `Course` and filters
  `deleted_at IS NULL`. Archived / draft courses still show up — only
  truly deleted ones disappear, paired with the iteration-24 fix.

### Fixed (iteration 25)
- **Course slug minting now sees through soft-deletes.** `_unique_slug`
  used `get_course_by_slug`, which hides `deleted_at IS NOT NULL` rows.
  Recreating a course with the same title as a soft-deleted one looked
  fine to the minter then crashed the INSERT against the unconditional
  `UNIQUE(courses.slug)` constraint. Added
  `repositories.courses.slug_is_taken(db, slug, exclude_id=...)` which
  reads the raw table, and switched the slug minter to use it. Three
  regression tests cover delete-then-recreate, repeated duplication, and
  rename-to-same-title.

### Fixed (iteration 24)
- **Archiving (or un-publishing) a course no longer locks out already-
  enrolled learners.** `GET /api/v1/courses/{slug}` previously routed
  visibility through `can_view_unpublished`, which returned True only
  for the course owner and admins. Existing students of a course an
  instructor then archived would start getting a 404 on the syllabus —
  losing the chat link, lesson navigation, and certificate download CTA
  they earned. Introduced `can_view_course(db, course, viewer)` which
  also accepts a current enrolment as proof of access. Anonymous and
  not-enrolled viewers still see 404 for non-published courses. Three
  regression tests in `test_archived_access.py`.

### Fixed (iteration 23)
- **Failing a quiz retake no longer un-passes a previously-passed lesson.**
  The quiz endpoint previously routed through `mark_lesson(completed=…)`,
  which cleared `LessonProgress.completed_at` on every failing attempt.
  A learner who passed and then retook out of curiosity could lose their
  completion (and the course-completion certificate that hinged on it).
  Introduced `enrollment_service.record_quiz_attempt` which always
  records the latest score but only flips `completed_at` on a passing
  attempt — and never clears it. Two regression tests in
  `test_quiz_retake.py` lock the "pass then fail-retake stays complete"
  and "fail-then-pass marks complete with the new score" paths.

### Fixed (iteration 22)
- **Progress could exceed 100% after a lesson was soft-deleted.**
  `count_completed_lessons`, the per-course `avg_progress_pct`, and the
  cohort listing all counted every `LessonProgress` row regardless of
  whether the parent lesson still existed. Soft-deleting a finished
  lesson left ``done > total``, which produced >100% progress for the
  learner and the cohort view, and risked spurious certificate issuance.
  The queries now join `Lesson` and filter on `Lesson.deleted_at IS NULL`,
  so progress always clamps to the surviving curriculum. Three
  regression tests in `test_progress_soft_delete.py` lock the fix in
  for the learner, cohort, and per-course-analytics paths.

### Added (iteration 21)
- ChatRoom test (vitest): swaps in a MockWebSocket double and asserts the
  empty/connecting state, server-pushed messages render, presence count
  updates, outbound frames are valid JSON, Send is disabled until the
  socket is OPEN, transient closes (1006) show "Reconnecting", terminal
  closes (4403) show "Disconnected", and no socket is opened when there's
  no token.

### Fixed (iteration 20)
- `/learn/[slug]` now redirects non-enrolled viewers to the course detail
  page (with a "Enroll to start learning" toast) instead of rendering a
  player whose writes the server silently rejected. Course owners and
  admins bypass the guard so they can preview their own content.

### Added (iteration 20)
- Public free-preview lessons get a real surface: a new
  `/courses/[slug]/preview/[lessonId]` page renders any `is_preview`
  lesson via the existing public endpoint, with a friendly Enroll CTA
  and clear messaging for 403 / 404 cases. The course detail syllabus
  now shows a "Sample →" link beside each preview lesson on published
  courses.
- `Courses.getLesson()` added to the typed API client.

### Fixed (iteration 19)
- Wrapped every `useSearchParams` consumer in `<Suspense>` boundaries so
  Next.js 15 can serve them without forcing full-page dynamic rendering:
  login, reset-password, verify-email, catalog (`/courses`), and the
  HeaderSearch component used on every route via the site header. Each
  boundary ships an opaque skeleton fallback that matches the final
  layout (no layout shift on hydration).

### Changed (iteration 19)
- `docs/api.md` gains a top-of-document Contents section so the ~280-line
  reference stays navigable.

### Added (iteration 18)
- Per-course OpenGraph metadata. The course detail route is split into a
  server `page.tsx` that exports `generateMetadata` and a client
  `course-detail-view.tsx`. Shares now carry the course title,
  description (first 280 chars of overview), `og:image` (cover), and a
  canonical link; 404s become a "Course not found" title.
- ImageUpload component test: file too large is rejected before the API
  is called, signs + PUTs + calls onChange with the public URL, surfaces
  an error toast on PUT failure, Remove clears the value, and the
  preview/placeholder render paths are covered.

### Added (iteration 17)
- SEO: Next.js generates `/robots.txt` (allows public routes, disallows
  auth + studio + admin + learn paths) and `/sitemap.xml` (static routes
  plus the most recent 100 published courses with `lastModified` and a
  boost for featured ones). Sitemap is fail-soft: if the API is down at
  regeneration time, only the static routes are emitted.
- CourseCard tests extended with: hides Featured badge when not featured,
  omits rating tile when `avg_rating` is null, renders the cover `<img>`
  when `cover_url` is set (with the monogram fallback when not), and
  surfaces the difficulty + subject badges.

### Changed (iteration 16)
- README "Features at a glance" rewritten as Learner / Instructor / Admin /
  Cross-cutting sections that match what actually shipped (bookmarks,
  server-graded quizzes, cohort view, sessions UI, cert verification,
  rate limiting, prod-secret guard, studio status tabs, …).
- `docs/security.md` gains a "Rate limiting" section with the per-endpoint
  thresholds and a note on `X-Forwarded-For` trust.

### Added (iteration 16)
- Frontend test for `LessonEditor`: existing-lesson seeding, patch round-
  trip (incl. `is_preview` toggle), create round-trip for a new lesson,
  delete invokes `deleteLesson` + `onDeleted`, quiz "Add question" path,
  Save disabled until a title is entered.

### Fixed (iteration 15)
- **Rate limiting was configured but never wired**. The `slowapi` limiter
  is now mounted on the FastAPI app via `SlowAPIMiddleware`, and the
  high-risk auth endpoints carry per-IP limits: `POST /auth/login` (10/min),
  `POST /auth/register` (5/min), `POST /auth/password-reset/request`
  (3/min), `POST /auth/verify/request` (3/min). 429 responses use the
  standard envelope and include `Retry-After`. Tests use an in-memory
  bucket reset via a `_reset_rate_limiter` autouse fixture.

### Added (iteration 15)
- Frontend tests: CohortCard (empty / mixed-progress / error states) and
  NotificationsBell (unread badge count, mark-on-click, empty state).

### Added (iteration 14)
- Studio courses page gains All / Drafts / Published / Archived filter
  tabs with counts so archived courses stop cluttering the live view.
- Frontend tests: SessionsCard (list render, per-row revoke, sign-out-
  everywhere, empty state) and MyReviewEditor (initial state, seeded
  existing review, save, remove, save-disabled-until-rating).

### Added (iteration 13)
- Server-side quiz grading. `POST /api/v1/me/progress/lessons/{id}/quiz`
  accepts an `{answers: {question_id: ...}}` payload, grades the quiz
  server-side via the new `app.services.quiz` module, persists the score on
  `LessonProgress.score`, marks the lesson complete on pass, and returns
  per-question correctness. The lesson player now submits to this endpoint
  and renders the server-graded result (per-question badges, pass/fail
  message tied to the actual `pass_score`).
- `GET /api/v1/admin/stats` returns platform totals (users, active users,
  instructors, courses by status, enrollments). Admin home renders a
  "Platform at a glance" tile row.

### Added (iteration 12)
- Instructor cohort view: `GET /api/v1/courses/{course_id}/students` returns
  enrolled learners with per-student progress %, completion timestamp, and
  certificate id. Rendered on the studio course page as a new "Students"
  card with status badges (completed / in progress / not started).
- Course detail badges (subject, difficulty, tags) are now Links into
  `/courses?subject=…`, `?difficulty=…`, `?tag=…` for one-click discovery.
- Catalog page now seeds `subject`, `difficulty`, and `tag` from the URL
  in addition to `q`, so deep-links from elsewhere "just work".

### Changed (iteration 12)
- `docs/security.md` refreshed to cover the post-iteration-7 auth surface:
  password change + revoke, password reset (hash-bound JWT), email verify
  (email-bound JWT, idempotent), active sessions, public certificate
  verify (no PII), and the production startup guard.

### Added (iteration 11)
- Chat WebSocket auto-reconnects with exponential backoff (1s → 30s, six
  steps) and a coloured status pill ("Reconnecting…"). Server-refused
  closes (4401/4403/4404) stop retrying. Backoff + retry logic lives in
  `lib/reconnect.ts` and is unit-tested.
- Catalog page renders tag filter chips below the row of selects; clicking
  one filters by `?tag=<slug>`, with a clear button when active.
- Register success toast now hints that a verification email is on the way.

### Changed (iteration 11)
- Catalog tag list fetched once via the existing `/tags` endpoint and
  capped at 20 chips to keep the header compact.

### Added (iteration 10)
- Header search bar (visible on md+ and inside the mobile drawer) routes to
  `/courses?q=…`; the catalog page now seeds its `q` input from the URL.
- `POST /api/v1/admin/search/reindex` (202 Accepted) queues a full catalog
  reindex via Celery; falls back to inline reindex when no broker is
  reachable. Admin home renders a "Reindex catalog" button under a Search
  index card.
- `GET /api/v1/certificates/verify/{certificate_id}` is a public endpoint
  that returns the certificate's course + display name (no PII). A new
  `/verify/[id]` Next.js page renders the result so anyone with the ID can
  confirm a certificate is real.

### Added (iteration 9)
- Active-sessions panel on `/profile` — lists each refresh-token session
  with user-agent + IP + age, per-row revoke, and a "Sign out everywhere"
  button.
- Admin `GET /api/v1/admin/courses` returns the full catalog (filterable
  by `q` and `only_featured`); `PATCH /admin/courses/{id}/feature` toggles
  the featured flag and writes an `admin.course.featured` audit row.
- New `/admin/courses` UI lists every course with status badges and a
  Feature / Unfeature button; admin home tile grid links to it.

### Changed (iteration 9)
- Hoisted the admin router's mid-block imports (selectinload, builders,
  repo, model, schema) to the top of the file for consistency with the
  rest of the codebase.

### Changed (iteration 8)
- Centralized `CourseListItem` / `CourseDetail` construction in
  `app/api/v1/_builders.py`. catalog, courses, enrollments, bookmarks, and
  search routers now share the single builder — eliminates five copies of
  the same field-by-field projection.
- Hoisted mid-file imports in `users.py`, `courses.py`, and `search.py` to
  module-level; removed unused imports along the way.
- `SessionOut` revoke endpoint now raises `NotFoundError` (was a misnamed
  `ValidationAppError`) when the session id is unknown.

### Added (iteration 8)
- Production startup hardening: `Settings.assert_production_ready()` refuses
  to boot when `env=production` if `JWT_SECRET`, `SECRET_KEY`, or
  `S3_SECRET_ACCESS_KEY` are still dev defaults, or if `CORS_ORIGINS`
  contains `localhost`. Called from the FastAPI lifespan.
- Accessibility: skip-to-content link in the root layout, `aria-current="page"`
  on active nav links (desktop and mobile drawer).

### Added (iteration 7)
- Email verification flow: register queues a verification email, `POST
  /api/v1/auth/verify/request` resends, `POST /api/v1/auth/verify/confirm`
  marks `email_verified_at`. Tokens are stateless JWTs bound to the current
  email; idempotent on replay; rejected after email change. Profile page
  shows a verified/unverified badge and a Resend button.
- `/verify-email` page handles the link landing flow.
- Lesson free-preview flag: `is_preview` on lessons; published-course
  preview lessons are fetchable anonymously via `GET
  /api/v1/courses/lessons/{lesson_id}`. Course detail tags them with a
  "free preview" badge; lesson editor exposes the toggle.
- Active sessions: `GET /api/v1/users/me/sessions`,
  `DELETE /api/v1/users/me/sessions` (sign out everywhere),
  `DELETE /api/v1/users/me/sessions/{id}` (revoke one).

### Added (iteration 6)
- `GET /api/v1/courses/{course_id}/analytics` returns per-course metrics
  (enrollments, completions, completion rate, avg rating + count, avg
  progress, new-7d and new-30d enrollments). Surfaced on the studio page.
- `POST /api/v1/courses/{course_id}/duplicate` clones a course (modules +
  lessons) as a draft owned by the caller, with a unique slug. Any instructor
  can duplicate a published course to remix it.
- `scripts/export_openapi.py` + `make openapi` / `make openapi.local` dump
  the OpenAPI schema without a running stack.

### Added (iteration 5)
- Course bookmarks: `GET/PUT/DELETE /api/v1/me/bookmarks/{course_id}`, with
  `is_bookmarked` exposed on the course detail and a Bookmarks section on the
  dashboard.
- Lesson navigation in the learner view: Previous / Next plus a
  "Mark complete & continue" combo button.

### Changed (iteration 5)
- `_owned_module` / `_owned_lesson` now raise `NotFoundError` (not
  `ForbiddenError`) when a parent record is missing — clearer error semantics.
- `docs/api.md` documents the full endpoint inventory across auth, users,
  catalog, search, courses, enrollments, reviews, chat, uploads, certificates,
  admin, bookmarks, and health.

### Added (iteration 4)
- `/api/v1/search/courses` endpoint backed by Meilisearch with an automatic
  Postgres ILIKE fallback when the search service is unavailable.
- Presigned image upload widget wired into the profile avatar and the
  new-course cover image fields.
- `MyReviewEditor` lets enrolled learners post, update, or delete their review
  inline on the course detail page.
- "Preview as student" link on the studio course page.
- Mobile navigation with hamburger toggle that collapses on route change.
- Notifications bell in the header with unread badge and click-to-read.
- Project-level `CLAUDE.md` to orient future agent sessions.

### Changed (iteration 4)
- Quiz grading extracted into `lib/quiz.ts` so the lesson player and tests
  share one implementation.
- `Courses.create` typed signature now accepts `cover_url` and `tag_ids`.
- Site header tracks active route to highlight the current section.

### Fixed (iteration 4)
- Course publish/unpublish/delete now best-effort enqueues a search reindex
  (tolerates a missing Celery broker in dev/tests).

### Foundation
- Complete rewrite from Django prototype to FastAPI + Next.js 15.
- Repository skeleton (monorepo with `apps/backend`, `apps/frontend`).
- SDLC documentation: PRD, architecture, ADRs (0001–0007), SDLC, API conventions, security model, deployment guide.
- Docker Compose for local dev and production.
- FastAPI app factory, settings, async SQLAlchemy, Alembic, structured logging, error handlers, OpenAPI.
- Domain models: User, Subject, Tag, Course, Module, Lesson (polymorphic), Enrollment, Progress, Review, ChatMessage, Notification, AuditEvent, RefreshToken, Asset.
- Auth: register, login, refresh (rotating), logout, current user, password reset stub; RBAC.
- Courses, modules, lessons CRUD with publishing, ordering, content types, instructor permissions.
- Enrollment, progress, reviews, certificates.
- Real-time chat with WebSocket + Redis pub/sub, persistence, presence.
- File uploads via presigned URLs to MinIO.
- Search via Meilisearch (with Postgres fallback).
- Next.js 15 frontend foundation: App Router, Tailwind 4, shadcn/ui, TanStack Query, generated API client.
- Frontend pages: landing, auth, catalog, course detail, learner dashboard, instructor studio, chat UI, profile.
- Test stacks: pytest + httpx + factory-boy for backend; vitest + Playwright for frontend.
- GitHub Actions CI/CD: lint, type-check, test, build, scan, push images, deploy stage on `main`, tag-driven prod.
- Observability: structlog JSON logs, OpenTelemetry, Prometheus metrics endpoint.
- Pre-commit hooks: ruff, eslint, prettier, gitleaks, conventional-commits check.

### Changed
- Original Django project archived to `legacy/`.

### Security
- Argon2id password hashing.
- Refresh-token rotation with reuse detection.
- CSP, HSTS, secure cookie defaults.
- Rate limiting on auth and chat endpoints.
