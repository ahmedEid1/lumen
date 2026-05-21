# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
