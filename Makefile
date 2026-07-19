.PHONY: install format lint typecheck test test-unit test-integration compose-up compose-down compose-logs migrate api worker

install:
	python -m pip install -e '.[dev]'

format:
	ruff format src tests
	ruff check --fix src tests

lint:
	ruff format --check src tests
	ruff check src tests

typecheck:
	mypy src

test:
	pytest

test-unit:
	pytest -m 'not integration and not manual'

test-integration:
	pytest -m integration

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f api worker

migrate:
	alembic upgrade head

api:
	uvicorn video_crawler.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	python -m video_crawler.worker.main
