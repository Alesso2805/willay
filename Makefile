SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose

.PHONY: help up down lint lint-backend lint-dashboard test test-backend test-dashboard migrate seed demo

help: ## Lista los comandos disponibles
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: .env ## Levanta todo el stack (migrate corre antes que api y workers)
	$(COMPOSE) up -d --build --wait

.env:
	cp .env.example .env
	@echo "Creado .env desde .env.example (credenciales solo de desarrollo)."

down: ## Detiene el stack (conserva los volúmenes)
	$(COMPOSE) down

lint: lint-backend lint-dashboard ## Ruff, Mypy y ESLint

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy

lint-dashboard:
	cd dashboard && npm run lint

test: test-backend test-dashboard ## Pytest (unit e integración con Docker) y Vitest

test-backend:
	cd backend && uv run pytest

test-dashboard:
	cd dashboard && npm test -- --watch=false

migrate: .env ## Aplica las migraciones de Alembic con vigia_owner
	$(COMPOSE) run --rm migrate

# Corre con tu uid para que .secrets/station-keys.json sea tuyo y no del usuario del contenedor.
seed: .env ## Carga los datos demo e imprime las API keys (ARGS=--rotate-keys para rotarlas)
	@mkdir -p .secrets
	$(COMPOSE) run --rm --user "$$(id -u):$$(id -g)" -v "$(CURDIR)/.secrets:/secrets" \
		migrate python -m vigia.seed --keys-file /secrets/station-keys.json $(ARGS)

demo: ## Escenario Rímac guiado (VIG-30)
	@echo "make demo llega con VIG-30 (Sprint 6)." && exit 1
