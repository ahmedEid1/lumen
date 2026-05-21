# API conventions

OpenAPI is the source of truth. This document describes the conventions OpenAPI does not capture.

Base URL: `/api/v1`. All responses are JSON. All times are ISO 8601 UTC.

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
