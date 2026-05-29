# Contributing to Lumen

Thanks for your interest! Here's how to get set up and how we work.

## Local setup

```bash
git clone https://github.com/ahmedEid1/lumen.git
cd lumen
cp .env.example .env
make up
```

You should see:

- Frontend on http://localhost:3000
- API on http://localhost:8000

Run the test suite:

```bash
make test
```

Install pre-commit hooks once:

```bash
pip install --user pre-commit
pre-commit install
```

## Working on the backend

Open a shell in the `api` container:

```bash
make shell.api
```

Common commands inside the container:

```bash
pytest                                  # run tests
ruff check . && ruff format .           # lint + format
mypy app                                # type check
alembic upgrade head                    # apply migrations
alembic revision --autogenerate -m "msg"  # generate migration
```

## Working on the frontend

```bash
make shell.web
pnpm dev          # already running in the container; this is for ad-hoc
pnpm lint
pnpm typecheck
pnpm test
pnpm test:e2e
```

## Branching & commits

- Branch from `main`: `feat/<short-name>`, `fix/...`, `chore/...`.
- Conventional Commits for subjects.
- Squash on merge.

## Pull requests

- One topic per PR.
- Tests are required for new behavior and regressions.
- Update docs when the contract changes.
- Use the PR template; tick the checklist honestly.

## Code style

We rely on tooling — formatters first, opinions second.

- **Python:** ruff (lint + format), mypy strict on `app/`, line length 100.
- **TypeScript:** ESLint flat config, Prettier, `strict: true`, no implicit any.
- Prefer pure functions and explicit dependencies.
- Public functions and modules get a short module-level docstring; bodies stay comment-light.

## Adding a feature

1. Sketch the change in an issue or short proposal.
2. If it touches an architectural seam, open an ADR.
3. Implement behind tests.
4. Update OpenAPI (auto), regenerate the TS client (`make api-client`).
5. PR with a clear "why".

## Reporting bugs

Use the bug report issue template. Include version (commit SHA), env, repro steps, expected vs actual, logs (redacted).

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be kind, assume good faith.
