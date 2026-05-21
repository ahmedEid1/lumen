# Lumen — E-Learning Platform

> A modern, full-stack learning management system rebuilt in 2026 from the original Django prototype.

[![CI](https://github.com/ahmedEid1/E-Learning-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/ahmedEid1/E-Learning-Platform/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Lumen is the second-generation rewrite of the original `E-Learning-Platform` Django app. It pairs a **FastAPI** backend with a **Next.js 15** frontend, runs entirely from Docker Compose, and ships with a complete SDLC: planning docs, ADRs, automated tests, CI/CD, observability, and a production deployment story.

---

## Highlights

| Area | Stack |
|------|-------|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, Celery |
| Frontend | Next.js 15 (App Router), React 19, TypeScript 5, Tailwind 4, shadcn/ui, TanStack Query |
| Data | PostgreSQL 17, Redis 7, MinIO (S3-compatible), Meilisearch |
| Auth | JWT access + rotating refresh, Argon2 hashing, OAuth2-ready, RBAC |
| Realtime | WebSockets fan-out via Redis Pub/Sub |
| Quality | Ruff, mypy, ESLint, Prettier, pytest, Vitest, Playwright, pre-commit |
| Delivery | Docker, Docker Compose (dev & prod), GitHub Actions, Trivy scans, Renovate |
| Ops | OpenTelemetry, Prometheus metrics, structured logs, audit trail |

---

## Repository layout

```text
.
├── apps/
│   ├── backend/                FastAPI service (Python 3.13)
│   └── frontend/               Next.js 15 app (TypeScript)
├── docs/
│   ├── adr/                    Architecture Decision Records
│   ├── architecture.md         System architecture & data flow
│   ├── product-requirements.md Product Requirements Document
│   ├── sdlc.md                 SDLC, branching, release process
│   ├── api.md                  API conventions
│   ├── deployment.md           Production deployment guide
│   ├── security.md             Threat model & security controls
│   └── runbooks/               On-call runbooks
├── infra/
│   ├── compose/                Compose profiles & extras
│   ├── caddy/                  Reverse proxy config
│   └── postgres/               DB init scripts
├── scripts/                    Dev tooling
├── .github/workflows/          CI/CD pipelines
├── docker-compose.yml          Local dev stack
├── docker-compose.prod.yml     Production stack
├── Makefile                    Common commands
├── legacy/                     Original Django app (read-only archive)
└── README.md
```

## Quick start (local dev)

Prerequisites: **Docker Desktop ≥ 4.30** (or Docker Engine 27 + Compose v2), **Make** (optional), 8 GB free RAM.

```bash
git clone https://github.com/ahmedEid1/E-Learning-Platform.git
cd E-Learning-Platform
cp .env.example .env
make up          # or: docker compose up --build
```

Then open:

| Service        | URL                        |
|----------------|----------------------------|
| Frontend       | http://localhost:3000      |
| Backend (API)  | http://localhost:8000      |
| API docs       | http://localhost:8000/docs |
| MinIO console  | http://localhost:9001      |
| Mailpit        | http://localhost:8025      |
| Traefik dash   | http://localhost:8080      |

Seed data and a demo instructor/student are loaded by the `seed` profile:

```bash
make seed
```

Default credentials after seeding (change immediately in any non-local env):

| Role       | Email                | Password    |
|------------|----------------------|-------------|
| Admin      | admin@lumen.test     | Admin!2026  |
| Instructor | teacher@lumen.test   | Teach!2026  |
| Student    | student@lumen.test   | Learn!2026  |

## Make targets

```bash
make up          # start the full dev stack
make down        # stop & remove containers
make logs        # tail all logs
make seed        # load demo data
make migrate     # alembic upgrade head
make revision m="add foo"   # alembic autogenerate
make test        # full test suite (backend + frontend)
make lint        # ruff, mypy, eslint
make fmt         # ruff format, prettier
make shell.api   # exec bash in backend container
make shell.db    # psql
make gif         # rebuild README gifs from Playwright traces
```

## Documentation

Start with **[docs/product-requirements.md](docs/product-requirements.md)** for the product vision, then read:

1. [Architecture overview](docs/architecture.md)
2. [SDLC & process](docs/sdlc.md)
3. [API conventions](docs/api.md)
4. [Security model](docs/security.md)
5. [Deployment](docs/deployment.md)
6. [Contributing](CONTRIBUTING.md)
7. [ADRs](docs/adr/) — every load-bearing decision

## Features at a glance

### Learners
- **Catalog** — searchable courses with subject, tag, and difficulty filters; clickable taxonomy chips
- **Enrollment & progress** — granular per-lesson completion, course-level %, prev/next navigation
- **Quizzes** — multi-choice and short-answer, **server-graded** with persisted scores
- **Bookmarks** — favourite courses; surfaced on the learner dashboard
- **Reviews & ratings** — write/update/delete a 1–5 star review inline; one per enrolled course
- **Free preview lessons** — instructors can mark lessons as free; visible without enrolment
- **Real-time chat** — per-course room with persistence, presence, **auto-reconnect with backoff**
- **Notifications** — in-app bell with unread badge, email on enrol / certificate / review received
- **Certificates** — auto-issued PDF on 100% completion plus a **public verification page** (no PII)

### Instructors
- **Studio** — courses filtered by status (All / Drafts / Published / Archived)
- **Drag & drop ordering** — modules and lessons reorder live via dnd-kit
- **Authoring** — text / video / image / file / quiz lessons with type-specific editors
- **Course duplication** — fork any course into a personal draft
- **Per-course analytics** — enrolments, completion rate, avg rating, new-7d / new-30d
- **Cohort view** — see every enrolled student's progress %, status, and certificate id
- **Preview as student** — one-click preview of a draft using the public course detail page

### Admins
- **Subjects, tags, users, courses, audit log** — full CRUD where it makes sense
- **Featured courses** — toggle the featured flag with an audit trail
- **Platform stats** — at-a-glance totals (users, instructors, courses by status, enrolments)
- **Manual search reindex** — queue a full Meilisearch reindex

### Cross-cutting
- **Account control** — email verification, password change/reset, active-sessions UI with per-row revoke
- **Search** — Meilisearch when configured, automatic Postgres ILIKE fallback if it's down
- **Rate limiting** — slowapi-backed per-IP limits on login / register / password-reset / verify
- **Audit log** — append-only record of admin actions
- **GDPR** — account export & delete (scrambles PII, revokes refresh tokens)
- **Accessibility** — skip-to-content link, aria-current on nav, keyboard nav, prefers-reduced-motion
- **Dark mode** — system / light / dark
- **i18n-ready** — first-class EN; the data model accommodates more languages
- **Production hardening** — refuses to boot with default secrets or localhost CORS

## License

MIT — see [LICENSE](LICENSE).
