SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose

.PHONY: help up down lint lint-backend lint-dashboard test test-backend test-dashboard openapi migrate seed simulate demo

help: ## List the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: .env ## Start the whole stack (migrate runs before api and workers)
	$(COMPOSE) up -d --build --wait

.env:
	cp .env.example .env
	@echo "Created .env from .env.example (development-only credentials)."

down: ## Stop the stack (keeps the volumes)
	$(COMPOSE) down

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

# Runs with your uid so that .secrets/station-keys.json belongs to you and not to the container user.
seed: .env ## Load the demo data and print the API keys (ARGS=--rotate-keys to rotate them)
	@mkdir -p .secrets
	$(COMPOSE) run --rm --user "$$(id -u):$$(id -g)" -v "$(CURDIR)/.secrets:/secrets" \
		migrate python -m willay.seed --keys-file /secrets/station-keys.json $(ARGS)

simulate: ## Station simulator against the local API (ARGS="--scenario rimac --seed 42")
	cd backend && uv run simulate --keys-file ../.secrets/station-keys.json $(ARGS)

demo: ## Guided Rímac scenario (VIG-30)
	@echo "make demo arrives with VIG-30 (Sprint 7)." && exit 1
