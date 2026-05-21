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
test.e2e: ## Playwright end-to-end tests.
	$(COMPOSE) exec web pnpm test:e2e

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

.PHONY: precommit
precommit: ## Run pre-commit on all files.
	pre-commit run --all-files
