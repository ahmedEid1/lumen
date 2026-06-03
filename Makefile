# ---------- Lumen ----------
# Common dev commands. All wrap docker compose so they work on any host.

COMPOSE       ?= docker compose
COMPOSE_PROD  ?= docker compose -f docker-compose.prod.yml

.DEFAULT_GOAL := help

# ----- help -----
.PHONY: help
help: ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_.-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ----- lifecycle -----
.PHONY: up
up: ## Build & start the dev stack.
	$(COMPOSE) up --build -d
	@$(MAKE) --no-print-directory urls

.PHONY: down
down: ## Stop & remove containers.
	$(COMPOSE) down

.PHONY: restart
restart: ## Restart all containers.
	$(COMPOSE) restart

.PHONY: logs
logs: ## Tail logs for all services.
	$(COMPOSE) logs -f --tail=200

.PHONY: ps
ps: ## Show service status.
	$(COMPOSE) ps

.PHONY: urls
urls: ## Print useful local URLs.
	@echo ""
	@echo "  Frontend     : http://localhost:3000"
	@echo "  API          : http://localhost:8000"
	@echo "  API docs     : http://localhost:8000/docs"
	@echo "  MinIO console: http://localhost:9001"
	@echo "  Mailpit      : http://localhost:8025"
	@echo ""

# ----- db -----
.PHONY: migrate
migrate: migrate.safe ## Apply additive (phase-A) migrations safely (alias for migrate.safe).

.PHONY: migrate.safe
migrate.safe: ## Apply only additive (phase-A) migrations; refuses to cross a phase boundary.
	# PR-11 / S7pre.9 — never a blind `alembic upgrade head`. The guard
	# walks pending revisions and applies up to (but not across) the first
	# release-gated rev (IRREVERSIBLE 0031 / metadata flip 0032 / NOT-NULL
	# tighten 0043). A blocked phase boundary exits non-zero with the exact
	# `make migrate.phase` instruction.
	$(COMPOSE) exec api python -m app.db.migration_phase_guard safe

.PHONY: migrate.phase
migrate.phase: ## Apply phase-gated migrations to head. Requires ALLOW_PHASE_MIGRATION=1.
	# Explicit, operator-acknowledged step for a phased release (DR-12).
	# Run ONE phase at a time per the deploy runbook, e.g. Phase B then C.
	$(COMPOSE) exec -e ALLOW_PHASE_MIGRATION=$(ALLOW_PHASE_MIGRATION) api \
		python -m app.db.migration_phase_guard phase

.PHONY: revision
revision: ## Autogenerate a migration. Usage: make revision m="add foo"
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

.PHONY: downgrade
downgrade: ## Downgrade one revision.
	$(COMPOSE) exec api alembic downgrade -1

.PHONY: seed
seed: ## Load demo data.
	$(COMPOSE) exec api python -m app.cli seed

.PHONY: demo-seed
demo-seed: ## Load the agentic-demo bundle (3 courses + demo learner + tutor turn + draft).
	$(COMPOSE) exec api python -m app.cli demo-seed

.PHONY: reset
reset: ## Drop volumes and rebuild. Destroys local data!
	$(COMPOSE) down -v
	$(COMPOSE) up --build -d
	@sleep 5
	# Fresh local DB: cross every phase intentionally (the data-collapse is a
	# no-op on an empty `users` table). ALLOW_PHASE_MIGRATION=1 makes the
	# destructive-rebuild intent explicit.
	@$(MAKE) --no-print-directory migrate.phase ALLOW_PHASE_MIGRATION=1
	@$(MAKE) --no-print-directory seed

# ----- quality -----
.PHONY: lint
lint: lint.api lint.web ## Run all linters.

.PHONY: lint.api
lint.api: ## Lint backend.
	$(COMPOSE) exec api ruff check .
	$(COMPOSE) exec api ruff format --check .
	$(COMPOSE) exec api mypy app

.PHONY: lint.web
lint.web: ## Lint frontend.
	$(COMPOSE) exec web pnpm lint
	$(COMPOSE) exec web pnpm typecheck

.PHONY: fmt
fmt: ## Format code.
	$(COMPOSE) exec api ruff format .
	$(COMPOSE) exec api ruff check --fix .
	$(COMPOSE) exec web pnpm format

# ----- tests -----
.PHONY: test
test: test.api test.web ## Run all tests.

.PHONY: test.api
test.api: ## Backend tests.
	# Drop the historical ``-q``: pyproject.toml addopts now pin
	# ``-v --durations=10 --timeout=120 -n 4 --dist=loadfile
	# --max-worker-restart=0`` (streaming + parallel + per-test
	# timeout + fail-loud on worker crash). A
	# leading ``-q`` on the CLI would override that and silently
	# regress us to the old serial behaviour.
	$(COMPOSE) exec api pytest

.PHONY: test.web
test.web: ## Frontend unit tests.
	# Direct `pnpm exec vitest run` avoids the pnpm-shorthand-vs-
	# script-flag ambiguity that breaks on pnpm 9.15.0 (and the
	# packageManager pin in package.json). `pnpm test --run` is
	# intercepted by pnpm's CLI as an unknown top-level option;
	# `pnpm test -- --run` works but is fragile across pnpm bumps.
	# `pnpm exec vitest run` invokes vitest's CLI directly with
	# its built-in `run` subcommand, matching the form CI uses
	# in .github/workflows/ci.yml.
	$(COMPOSE) exec web pnpm exec vitest run

.PHONY: test.e2e
test.e2e: ## Playwright end-to-end tests against the live stack (uses the e2e profile).
	$(COMPOSE) --profile e2e run --rm e2e

.PHONY: a11y
a11y: ## WCAG 2.2 AA axe-core gate (requires `make up` first; chromium only).
	$(COMPOSE) --profile e2e run --rm e2e tests/e2e/accessibility.spec.ts --project=chromium

# ----- evals (H2) -----
# Run a golden eval suite against the live api container. Default
# suite is `tutor` (30 items); override with e.g. `make eval suite=authoring`
# or `make eval suite=ingest`. Pass `limit=3` to truncate (smoke run).
#
# Provider selection is via env on the api container — see the
# operator runbook in docs/release/operator-activation-runbook.md. The default
# .env / docker-compose path gives you the noop provider, which is
# free, deterministic, and good enough to prove the harness wiring;
# point LLM_PROVIDER=openai + OPENAI_API_BASE at Groq for a real run.
.PHONY: eval
eval: ## Run an eval suite. Override: suite=authoring|ingest, limit=N.
	$(COMPOSE) exec api python -m app.evals run --suite $(or $(suite),tutor) $(if $(limit),--limit $(limit),)

# ----- shells -----
.PHONY: shell.api
shell.api: ## Shell into the API container.
	$(COMPOSE) exec api bash

.PHONY: shell.web
shell.web: ## Shell into the web container.
	$(COMPOSE) exec web sh

.PHONY: shell.db
shell.db: ## Open psql against the dev database.
	$(COMPOSE) exec db psql -U lumen -d lumen

# ----- prod helpers -----
.PHONY: config.check
config.check: ## Validate prod compose configuration.
	$(COMPOSE_PROD) config -q && echo "OK"

.PHONY: prod.up
prod.up: ## Start prod stack (requires .env populated for prod).
	$(COMPOSE_PROD) up -d

.PHONY: prod.logs
prod.logs:
	$(COMPOSE_PROD) logs -f --tail=200

# ----- meta -----
.PHONY: api-client
api-client: ## Regenerate the TypeScript client from OpenAPI.
	$(COMPOSE) exec web pnpm openapi:generate

.PHONY: openapi
openapi: ## Dump OpenAPI schema to apps/backend/openapi.json (no running stack needed).
	$(COMPOSE) exec api python -m scripts.export_openapi --out openapi.json --pretty

.PHONY: openapi.local
openapi.local: ## Same as `openapi` but runs on the host (requires deps installed locally).
	cd apps/backend && python -m scripts.export_openapi --out openapi.json --pretty

.PHONY: precommit
precommit: ## Run pre-commit on all files.
	pre-commit run --all-files

# ----- MCP (I1) -----
# Mint a new MCP OAuth client + print its secret once. Pass the
# owner email via OWNER (defaults to the seeded instructor).
#
#     make mcp-token OWNER=teacher@lumen.test
#
# Save the `client_secret` line — Lumen only stores an argon2 hash;
# if you lose the plaintext you mint a new one.
.PHONY: mcp-token
mcp-token: ## Mint a new MCP OAuth client + print its secret once.
	$(COMPOSE) exec api python -m app.cli mcp-token --owner-email "$(or $(OWNER),teacher@lumen.test)" --name "$(or $(NAME),Local MCP client)" --scopes "$(or $(SCOPES),*)"

# The `publish-rewrite` target (Phase A6) was removed on 2026-05-26
# when `Rewrite` was renamed to `main` and `master` to `legacy`. The
# rebuild was promoted in-place; there is no Rewrite-→-master PR to
# open. Ongoing development ships via the normal flow: PR to `main`
# → CI gates → merge. See docs/release/operator-activation-runbook.md
# Step 7 (now marked superseded) for the historical context.
