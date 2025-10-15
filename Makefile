# Makefile for Omni Backend

.PHONY: help install install-test test test-unit test-integration test-cov test-fast clean lint format run build

# Default target
help:
	@echo "Omni Backend - Available Commands:"
	@echo ""
	@echo "  make install          - Install production dependencies"
	@echo "  make install-test     - Install test dependencies"
	@echo "  make test            - Run all tests"
	@echo "  make test-unit       - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo "  make test-cov        - Run tests with coverage report"
	@echo "  make test-fast       - Run fast tests (exclude slow)"
	@echo "  make test-smoke      - Run smoke tests"
	@echo "  make lint            - Run linters"
	@echo "  make format          - Format code"
	@echo "  make clean           - Clean build artifacts and cache"
	@echo "  make run             - Run the application"
	@echo "  make build           - Build executable"
	@echo ""

# Installation
install:
	pip install -r requirements.txt

install-test:
	pip install -r requirements-test.txt

# Testing
test:
	pytest -v

test-unit:
	pytest -v -m unit

test-integration:
	pytest -v -m integration

test-api:
	pytest -v -m api

test-websocket:
	pytest -v -m websocket

test-capability:
	pytest -v -m capability

test-smoke:
	pytest -v -m smoke

test-cov:
	pytest --cov=src --cov-report=html --cov-report=term-missing
	@echo ""
	@echo "Coverage report generated in htmlcov/index.html"

test-fast:
	pytest -v -m "not slow"

test-parallel:
	pytest -v -n auto

test-watch:
	pytest-watch

# Code quality
lint:
	@echo "Running linters..."
	ruff check src/ tests/
	mypy src/
	@echo "Checking docstrings..."
	pydocstyle src/ --convention=google || true

lint-strict:
	@echo "Running strict linters..."
	ruff check src/ tests/
	mypy src/ --strict
	pydocstyle src/ --convention=google

docstring-check:
	@echo "Checking for missing docstrings..."
	python3 add_docstrings.py

docstring-lint:
	@echo "Linting docstring style..."
	pydocstyle src/ --convention=google

format:
	@echo "Formatting code..."
	ruff format src/ tests/
	ruff check --fix src/ tests/

# Cleaning
clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.coverage" -delete
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf htmlcov
	rm -rf dist
	rm -rf build
	rm -rf *.egg-info
	@echo "Clean complete!"

clean-all: clean
	rm -rf .venv
	rm -rf logs/*

# Running
run:
	python main.py

run-dev:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Building
build:
	python scripts/build.py

build-optimized:
	python scripts/build_scripts/nuitka_optimized.py

# Development
dev-setup: install install-test
	pre-commit install
	@echo ""
	@echo "Development environment setup complete!"
	@echo "Run 'make test' to verify everything works."

# Pre-commit
pre-commit:
	pre-commit run --all-files

# Database (if applicable)
db-migrate:
	alembic upgrade head

db-rollback:
	alembic downgrade -1

# Docker (if applicable)
docker-build:
	docker build -t omni-backend .

docker-run:
	docker run -p 8000:8000 omni-backend

# Documentation
docs:
	@echo "Opening documentation..."
	@echo "Available docs:"
	@echo "  - docs/architecture.md"
	@echo "  - docs/testing-guide.md"
	@echo "  - docs/build-guide.md"
	@echo "  - docs/signing-guide.md"

# CI/CD helpers
ci-test:
	pytest --cov=src --cov-report=xml --cov-report=term

ci-lint:
	ruff check src/ tests/
	mypy src/ --no-error-summary

# Versioning
version:
	@python -c "from src.configs.settings import settings; print(f'Version: {settings.VERSION if hasattr(settings, \"VERSION\") else \"unknown\"}')" || echo "Version not configured"

# Environment
env-example:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example"; \
		echo "Please update .env with your configuration"; \
	else \
		echo ".env already exists"; \
	fi
