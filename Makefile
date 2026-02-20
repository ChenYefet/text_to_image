.PHONY: run test lint format coverage clean docker-build docker-up docker-down

run:
	uvicorn main:fastapi_application --host 127.0.0.1 --port 8000 --reload

test:
	pytest tests/ -q

lint:
	ruff check application/ tests/

format:
	ruff format application/ tests/

format-check:
	ruff format --check application/ tests/

coverage:
	pytest --cov=application --cov-report=term-missing --cov-fail-under=80

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
	find . -type f -name "*.pyc" -delete 2>/dev/null; \
	rm -rf .coverage htmlcov .pytest_cache; \
	true
