.PHONY: help setup dev server worker beat tailwind test lint format typecheck migrate migrations docker-up docker-down docker-build

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Setup

setup: ## Initial project setup (copy env, install deps, migrate)
	@test -f .env || cp .env.example .env
	pip install -r requirements.txt
	cd theme/static_src && npm install
	python manage.py migrate
	@echo ""
	@echo "Setup complete. Run 'python manage.py createsuperuser' to create an admin account."
	@echo "Then run 'make dev' to start the app."

# Development

dev: ## Start Django server, worker, beat, and Tailwind watcher (requires 4 terminals + Redis)
	@echo "Start these in separate terminals (requires a running Redis — see REDIS_URL):"
	@echo "  make server    - Django dev server"
	@echo "  make worker    - Celery worker"
	@echo "  make beat      - Celery beat scheduler"
	@echo "  make tailwind  - Tailwind CSS watcher"

server: ## Start Django dev server
	python manage.py runserver

worker: ## Start Celery worker
	celery -A config worker -l info --concurrency 2

beat: ## Start Celery beat scheduler
	celery -A config beat -l info

tailwind: ## Start Tailwind CSS watcher
	cd theme/static_src && npm run start

# Database

migrate: ## Run database migrations
	python manage.py migrate

migrations: ## Create new migrations
	python manage.py makemigrations

# Code quality

test: ## Run tests
	pytest

test-cov: ## Run tests with coverage
	pytest --cov=apps --cov-report=term-missing

lint: ## Run linter and format check
	ruff check .
	ruff format --check .

format: ## Auto-fix lint and formatting issues
	ruff check --fix .
	ruff format .

typecheck: ## Run mypy type checker
	mypy apps/ config/ providers/ tests/ --ignore-missing-imports

# Docker

docker-up: ## Start all Docker services
	docker compose up -d

docker-down: ## Stop all Docker services
	docker compose down

docker-build: ## Rebuild Docker images
	docker compose build

docker-logs: ## Tail logs from all Docker services
	docker compose logs -f

docker-prod: ## Start production Docker setup (with Caddy)
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
