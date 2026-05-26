---
name: first-boot-gotchas
description: "Three configuration gotchas that bite on a fresh `docker compose up` and aren't yet pinned by a test"
metadata: 
  node_type: memory
  type: project
  originSessionId: 570ed99c-48b3-471c-a2d9-c72712d55445
---

After iter 98 the stack boots cleanly, but three configuration
gotchas live in non-tracked files (`.env`, container env) and
will bite a fresh checkout / new dev machine. None of these are
captured by an automated test today — they'd show up as boot-time
crashes that have to be diagnosed from logs.

**1. `CORS_ORIGINS` must be JSON-array, not comma-separated**

pydantic-settings v2 parses `list[str]` env vars as JSON *before*
any `mode="before"` field_validator runs. The historical
`CORS_ORIGINS=http://localhost:3000` shape now crashes startup
with `error parsing value for field "cors_origins"`. Both the
`docker-compose.yml` default and any local `.env` must use:

    CORS_ORIGINS=["http://localhost:3000","https://lumen.example"]

`.env` is gitignored so the fix doesn't carry between checkouts —
new devs need to be told. **How to apply**: check `.env`'s
`CORS_ORIGINS` line at the start of any boot-related task; fix
it locally before `docker compose up` if it's still the old shape.

**2. `.test` TLD seed accounts need `app.core.email_type.Email`**

Pydantic's `EmailStr` defers to email-validator which enforces
RFC 6761 and refuses reserved TLDs (`.test`, `.invalid`,
`.localhost`, `.example`). The entire seed convention
(`student@lumen.test`, etc.) and test fixtures use `.test`. Iter
98 added `app.core.email_type.Email` which wraps email-validator
with `test_environment=True`. **How to apply**: any new endpoint
or schema accepting an email must import from `app.core.email_type`,
never from `pydantic.EmailStr` directly. A grep for `EmailStr` in
the backend should return zero hits.

**3. `User.role` access pattern**

The column is typed `Mapped[Role]` but stored as `String(20)`
without an `Enum` TypeDecorator, so SQLAlchemy hands back a plain
`str` on read, not a `Role` enum instance. `user.role.value`
crashes with `AttributeError`. **How to apply**: always use
`str(user.role)` (works for both StrEnum instances and plain
strings) when you need the string form, or `Role(user.role)` when
you need a Role instance. Don't `.value` it directly.
