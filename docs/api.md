# API conventions

OpenAPI is the source of truth. This document describes the conventions OpenAPI does not capture.

Base URL: `/api/v1`. All responses are JSON. All times are ISO 8601 UTC.

## Contents

- [Authentication](#authentication)
- [Versioning](#versioning)
- [Pagination](#pagination)
- [Filtering & sorting](#filtering--sorting)
- [Errors](#errors)
- [Idempotency](#idempotency)
- [Rate limiting](#rate-limiting)
- [Resource conventions](#resource-conventions)
- [Request IDs](#request-ids)
- [WebSocket protocol](#websocket-protocol)
- [Endpoint inventory](#endpoint-inventory)
  - [Auth](#auth-apiv1auth)
  - [Users](#users-apiv1users)
  - [Catalog](#catalog-apiv1)
  - [Search](#search-apiv1search)
  - [Courses](#courses-apiv1courses)
  - [Enrollments + progress](#enrollments--progress-apiv1me)
  - [Reviews](#reviews-apiv1coursescourse_idreviews)
  - [Chat](#chat-apiv1chat)
  - [Uploads](#uploads-apiv1uploads)
  - [Certificates](#certificates-apiv1certificates)
  - [Admin](#admin-apiv1admin--admin-role-only)
  - [Health](#health-apiv1health)

## Authentication

```
Authorization: Bearer <access_token>
```

Or the `__Host-access` cookie when the browser is the client. WebSocket connections receive the token as a `?token=` query parameter.

## Versioning

The URL carries the version (`/api/v1/...`). Non-breaking additions ship in the same version. Breaking changes get a new version and the previous version is deprecated for one full minor release.

## Pagination

Cursor-based for collections that grow without bound (chat messages, audit events):

```
GET /api/v1/chat/courses/42/messages?limit=50&before=<cursor>
→ { "items": [...], "next_cursor": "..." }
```

Offset-based for catalog-like reads:

```
GET /api/v1/courses?page=1&page_size=20
→ { "items": [...], "total": 137, "page": 1, "page_size": 20 }
```

`page_size` defaults to 20, max 100.

## Filtering & sorting

- Filter parameters are flat: `?subject=python&difficulty=beginner&tag=async`.
- Free-text search: `?q=fastapi`.
- Sort: `?sort=-created` (prefix `-` = desc).

## Errors

```json
{
  "error": {
    "code": "course.not_found",
    "message": "Course not found",
    "details": { "course_id": "abc123" },
    "request_id": "req_01HXYZ..."
  }
}
```

| HTTP | When |
|------|------|
| 400  | malformed request |
| 401  | missing/invalid auth |
| 403  | authenticated but not permitted |
| 404  | resource not found |
| 409  | conflict (e.g. duplicate slug, already enrolled) |
| 422  | semantic validation (Pydantic) |
| 429  | rate limited |
| 5xx  | server error |

`code` is stable; `message` is for humans; `details` is structured context.

## Idempotency

Mutating endpoints that may be safely retried accept `Idempotency-Key: <uuid>` and replay the original response when the key has been seen within 24 h.

## Rate limiting

`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers on every response. Defaults:

| Bucket            | Limit |
|-------------------|-------|
| anon by IP        | 60 req / min |
| user `auth.*`     | 10 req / min |
| user general      | 240 req / min |
| WS chat send      | 30 msg / min |

## Resource conventions

- IDs are short opaque strings (`nanoid`, 21 chars) — never expose sequential integers in URLs.
- `created_at` / `updated_at` on every persisted resource.
- Soft deletes for user-visible content (Course, Lesson, Review) via `deleted_at`; hard delete for sessions, refresh tokens, ephemeral data.
- Polymorphic lesson content uses `type` discriminator (`text`, `video`, `image`, `file`, `quiz`) and a typed `data` payload.

## Request IDs

Every request gets a `X-Request-ID`. Clients may pass their own; otherwise the server generates one. Logged and echoed in errors.

## WebSocket protocol

`/api/v1/ws/chat/{course_id}?token=...`

Inbound frames:

```json
{ "type": "message", "data": { "body": "hello" } }
{ "type": "typing.start" }
{ "type": "typing.stop" }
```

Outbound frames:

```json
{ "type": "message", "data": { "id": "...", "author": {...}, "body": "...", "created_at": "..." } }
{ "type": "presence", "data": { "online": ["user_id", ...] } }
{ "type": "typing",   "data": { "user_id": "...", "active": true } }
{ "type": "error",    "data": { "code": "...", "message": "..." } }
```

Server closes with the closest applicable code (`4401` unauthenticated, `4403` not enrolled, `4404` course gone, `1011` server error).

The WebSocket path used by the client is `/api/v1/chat/ws/{course_id}?token=...`.

## Endpoint inventory

OpenAPI at `/openapi.json` is the source of truth; this list points to the resources you'll actually use.

### Auth (`/api/v1/auth`)
- `POST /register` — create account; queues an email-verification link
- `POST /login` — exchange credentials for an access token + refresh cookie
- `POST /refresh` — rotate the refresh token (reuse is detected and revokes the chain)
- `POST /logout` — clear cookies + revoke the presented refresh token
- `GET  /me` — current authenticated user
- `POST /password-reset/request` — always 200 (does not leak email existence)
- `POST /password-reset/confirm` — single-use token bound to the current password hash
- `POST /verify/request` — resend the email-verification link for the current user
- `POST /verify/confirm` — confirm an email-verification token (idempotent)

### Users (`/api/v1/users`)
- `GET /me`, `PATCH /me` — view and edit profile
- `POST /me/change-password` — verifies current password, revokes all refresh tokens
- `GET /me/export` — lightweight GDPR export (profile + counts)
- `DELETE /me` — deactivate, scramble PII, revoke refresh tokens; requires password
- `GET /me/sessions`, `DELETE /me/sessions`, `DELETE /me/sessions/{id}` —
  list / revoke-all / revoke-one active refresh-token sessions

### Catalog (`/api/v1`)
- `GET /subjects` — list with `total_courses`
- `GET /tags`
- `GET /courses` — paginated, filterable (`q`, `subject`, `tag`, `difficulty`, `sort`)

### Search (`/api/v1/search`)
- `GET /courses?q=...` — Postgres `tsvector` full-text on `courses.search_vector` (a `GENERATED ALWAYS AS` column Postgres maintains on every insert/update — no Celery trigger needed) **plus** an ILIKE OR-branch on `title` / `overview` for partial-word matches the English stemmer would miss (so "java" still finds "javascript"). FTS hits rank at `ts_rank`; ILIKE-only hits get a `0.0` floor so exact matches surface first. Supports `subject`, `tag`, `difficulty`.

### Courses (`/api/v1/courses`)
- `POST /` — instructor-only create
- `GET  /mine` — instructor's own courses
- `GET  /{slug-or-id}` — detail; owners and admins see drafts
- `PATCH /{course_id}`, `DELETE /{course_id}` — owner/admin only
- `POST /{course_id}/duplicate` — clone modules + lessons as a draft owned by the caller (any instructor)
- `GET /{course_id}/analytics` — owner/admin only; per-course metrics
- `GET /{course_id}/students` — owner/admin only; cohort listing with per-student progress
- `POST /{course_id}/modules`, `PATCH /modules/{module_id}`, `DELETE /modules/{module_id}`
- `POST /{course_id}/modules/order` — reorder via id→order map
- `POST /modules/{module_id}/lessons`, `PATCH /lessons/{lesson_id}`, `DELETE /lessons/{lesson_id}`
- `POST /modules/{module_id}/lessons/order`
- `GET  /lessons/{lesson_id}` — fetch a lesson; allowed for owner/admin/enrolled,
  or anonymous when `is_preview` is true and the course is published

Lesson payload is discriminated by `type` (`text` | `video` | `image` | `file` | `quiz`). Quiz schemas validate that choice-based questions have answer_keys subset of the choice ids.

### Enrollments + progress (`/api/v1/me`)
- `GET /enrollments`, `POST /enrollments/{course_id}`, `DELETE /enrollments/{course_id}`
- `POST /progress/lessons/{lesson_id}` — mark complete; the response includes `progress_pct` and a `certificate_id` once 100% complete
- `POST /progress/lessons/{lesson_id}/quiz` — server-graded quiz submission; persists the score on `LessonProgress`, marks the lesson complete on pass, returns per-question correctness
- `GET  /notifications`, `POST /notifications/{id}/read`
- `GET  /bookmarks`, `PUT /bookmarks/{course_id}`, `DELETE /bookmarks/{course_id}`

### Reviews (`/api/v1/courses/{course_id}/reviews`)
- `GET`, `PUT` (upsert), `DELETE` — enrolled-only writes, public reads

### Chat (`/api/v1/chat`)
- `GET  /courses/{course_id}/messages?before=&limit=` — paginated history
- `POST /courses/{course_id}/messages` — REST send
- `WS   /ws/{course_id}?token=...` — real-time stream

### Uploads (`/api/v1/uploads`)
- `POST /sign` — returns a presigned PUT URL + public URL; content-type allow-list and size cap per `kind` (`avatar` | `cover` | `lesson` | `attachment`)

### Certificates (`/api/v1/certificates`)
- `GET /{course_id}.pdf` — synchronous PDF render, gated on 100% completion + enrollment
- `GET /verify/{certificate_id}` — public lookup; returns course + learner display name (no PII)

### Admin (`/api/v1/admin`) — admin role only
- `POST/PATCH/DELETE /subjects`, `POST/DELETE /tags`
- `GET /courses?q=&only_featured=&limit=`, `PATCH /courses/{id}/feature`
- `GET /users?q=&limit=`, `PATCH /users/{user_id}/role`, `PATCH /users/{user_id}/active`
- `GET /audit?action=&actor_id=&limit=` — append-only audit log
- `POST /search/reindex` — queue a full search reindex (202 Accepted)
- `GET  /stats` — platform totals (users, instructors, courses by status, enrollments)

### Health (`/api/v1/health`)
- `GET /live` — process is up
- `GET /ready` — Postgres + Redis reachable; returns 503 on failure
