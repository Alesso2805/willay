SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose

# Windows: from PowerShell make runs the recipes with cmd.exe, from Git Bash with sh.exe. The
# recipes avoid shell-specific commands; what differs is decided here, by make itself.
ifeq ($(OS),Windows_NT)
# Docker Desktop does not map file ownership on bind mounts, and Windows has no `id`.
SEED_USER := 0
else
# Your uid, so that .secrets/station-keys.json belongs to you and not to the container user.
SEED_USER := $(shell id -u):$(shell id -g)
endif
# Git Bash would rewrite container paths such as /secrets as Windows paths; elsewhere it is unused.
export MSYS_NO_PATHCONV := 1

.PHONY: help up down lint lint-backend lint-dashboard test test-backend test-dashboard openapi migrate seed simulate latency loadtest demo secrets

help: ## List the available commands
ifeq ($(OS),Windows_NT)
	@findstr /R /C:"^[a-z-]*:.*## " $(MAKEFILE_LIST)
else
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
endif

up: .env ## Start the whole stack (migrate runs before api and workers)
	$(COMPOSE) up -d --build --wait

# make's own file function instead of cp, which cmd.exe does not have. On Windows it writes CRLF
# line endings, which Docker Compose and python-dotenv both read correctly.
.env:
	$(file > .env,$(file < .env.example))
	@echo Created .env from .env.example, with development-only credentials.

down: ## Stop the stack (keeps the volumes)
	$(COMPOSE) down

# On a server only (docs/runbooks/deploy.md): there is no .env yet, and this one is not for local use.
secrets: ## Server: write .env with new credentials for HOST (HOST=willay.example.org DEMO=1)
	sh infra/scripts/production-env.sh "$(HOST)" "$(DEMO)"

lint: lint-backend lint-dashboard ## Ruff, Mypy and ESLint

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy

lint-dashboard:
	cd dashboard && npm run lint

test: test-backend test-dashboard ## Pytest (unit and integration with Docker) and Vitest

test-backend:
	cd backend && uv run pytest

test-dashboard:
	cd dashboard && npm test -- --watch=false

openapi: ## Regenerate docs/openapi.json (a test fails if it is out of date)
	cd backend && uv run python -m willay.api.openapi ../docs/openapi.json

migrate: .env ## Apply the Alembic migrations as willay_owner
	$(COMPOSE) run --rm migrate

# .secrets/ is in the repository (only its .gitkeep), so no shell has to create it.
seed: .env ## Load the demo data and print the API keys (ARGS=--rotate-keys to rotate them)
	$(COMPOSE) run --rm --user "$(SEED_USER)" -v "$(CURDIR)/.secrets:/secrets" migrate python -m willay.seed --keys-file /secrets/station-keys.json $(ARGS)

simulate: ## Station simulator against the local API (ARGS="--scenario rimac --seed 42")
	cd backend && uv run simulate --keys-file ../.secrets/station-keys.json $(ARGS)

latency: .env ## p50/p95 of reading received -> first alert sent (ARGS="--minutes 60")
	$(COMPOSE) run --rm migrate python -m willay.alerts.api.latency_cli $(ARGS)

loadtest: .env ## Load test: 50 stations x 1 reading/10 s, checks SPEC (ARGS="--minutes 30")
	$(COMPOSE) run --rm migrate python -m willay.loadtest $(ARGS)

# The keys file is mounted read-only: the demo only reads the keys `make seed` saved.
demo: .env ## Guided Rímac scenario, narrated; PASS when level 2 acknowledges both incidents
	$(COMPOSE) run --rm --user "$(SEED_USER)" -v "$(CURDIR)/.secrets:/secrets:ro" migrate python -m willay.demo $(ARGS)
