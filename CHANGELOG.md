# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
