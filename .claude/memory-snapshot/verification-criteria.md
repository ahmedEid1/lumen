---
name: verification-criteria
description: "User explicitly preferred running-the-app verification over test-suite-only signals — six real bugs in iter 98 weren't caught by the green test suite"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 570ed99c-48b3-471c-a2d9-c72712d55445
---

This user values "I drove the running app and watched it work" over
"all tests are green." Iter 98 demonstrated why: the entire test
suite was green BEFORE that iteration, and `docker compose up`
exposed six real first-boot bugs that no test would have caught:

1. Dockerfile `deps` stage couldn't build without a stub `app/`
2. Meilisearch port 7700 collided with a Windows reservation
3. Meilisearch healthcheck used IPv6 `localhost` against an IPv4 daemon
4. `CORS_ORIGINS` env shape (comma vs JSON) crashed startup
5. Structlog `add_logger_name` incompatible with `PrintLoggerFactory`
6. Pydantic `EmailStr` rejected `.test` TLD seed accounts

**Why these were invisible**: tests run with `EnvironmentSettings`
that bypass the docker-compose env shape; they use a real DB
session (so SQLAlchemy's String-vs-Enum mismatch is silent); they
never start meilisearch (so the port + healthcheck issues never
surface); and pytest captures logging without exercising the
PrintLogger path that production uses.

**How to apply**: when a task is "verify X works", at least one
iteration must include actually running the stack (`docker compose
up -d`) and driving the relevant flow through the browser via the
Chrome MCP tools — not just running the test suite. The credible
stopping criteria for "everything works" includes:

- Backend pytest green
- Frontend vitest green
- Playwright e2e green **against the live docker stack**
- Manual Chrome smokes for: login (all 3 roles), enroll, complete
  lesson, post discussion, language switcher (LTR → RTL), dark
  mode toggle
- `docker compose down && up` cycle re-boots clean
- 60s of idle in `docker compose logs` produces no new errors

Don't claim done without running the app.
