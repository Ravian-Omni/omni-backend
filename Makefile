# Makefile
.PHONY: install dev test lint format run clean

install:
	uv sync

dev:
	uv sync --dev

test:
	uv run pytest

lint:
	uv run black --check .
	uv run isort --check-only .
	uv run mypy .

format:
	uv run black .
	uv run isort .

run:
	uv run uvicorn main:app --reload

run-prod:
	uv run gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker

clean:
	rm -rf .venv
	rm -rf __pycache__
	rm -rf .pytest_cache
	rm -rf .mypy_cache