# E2E suite (Playwright)

Browser-driven regression suite running against the live docker
compose stack. Two flavours of test live side-by-side here:

- **Accessibility gate** — `accessibility.spec.ts` (Phase D5). Audits
  the golden routes against WCAG 2.2 AA via axe-core. Wired to the
  `.github/workflows/accessibility.yml` workflow.
- **Golden behavioural paths** — `auth.spec.ts`, `learner-flow.spec.ts`,
  `instructor-golden.spec.ts`, `tutor-citations.spec.ts`,
  `ingest-multimodal.spec.ts` (Phase H3). Walk the headline user
  flows end-to-end. Wired to `.github/workflows/e2e.yml`.

The older smoke / journey / instructor specs predate Phase H and stay
in place as a thinner sanity layer that runs in the same suite.

## Running locally

Pre-flight: bring up the full dev stack and seed the demo data.

```bash
make up                      # docker compose up -d
make migrate
make seed
```

The H3 tutor spec also needs the seeded course's lesson chunks
indexed (the seed creates a published course directly in the DB,
which bypasses the publish hook that normally enqueues embedding
ingest). Trigger it from the api container:

```bash
docker compose exec -T api python -c "
import asyncio
from app.db.base import get_sessionmaker
from app.services.embeddings_ingest import ingest_course
from sqlalchemy import select
from app.models.course import Course, CourseStatus

async def main():
    Session = get_sessionmaker()
    async with Session() as db:
        rows = (await db.execute(
            select(Course.id).where(
                Course.status == CourseStatus.published,
                Course.deleted_at.is_(None),
            )
        )).all()
        for (cid,) in rows:
            await ingest_course(db, cid)
            print('indexed', cid)

asyncio.run(main())
"
```

Then run the suite:

```bash
pnpm --filter ./apps/frontend exec playwright test
```

Filter to a single spec:

```bash
pnpm --filter ./apps/frontend exec playwright test tests/e2e/auth.spec.ts
```

## Debugging

Run with the UI mode for interactive stepping and time-travel:

```bash
pnpm --filter ./apps/frontend exec playwright test --ui
```

Or open the headed browser for a single spec:

```bash
pnpm --filter ./apps/frontend exec playwright test \
  tests/e2e/tutor-citations.spec.ts --headed --project=chromium
```

Other useful flags:

- `--debug` — pause at the first action, step through with the
  inspector window.
- `--trace on` — record a trace for every test (not just retries);
  open with `pnpm exec playwright show-trace path/to/trace.zip`.
- `--project=chromium` — skip the WebKit run if you don't need
  cross-browser coverage right now.

On CI, failed runs upload the Playwright report + traces +
screenshots + videos as a workflow artifact named
`playwright-e2e-report` (see `.github/workflows/e2e.yml`).

## Environment

The specs read these env vars at start-up:

| Var               | Default                   | Used by                           |
|-------------------|---------------------------|-----------------------------------|
| `E2E_BASE_URL`    | `http://localhost:3000`   | every spec (`page.goto` baseURL)  |
| `E2E_API_BASE_URL`| `http://localhost:8000`   | `helpers/api.ts`                  |
| `MAILPIT_BASE_URL`| `http://localhost:8025`   | `helpers/mailpit.ts`              |
| `LLM_PROVIDER`    | `noop` (recommended)      | backend — keeps AI paths free + deterministic |

When `LLM_PROVIDER=noop`:

- Tutor responses are formatted as
  `"Based on the course content, <question…> [L:<lesson_id>] …"`, so
  the citation parser sees deterministic tokens.
- AI outline generation returns plain text that fails the JSON
  outline contract → the studio surfaces a friendly error toast.
  `instructor-golden.spec.ts` asserts on that deterministic failure
  path rather than on a positive preview tree (the latter requires a
  real provider).

## Adding a new spec

- Put new specs at the top level of `tests/e2e/`. Helpers (login,
  Mailpit, API) live under `tests/e2e/helpers/`.
- Use the seeded creds via `helpers/login.ts`'s `login(page, role)`
  rather than re-spelling email + password.
- Anchor selectors on `data-testid`, `aria-label`, or role + name —
  not on translated copy that the i18n parity test could rotate.
- Don't add a backend endpoint just to make a test easier; if the
  data you need isn't surfaced, prefer reading from Mailpit / the
  test database / the live API rather than minting a `/_test/*`
  route.
