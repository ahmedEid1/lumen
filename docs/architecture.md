# Architecture

## 1. Topology

```
                          ┌──────────────────────────────────┐
                          │            Browser               │
                          │   Next.js 15 (SSR + RSC + CSR)   │
                          └─────────────┬────────────────────┘
                                        │ HTTPS
                                        ▼
                              ┌──────────────────┐
                              │   Caddy / TLS    │  (reverse proxy)
                              └──┬────────────┬──┘
                                 │            │
                       /api/*    │            │  /*
                                 ▼            ▼
                ┌──────────────────────┐ ┌──────────────────┐
                │     FastAPI          │ │   Next.js node   │
                │  (uvicorn workers)   │ │   (standalone)   │
                └─┬─────┬────────┬─────┘ └──────────────────┘
                  │     │        │
        async SQL │     │ pubsub │ presigned PUT/GET
                  ▼     ▼        ▼
            ┌─────────┐┌─────┐┌────────┐
            │ Postgres││Redis││ MinIO  │
            │   17    ││  7  ││   S3   │
            └─────────┘└─────┘└────────┘
                  ▲
        FT search │
                  ▼
              ┌───────────┐
              │ Meili 1.x │
              └───────────┘

Background:                           Email:
  Celery worker ───►  Redis  ◄───►   Mailpit (dev) / SMTP (prod)
  Celery beat
```

## 2. Services

| Service       | Image / runtime               | Responsibilities |
|---------------|------------------------------|------------------|
| `web`         | `node:22-alpine` → custom    | Next.js 15 SSR/RSC + static |
| `api`         | `python:3.13-slim` → custom  | FastAPI HTTP + WebSocket |
| `worker`      | same as `api`                | Celery worker (uploads, emails, indexing, certs) |
| `beat`        | same as `api`                | Celery beat scheduler |
| `db`          | `postgres:17-alpine`         | Primary datastore |
| `redis`       | `redis:7-alpine`             | Cache, broker, pub/sub |
| `s3`          | `minio/minio`                | Object storage (lessons, avatars) |
| `mail`        | `axllent/mailpit`            | Dev SMTP UI |
| `proxy`       | `caddy:2-alpine`             | TLS termination + routing |
| `prom`        | `prom/prometheus`            | (prod profile) metrics scrape |

## 3. Request lifecycle

1. Caddy terminates TLS, forwards `/api/*` to FastAPI and everything else to Next.js.
2. Next.js renders RSC; protected routes call FastAPI with the access token from a same-site cookie via a thin server-side fetcher.
3. FastAPI validates the JWT, looks up the user, applies RBAC at the dependency layer.
4. Handlers call into the service layer; services call repositories; repositories use async SQLAlchemy sessions.
5. WebSocket connections at `/api/ws/chat/{course_id}` fan out via Redis pub/sub so multiple `api` replicas stay coherent.
6. Long-running jobs (image resize, video probe, email, certificate render, search index) enqueue to Celery via Redis.

## 4. Module layout — backend

```
apps/backend/app/
├── main.py                # app factory + uvicorn entry
├── core/
│   ├── config.py          # Pydantic settings
│   ├── logging.py         # structlog setup
│   ├── security.py        # password hashing + JWT
│   ├── errors.py          # exception hierarchy + handlers
│   └── otel.py            # OpenTelemetry init
├── db/
│   ├── base.py            # async engine, sessionmaker, Base
│   └── session.py         # FastAPI Depends provider
├── models/                # SQLAlchemy ORM models
├── schemas/               # Pydantic v2 DTOs
├── repositories/          # data access; no HTTP concerns
├── services/              # business logic; orchestrates repos
├── api/
│   ├── deps.py            # common dependencies (user, perms)
│   ├── router.py          # versioned root router
│   └── v1/
│       ├── auth.py
│       ├── users.py
│       ├── subjects.py
│       ├── tags.py
│       ├── courses.py
│       ├── modules.py
│       ├── lessons.py
│       ├── enrollments.py
│       ├── reviews.py
│       ├── chat.py        # WebSocket
│       ├── uploads.py
│       └── health.py
├── workers/
│   ├── celery_app.py
│   └── tasks/
│       ├── email.py
│       ├── media.py
│       ├── search.py
│       └── certificates.py
└── utils/
```

The **service layer** is the only place business invariants live; **handlers** are thin (parse, call service, serialize); **repositories** know nothing about HTTP.

## 5. Module layout — frontend

```
apps/frontend/src/
├── app/                   # Next.js App Router
│   ├── (marketing)/
│   ├── (auth)/
│   ├── (learn)/
│   ├── (studio)/
│   ├── api/health/        # liveness for proxy
│   └── layout.tsx
├── components/
│   ├── ui/                # shadcn primitives
│   ├── course/
│   ├── lesson/
│   ├── chat/
│   └── shared/
├── features/              # feature-grouped hooks + components
│   ├── auth/
│   ├── catalog/
│   ├── enrollment/
│   ├── studio/
│   └── chat/
├── lib/
│   ├── api/               # generated client
│   ├── auth/              # session cookie + server helpers
│   ├── query/             # TanStack Query client + key factories
│   └── utils/
├── styles/
└── tests/
```

## 6. Data model (summary)

```
Subject 1──* Course *──* Tag
            │
            │1
            ▼*
          Module 1──* Lesson
                          │1
                          ▼1
                Lesson{Text|Video|Image|File|Quiz}

User *──* Course   (Enrollment with progress)
User 1──* Review   (ratings)
User 1──* ChatMessage (per Course room)
User 1──* AuditEvent
User 1──* Notification
```

Concrete columns and indexes are documented inline in `apps/backend/app/models/`.

## 7. Authentication

- **Access token** — JWT, HS256, 15 min TTL. Stored in memory by the SPA; mirrored to a `__Host-access` cookie (`SameSite=Strict`, `Secure`, `HttpOnly`) for SSR fetches.
- **Refresh token** — opaque 32-byte random, stored hashed in `auth_refresh_tokens`, sent as `__Host-refresh` cookie. Rotated on every use; reuse invalidates the chain.
- **Password hashing** — Argon2id via `passlib`.
- **Rate limiting** — `slowapi` on `auth.*` and `chat.*`.

See [adr/0004-auth-jwt-rotating-refresh.md](adr/0004-auth-jwt-rotating-refresh.md).

## 8. File storage

Uploads use presigned PUTs straight to MinIO, then the client posts the resulting key back to the API. The API verifies the key exists, then stores the object in `assets`. A Celery task generates derivatives (image variants, video probe metadata).

See [adr/0005-presigned-uploads.md](adr/0005-presigned-uploads.md).

## 9. Realtime

`/api/ws/chat/{course_id}` accepts the access token via a query parameter (since browser WebSocket cannot set headers). On connect, the consumer:

1. Verifies the user is enrolled or the course owner.
2. Joins a Redis pub/sub channel `chat:{course_id}`.
3. Persists each inbound message via the chat service.
4. Pushes messages from the channel back to the client.

Presence is approximated by Redis sorted set `presence:{course_id}` (member = user_id, score = last-seen unix). Typing indicator is ephemeral pub/sub-only.

## 10. Observability

- **Logs** — structlog → JSON to stdout; collected by container runtime; redacted PII.
- **Metrics** — Prometheus middleware exposes `/metrics`; default RED metrics + business counters.
- **Traces** — OpenTelemetry SDK with OTLP exporter; sampled at 10% in prod, 100% in dev.
- **Errors** — Sentry-compatible DSN if configured (`SENTRY_DSN` env).
- **Audit** — every state-changing admin action writes an `audit_events` row.

## 11. Failure modes & resilience

| Scenario | Mitigation |
|----------|------------|
| Postgres down | API returns `503` on `/healthz/ready`; reverse proxy stops routing; learner reads degrade gracefully via cached Next.js routes |
| Redis down | Chat & rate limiter fail fast (`503` on `/chat`); core API stays up; degraded mode banner shown in FE |
| MinIO down | Read-only mode for assets; uploads return `503` with retry-after |
| Worker backlog | Queue depth metric alarms; degraded toasts in FE |

## 12. Scaling notes

- Stateless API and FE allow horizontal scaling behind the proxy.
- Postgres is the primary bottleneck; v1 is single-writer. Read replicas + Pgpool can be added without code changes (repositories accept an explicit session).
- WebSocket pubsub via Redis means any API replica can receive a message for any room.

## 13. Accessibility gate

- `WCAG 2.2 AA` is enforced in CI via `@axe-core/playwright` against
  the built Next.js app on every PR and every push to `Rewrite` /
  `master`. The audit covers the golden-path routes for all three
  roles (logged-out home/catalog/auth pages, course detail,
  student dashboard + profile, instructor studio, admin).
- Workflow: `.github/workflows/accessibility.yml`. Suite:
  `apps/frontend/tests/e2e/accessibility.spec.ts`. Run locally with
  `make a11y` against an up dev stack.
- Full guide — including how to read an axe failure, when to fix
  vs. when to scope a `disableRules` call, and why there is no
  global ignore list — is in [`docs/accessibility.md`](./accessibility.md).
