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
	@echo "  Meilisearch  : http://localhost:7700"
	@echo ""

# ----- db -----
.PHONY: migrate
migrate: ## Apply database migrations.
	$(COMPOSE) exec api alembic upgrade head

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
demo-seed: ## Load the H4 free-tier demo bundle (3 courses + demo learner).
	$(COMPOSE) exec api python -m app.cli demo-seed

.PHONY: reset
reset: ## Drop volumes and rebuild. Destroys local data!
	$(COMPOSE) down -v
	$(COMPOSE) up --build -d
	@sleep 5
	@$(MAKE) --no-print-directory migrate
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
	$(COMPOSE) exec api pytest -q

.PHONY: test.web
test.web: ## Frontend unit tests.
	$(COMPOSE) exec web pnpm test --run

.PHONY: test.e2e
test.e2e: ## Playwright end-to-end tests against the live stack (uses the e2e profile).
	$(COMPOSE) --profile e2e run --rm e2e

.PHONY: a11y
a11y: ## WCAG 2.2 AA axe-core gate (requires `make up` first; chromium only).
	$(COMPOSE) --profile e2e run --rm e2e tests/e2e/accessibility.spec.ts --project=chromium

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

# ----- free-tier deploy (H4) -----
# These targets assume the operator has already run `flyctl auth login`
# locally. The full first-deploy runbook lives in
# docs/deployment/free-tier.md.

.PHONY: deploy.fly
deploy.fly: deploy.fly.api deploy.fly.worker ## Deploy api + worker to Fly.io.

.PHONY: deploy.fly.api
deploy.fly.api: ## Deploy api to Fly.io.
	flyctl deploy --config infra/fly/fly.api.toml --dockerfile infra/fly/Dockerfile.fly --remote-only

.PHONY: deploy.fly.worker
deploy.fly.worker: ## Deploy worker to Fly.io.
	flyctl deploy --config infra/fly/fly.worker.toml --dockerfile infra/fly/Dockerfile.fly --remote-only

.PHONY: deploy.demo-seed
deploy.demo-seed: ## Run the demo seed on the deployed api (via flyctl ssh).
	flyctl ssh console --app lumen-api --command "python -m app.cli seed"
	flyctl ssh console --app lumen-api --command "python -m app.cli demo-seed"
	flyctl ssh console --app lumen-api --command "python -m app.cli reindex"

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

# ----- release publish (A6) -----
# Push the local `Rewrite` branch to `origin/Rewrite` and open the
# release PR against `master`. Previews the commits that would land
# and prompts before doing anything destructive. The PR body is
# pre-written at docs/release/1.1.0-agentic-pr-body.md.
#
# Requires: `gh` authenticated (`gh auth status`) and write access
# to the origin remote. The push is a fast-forward (origin/Rewrite
# is an ancestor of local Rewrite), so no --force is needed.
.PHONY: publish-rewrite
publish-rewrite: ## Push Rewrite to origin and open the release PR.
	@echo ""
	@echo "  Publishing local Rewrite to origin/Rewrite + opening PR vs master."
	@echo "  PR body source: docs/release/1.1.0-agentic-pr-body.md"
	@echo ""
	@echo "  Commits that will be pushed (origin/Rewrite..Rewrite):"
	@echo "  ---------------------------------------------------------------"
	@git log origin/Rewrite..Rewrite --oneline | head -25
	@echo "  ---------------------------------------------------------------"
	@echo ""
	@read -p "  Confirm push Rewrite to origin and open PR? [y/N] " ans && [ "$$ans" = "y" ] || (echo "  aborted"; exit 1)
	git push origin Rewrite
	gh pr create --base master --head Rewrite --title "release: 1.1.0-agentic — Phase H + Phase I shipped" --body-file docs/release/1.1.0-agentic-pr-body.md
