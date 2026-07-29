.PHONY: help install up down logs dev api worker console migrate revision seed test lint fmt clean
.DEFAULT_GOAL := help

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## create the venv and install python + console dependencies
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	cd apps/console && npm install

up: ## start backing services
	docker compose up -d
	@echo "postgres :5432  redis :6379  minio :9001  mlflow :5000  grafana :3001"

down: ## stop backing services
	docker compose down

logs: ## tail service logs
	docker compose logs -f --tail=100

dev: ## run api and console together
	@trap 'kill 0' EXIT; \
	$(MAKE) api & \
	$(MAKE) console & \
	wait

api: ## run the api with reload
	$(VENV)/bin/uvicorn nexus.api.main:app --reload --port 8000

worker: ## run the celery worker
	$(VENV)/bin/celery -A nexus.worker.celery_app worker -l info

console: ## run the next.js console
	cd apps/console && npm run dev

migrate: ## apply migrations
	$(VENV)/bin/alembic upgrade head

revision: ## autogenerate a migration: make revision m="add x"
	$(VENV)/bin/alembic revision --autogenerate -m "$(m)"

seed: ## load demo data
	$(PY) -m nexus.seed

test: ## run tests
	$(VENV)/bin/pytest -q

lint: ## ruff + mypy
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/mypy src

fmt: ## format and autofix
	$(VENV)/bin/ruff format src tests
	$(VENV)/bin/ruff check --fix src tests

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -prune -exec rm -rf {} +
